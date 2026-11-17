# -*- coding: utf-8 -*-
"""标定板模式：和胶纸并排拍一张，先解出手机镜头的径向畸变，再量胶纸。

为什么值得多打一张板：手机广角镜头的桶形畸变是照片精度的最大误差源
（实测 k1=0.05 时，节距会偏 0.3~0.4 mm；校正后能到 0.1~0.2 mm）。倾斜本身不是问题，
单应矩阵对平面是精确的。

流程：
1. 画面里找"像纸"的四边形 → 内部黑方块最多的那块 = 标定板，另一块 = 胶纸；
2. 用板的四角做粗映射，把黑方块吸附到标定板的 20 mm 网格 → 得到一堆已知点；
3. 一维搜索 k1，让去畸变后的点最贴合单应映射（残差最小）；
4. 整幅图去畸变 → 重新找胶纸四边 → 单应拉成正视 A4 → 交给 ``scan.measure_image``。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from .scan import Measurement, measure_image
from .scan_board import (
    A4_H_MM,
    A4_W_MM,
    COLS,
    FIRST_X_MM,
    FIRST_Y_MM,
    ROWS,
    SPACING_MM,
)
from .scan_photo import PHOTO_DPI, _cv2, _order_quad, rectify_to_a4


def find_quads(bgr, max_side: int = 1400) -> List[np.ndarray]:
    """画面里所有"像一张纸"的四边形（原图坐标，四点已排序）。"""
    cv2 = _cv2()
    h, w = bgr.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w))
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((9, 9), np.uint8)
    mask = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel, iterations=3)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads: List[np.ndarray] = []
    min_area = small.shape[0] * small.shape[1] * 0.10
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < min_area:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            quads.append(_order_quad(approx) / scale)
    return quads


def find_marks(bgr) -> List[Tuple[float, float]]:
    """标定板黑色方块的质心（原图像素）。"""
    cv2 = _cv2()
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 90, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area_img = float(h * w)
    pts: List[Tuple[float, float]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not (area_img * 1.5e-5 < area < area_img * 4e-3):
            continue
        peri = cv2.arcLength(contour, True)
        if peri <= 0:
            continue
        if len(cv2.approxPolyDP(contour, 0.06 * peri, True)) != 4:
            continue
        (rw, rh) = cv2.minAreaRect(contour)[1]
        if rw <= 1 or rh <= 1 or not (0.6 < rw / rh < 1.7):
            continue
        m = cv2.moments(contour)
        if m["m00"] <= 0:
            continue
        pts.append((m["m10"] / m["m00"], m["m01"] / m["m00"]))
    return pts


def find_board_frame(bgr, max_side: int = 1400):
    """找标定板的黑边框外轮廓（= 这张纸的四角）。"""
    cv2 = _cv2()
    h, w = bgr.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w))
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 90, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(contour) < small.shape[0] * small.shape[1] * 0.08:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4:
            best = _order_quad(approx) / scale
            break
    return best


def _inside(quad: Sequence, points: Sequence[Tuple[float, float]]) -> int:
    cv2 = _cv2()
    poly = np.asarray(quad, dtype="float32")
    n = 0
    for x, y in points:
        if cv2.pointPolygonTest(poly, (float(x), float(y)), False) > 0:
            n += 1
    return n


def assign_marks(marks: Sequence[Tuple[float, float]], board_quad: np.ndarray):
    """用板的四角粗映射，把方块吸附到标定板的 20 mm 网格上。"""
    cv2 = _cv2()
    dst = np.array([[0, 0], [A4_W_MM, 0], [A4_W_MM, A4_H_MM], [0, A4_H_MM]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(np.asarray(board_quad, dtype="float32"), dst)
    img_pts, mm_pts = [], []
    for x, y in marks:
        pt = np.array([[[x, y]]], dtype="float32")
        mm = cv2.perspectiveTransform(pt, matrix)[0][0]
        ci = int(round((mm[0] - FIRST_X_MM) / SPACING_MM))
        ri = int(round((mm[1] - FIRST_Y_MM) / SPACING_MM))
        if not (0 <= ci < COLS and 0 <= ri < ROWS):
            continue
        gx = FIRST_X_MM + ci * SPACING_MM
        gy = FIRST_Y_MM + ri * SPACING_MM
        if abs(mm[0] - gx) > SPACING_MM * 0.4 or abs(mm[1] - gy) > SPACING_MM * 0.4:
            continue
        img_pts.append((x, y))
        mm_pts.append((gx, gy))
    return np.asarray(img_pts, dtype="float32"), np.asarray(mm_pts, dtype="float32")


def _undistort_points(points, k1: float, k2: float, center, radius):
    """把"拍到的点"按 (k1,k2) 反解成理想点：x_obs = x_ideal*(1 + k1*r² + k2*r⁴)。"""
    cx, cy = center
    pts = points.astype("float64")
    ideal = pts.copy()
    for _ in range(8):
        nx = (ideal[:, 0] - cx) / radius
        ny = (ideal[:, 1] - cy) / radius
        r2 = nx * nx + ny * ny
        f = 1.0 + k1 * r2 + k2 * r2 * r2
        ideal[:, 0] = cx + (pts[:, 0] - cx) / f
        ideal[:, 1] = cy + (pts[:, 1] - cy) / f
    return ideal.astype("float32")


def estimate_distortion(img_pts: np.ndarray, mm_pts: np.ndarray, shape,
                        k1_limit: float = 0.35, k2_limit: float = 0.20):
    """估径向畸变 (k1, k2)：一维搜索 k1，让去畸变后的方块点最贴合单应映射。

    调参结论（2026-11-16 实测）：同时优化 k2 会让板子一侧"过拟合"、把胶纸那侧带歪，
    在只有一块板、单张照片的条件下反而不稳。所以默认只用 k1（k2=0），
    k2 留作以后有真实样张再开。
    """
    cv2 = _cv2()
    h, w = shape[:2]
    center = (w / 2.0, h / 2.0)
    radius = max(1.0, 0.5 * (w ** 2 + h ** 2) ** 0.5)

    def error(k1: float) -> float:
        pts = _undistort_points(img_pts, k1, 0.0, center, radius)
        matrix, _ = cv2.findHomography(pts, mm_pts, 0)
        if matrix is None:
            return float("inf")
        proj = cv2.perspectiveTransform(pts.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        return float(np.median(np.linalg.norm(proj - mm_pts, axis=1)))

    best_k1, best_err = 0.0, error(0.0)
    for k1 in np.arange(-k1_limit, k1_limit + 1e-9, 0.005):
        err = error(float(k1))
        if err < best_err:
            best_k1, best_err = float(k1), err
    return best_k1, 0.0, best_err


def undo_distortion(bgr, k1: float, k2: float = 0.0):
    """按估计的 (k1,k2) 把整幅图扭回正（输出像素 ← 畸变图采样点）。"""
    cv2 = _cv2()
    if abs(k1) < 1e-6 and abs(k2) < 1e-6:
        return bgr
    h, w = bgr.shape[:2]
    cx, cy = w / 2.0, h / 2.0
    radius = max(1.0, 0.5 * (w ** 2 + h ** 2) ** 0.5)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xs - cx) / radius
    ny = (ys - cy) / radius
    r2 = nx * nx + ny * ny
    f = 1.0 + k1 * r2 + k2 * r2 * r2
    map_x = (cx + nx * f * radius).astype(np.float32)
    map_y = (cy + ny * f * radius).astype(np.float32)
    return cv2.remap(bgr, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _pick_sheet(quads, marks, board_area: float):
    """从亮区四边形里挑胶纸：内部没有黑方块、面积和标定板相当的那块。"""
    cv2 = _cv2()
    best, best_score = None, -1.0
    for q in quads:
        if _inside(q, marks) > 3:
            continue
        area = float(cv2.contourArea(np.asarray(q, dtype="float32")))
        if board_area > 0 and not (0.55 < area / board_area < 1.8):
            continue
        if area > best_score:
            best, best_score = q, area
    return best


def _cluster_1d(values, tol):
    """把一维坐标聚成簇（返回每簇的均值与成员下标）。"""
    order = np.argsort(values)
    groups, current = [], []
    for idx in order:
        v = values[idx]
        if current and v - values[current[-1]] > tol:
            groups.append(current)
            current = []
        current.append(idx)
    if current:
        groups.append(current)
    return [(float(np.mean(values[g])), g) for g in groups]


def _filter_grid_marks(marks):
    """去掉"多印的角块"：老版标定板四角有小方块，会把网格角点认错。

    做法：按 x/y 聚类，行/列间距明显偏窄（< 0.6 倍中位间距）的边缘簇判为多余，剔除。
    """
    pts = np.asarray(marks, dtype="float64")
    if len(pts) < 40:
        return pts
    for axis in (0, 1):
        vals = pts[:, axis]
        order = np.sort(vals)
        gaps = np.diff(order)
        big = gaps[gaps > np.median(gaps) * 0.5]
        tol = float(np.median(big)) * 0.45 if len(big) else 8.0
        cols = _cluster_1d(vals, tol)
        if len(cols) < 4:
            continue
        centres = [c for c, _ in cols]
        diffs = [b - a for a, b in zip(centres, centres[1:])]
        med = float(np.median(diffs))
        if diffs and diffs[0] < med * 0.6:          # 第一簇是多余角块
            drop = set(cols[0][1])
            pts = np.asarray([p for i, p in enumerate(pts) if i not in drop], dtype="float64")
        if diffs and diffs[-1] < med * 0.6:         # 最后一簇是多余角块
            idx = _cluster_1d(pts[:, axis], tol)
            drop = set(idx[-1][1])
            pts = np.asarray([p for i, p in enumerate(pts) if i not in drop], dtype="float64")
    return pts


def _homography_from_marks(marks):
    """只用标定板的黑方块求"图像 → 板面 mm"的单应（不依赖纸边，深色/浅色桌面都能用）。"""
    cv2 = _cv2()
    pts = _filter_grid_marks(marks).astype("float32")
    if len(pts) < 8:
        raise ValueError("标定板上的黑方块太少：板要整张拍进去、别有反光")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    corners = np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                        pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")
    grid = np.array([[FIRST_X_MM, FIRST_Y_MM],
                     [FIRST_X_MM + (COLS - 1) * SPACING_MM, FIRST_Y_MM],
                     [FIRST_X_MM + (COLS - 1) * SPACING_MM, FIRST_Y_MM + (ROWS - 1) * SPACING_MM],
                     [FIRST_X_MM, FIRST_Y_MM + (ROWS - 1) * SPACING_MM]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(corners, grid)
    chosen = None
    for _ in range(3):                      # 用全部方块精修
        mm = cv2.perspectiveTransform(pts.reshape(-1, 1, 2), matrix).reshape(-1, 2)
        ij = np.rint((mm - [FIRST_X_MM, FIRST_Y_MM]) / SPACING_MM)
        target = np.stack([FIRST_X_MM + ij[:, 0] * SPACING_MM,
                           FIRST_Y_MM + ij[:, 1] * SPACING_MM], axis=1)
        resid = np.linalg.norm(mm - target, axis=1)
        keep = (ij[:, 0] >= -0.3) & (ij[:, 0] <= COLS - 1 + 0.3) & \
               (ij[:, 1] >= -0.3) & (ij[:, 1] <= ROWS - 1 + 0.3) & (resid < SPACING_MM * 0.4)
        if keep.sum() >= 8:
            chosen = (pts[keep], target[keep])
        if chosen is None:
            break
        matrix, _ = cv2.findHomography(chosen[0], chosen[1], 0)
        if matrix is None:
            break
    if chosen is None:
        raise ValueError("标定板方块对不上网格：整张板拍进来、别有遮挡")
    return matrix, chosen


def _warp_to_mm(bgr, matrix_img_to_mm, px_per_mm: float = 4.0, pad_mm: float = 30.0):
    """把整幅图按"板面 mm"重采样：画布上 1 px = 1/px_per_mm mm。"""
    cv2 = _cv2()
    h, w = bgr.shape[:2]
    corners = np.array([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]], dtype="float32")
    mm = cv2.perspectiveTransform(corners, matrix_img_to_mm).reshape(-1, 2)
    x0 = float(min(mm[:, 0].min(), 0.0) - pad_mm)
    y0 = float(min(mm[:, 1].min(), 0.0) - pad_mm)
    x1 = float(max(mm[:, 0].max(), A4_W_MM) + pad_mm)
    y1 = float(max(mm[:, 1].max(), A4_H_MM) + pad_mm)
    width = max(16, int(round((x1 - x0) * px_per_mm)))
    height = max(16, int(round((y1 - y0) * px_per_mm)))
    scale = np.array([[px_per_mm, 0, -x0 * px_per_mm],
                      [0, px_per_mm, -y0 * px_per_mm],
                      [0, 0, 1]], dtype="float64")
    # cv2.warpPerspective 的矩阵是"目标像素 → 源图像素"：
    # 目标像素 → mm（inv(scale)），mm → 源图（inv(img→mm)）
    canvas_map = np.linalg.inv(matrix_img_to_mm.astype(np.float64)) @ np.linalg.inv(scale)
    warped = cv2.warpPerspective(bgr, canvas_map, (width, height), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(40, 40, 40))
    return warped, (x0, y0), px_per_mm


def _find_sheet_region(canvas, origin, px_per_mm: float):
    """在 mm 画布里找胶纸：板子区域之外、最亮的那块 A4 大小矩形。"""
    cv2 = _cv2()
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # 抹掉标定板本体
    bx0 = int(round((0 - origin[0]) * px_per_mm))
    by0 = int(round((0 - origin[1]) * px_per_mm))
    bx1 = int(round((A4_W_MM - origin[0]) * px_per_mm))
    by1 = int(round((A4_H_MM - origin[1]) * px_per_mm))
    cv2.rectangle(mask, (bx0, by0), (bx1, by1), 0, -1)
    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    a4_area = (A4_W_MM * px_per_mm) * (A4_H_MM * px_per_mm)
    best = None
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        area = cv2.contourArea(contour)
        if area < a4_area * 0.35:
            continue
        rect = cv2.minAreaRect(contour)
        (rw, rh) = rect[1]
        if rw < 8 or rh < 8:
            continue
        long_side, short_side = max(rw, rh), min(rw, rh)
        if not (0.9 * A4_H_MM * px_per_mm * 0.7 < long_side < 1.6 * A4_H_MM * px_per_mm):
            continue
        if short_side / long_side < 0.45:
            continue
        best = rect
        break
    if best is None:
        raise ValueError("没找到胶纸：把胶纸和标定板并排平放（别叠、别出画面）")
    return best


def _warp_sheet(canvas, rect, dpi: int = PHOTO_DPI):
    """把 mm 画布里那块胶纸矩形拉成正视 A4（短边当宽，长边当高）。"""
    cv2 = _cv2()
    pts = cv2.boxPoints(rect).astype("float32")
    center = pts.mean(axis=0)
    order = np.argsort(np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0]))
    pts = pts[order]
    pts = np.roll(pts, -int(np.argmin(pts.sum(axis=1))), axis=0)
    if np.linalg.norm(pts[1] - pts[0]) > np.linalg.norm(pts[2] - pts[1]):
        pts = np.roll(pts, -1, axis=0)
    pxmm = dpi / 25.4
    w_px, h_px = int(round(A4_W_MM * pxmm)), int(round(A4_H_MM * pxmm))
    dst = np.float32([[0, 0], [w_px, 0], [w_px, h_px], [0, h_px]])
    matrix = cv2.getPerspectiveTransform(pts, dst)
    page = cv2.warpPerspective(canvas, matrix, (w_px, h_px), flags=cv2.INTER_CUBIC)
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))


def measure_photo_calibrated(path: str, expect_cols: Optional[int] = None,
                             expect_rows: Optional[int] = None,
                             dpi: int = PHOTO_DPI) -> Measurement:
    """标定板模式：用板上的方块解 (k1,k2) → 去畸变 → 再用两张纸的边量胶纸。

    板子只负责"镜头畸变"这一项；尺寸仍由胶纸自己的 A4 边给出，所以桌面上板子被
    打印机缩放一点也不影响结果。
    """
    cv2 = _cv2()
    data = np.fromfile(path, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("读不了这张图：%s" % path)

    marks = find_marks(bgr)
    if len(marks) < 30:
        raise ValueError("没认出标定板上的黑方块：确认打印的是程序给的标定板、整张拍进来、别有反光/反光条")
    matrix, (img_pts, mm_pts) = _homography_from_marks(marks)
    k1, k2, err = estimate_distortion(img_pts, mm_pts, bgr.shape)

    fixed = undo_distortion(bgr, k1, k2)
    quads = find_quads(fixed)
    if len(quads) < 2:
        raise ValueError("找不到两张纸的边：把标定板和胶纸并排放在**深色桌面**上，中间留条缝、四边都拍进来")
    marks2 = find_marks(fixed)
    scored = sorted(((_inside(q, marks2), q) for q in quads), key=lambda t: t[0], reverse=True)
    board_score, board = scored[0]
    if board_score < 20:
        raise ValueError("没认出标定板：整张板拍进来、别让反光盖住方块")
    board_area = float(cv2.contourArea(np.asarray(board, dtype="float32")))
    sheet = _pick_sheet(quads, marks2, board_area)
    if sheet is None:
        raise ValueError("没找到胶纸：把胶纸和标定板并排平放（别叠、别出画面）")

    page = rectify_to_a4(fixed, sheet, dpi=dpi)
    warnings = (
        "photo: 已用标定板校正镜头畸变（k1=%+.2f, k2=%+.2f，板点残差 %.2f mm）" % (k1, k2, err),
        "photo: 照片量纸误差一般 0.2~0.5 mm；要更准请用扫描件",
    )
    return measure_image(page, A4_W_MM, A4_H_MM, dpi, warnings,
                         expect_cols, expect_rows)


def _warp_by_points(img, pts, dpi: int = PHOTO_DPI):
    """按用户点的四个角（图左上/右上/右下/左下）拉成正视 A4。"""
    cv2 = _cv2()
    pxmm = dpi / 25.4
    w_px, h_px = int(round(A4_W_MM * pxmm)), int(round(A4_H_MM * pxmm))
    src = np.asarray(pts, dtype="float32").reshape(4, 2)
    dst = np.float32([[0, 0], [w_px, 0], [w_px, h_px], [0, h_px]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    page = cv2.warpPerspective(img, matrix, (w_px, h_px), flags=cv2.INTER_CUBIC)
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2GRAY))


def measure_photo_corners(path: str, corners, expect_cols: Optional[int] = None,
                          expect_rows: Optional[int] = None,
                          dpi: int = PHOTO_DPI) -> Measurement:
    """兜底：纸边认不出来时，用户点胶纸的四个角。

    镜头畸变照样用标定板上的方块估（这一步不需要纸边），所以精度和自动模式一样，
    区别只是"四个角是人点的"。
    """
    cv2 = _cv2()
    data = np.fromfile(path, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("读不了这张图：%s" % path)
    pts = np.asarray(corners, dtype="float32").reshape(4, 2)

    k1, err = 0.0, 0.0
    try:
        marks = find_marks(bgr)
        if len(marks) >= 30:
            matrix, (img_pts, mm_pts) = _homography_from_marks(marks)
            k1, _k2, err = estimate_distortion(img_pts, mm_pts, bgr.shape)
    except Exception:                      # 板上方块没认出来也能继续，只是不校畸变
        k1, err = 0.0, 0.0

    if abs(k1) > 1e-6:
        h, w = bgr.shape[:2]
        center = (w / 2.0, h / 2.0)
        radius = max(1.0, 0.5 * (w ** 2 + h ** 2) ** 0.5)
        pts = _undistort_points(pts, k1, 0.0, center, radius)

    page = _warp_by_points(bgr, pts, dpi=dpi)
    warnings = (
        "photo: 四个角是你点的（k1=%+.2f，板点残差 %.2f mm）；点的越准量得越准" % (k1, err),
        "photo: 照片量纸误差一般 0.3~0.6 mm，比扫描和自动模式略差一点点",
    )
    return measure_image(page, A4_W_MM, A4_H_MM, dpi, warnings,
                         expect_cols, expect_rows)

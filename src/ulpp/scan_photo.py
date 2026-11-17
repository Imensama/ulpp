# -*- coding: utf-8 -*-
"""拍照量纸：手机随手拍一张 A4 胶纸 → 电脑把它拉成正视 A4 → 走同一套格阵拟合。

不打印标定板：**A4 纸自己就是标尺**（210×297）。只要有整张纸的四条边，
单应矩阵就能把透视/轻微倾斜都吸收掉；纸外的桌面请用深色（提高反差）。

依赖 OpenCV（可选）：``pip install opencv-python-headless``。没装也能用扫描/预设，
只是「用照片量」会提示装一下。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PIL import Image

from .scan import Measurement, measure_image

A4_W_MM, A4_H_MM = 210.0, 297.0
PHOTO_DPI = 300


def _cv2():
    try:
        import cv2  # type: ignore
    except Exception as exc:                      # pragma: no cover - 没装 opencv
        raise RuntimeError("没装 OpenCV，暂时只能用扫描件或预设（pip install opencv-python-headless）") from exc
    return cv2


def _order_quad(points):
    """四个角按 左上/右上/右下/左下 排好（绕质心定序，斜拍/转着拍也不会乱）。"""
    import numpy as np

    pts = np.asarray(points, dtype="float32").reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    order = np.argsort(angles)              # 逆时针（图像坐标 y 向下）
    pts = pts[order]
    # 从最左上的那个角开始
    start = int(np.argmin(pts.sum(axis=1)))
    pts = np.roll(pts, -start, axis=0)
    # 保证顺序是 TL → TR → BR → BL（叉积为正在图像坐标里是顺时针）
    cross = 0.0
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        cross += x1 * y2 - x2 * y1
    if cross < 0:
        pts = pts[[0, 3, 2, 1]]
    return pts


def find_paper_quad(bgr, max_side: int = 1400):
    """找整张 A4 的四个角。返回原图坐标下的 (4,2) 数组，失败抛 ValueError。"""
    cv2 = _cv2()
    import numpy as np

    h, w = bgr.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w))
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    area_total = float(small.shape[0] * small.shape[1])

    candidates = []
    # ① 纸比桌面亮：Otsu + 形态学闭运算
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = np.ones((9, 9), np.uint8)
    mask = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel, iterations=3)
    candidates.append(mask)
    # ② 边缘检测兜底
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, kernel, iterations=2)
    candidates.append(edges)

    for mask in candidates:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
            if cv2.contourArea(contour) < area_total * 0.25:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) == 4:
                quad = _order_quad(approx)
                return quad / scale
    raise ValueError("没找到整张 A4 的四条边：把纸单独放在深色桌面上、四边都拍进来、别裁边")


def rectify_to_a4(bgr, quad, dpi: int = PHOTO_DPI) -> Image.Image:
    """把纸的四个角拉到标准 A4 比例（300dpi 默认 ≈ 2480×3508）。"""
    cv2 = _cv2()
    import numpy as np

    w = int(round(A4_W_MM / 25.4 * dpi))
    h = int(round(A4_H_MM / 25.4 * dpi))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(np.asarray(quad, dtype="float32"), dst)
    warped = cv2.warpPerspective(bgr, matrix, (w, h), flags=cv2.INTER_CUBIC)
    return Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)).convert("L")


def measure_photo(path: str, expect_cols: Optional[int] = None,
                  expect_rows: Optional[int] = None,
                  dpi: int = PHOTO_DPI) -> Measurement:
    """一张手机照片 → 校正 → 量格阵。"""
    cv2 = _cv2()
    import numpy as np

    data = np.fromfile(path, dtype=np.uint8)      # 兼容中文路径
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("读不了这张图：%s" % path)
    quad = find_paper_quad(bgr)
    page = rectify_to_a4(bgr, quad, dpi=dpi)
    warnings = ["photo: 这是照片量的，误差通常 0.3~1 mm；dpi=%d" % dpi]
    return measure_image(page, A4_W_MM, A4_H_MM, dpi, warnings,
                         expect_cols, expect_rows)

# -*- coding: utf-8 -*-
"""试打自动纠偏：打一张校准页，再从扫描件里量出「打印内容相对纸」的偏移。

以前要靠人拿尺子在校准页上量 X/Y，再手填 ``PrinterProfile.offset_x_mm / offset_y_mm``。
这里把「量」这一步自动化：打校准页 → 扫描 → 量出偏移。本模块只管纯逻辑，
出图用 ``make_page_pdf``，读扫描件用 ``measure_offset``，写回配置由调用方做
（``offset = -dx``，因为 PrinterProfile 的语义是「把内容往右/往下挪多少」）。

用法：
    from ulpp.offset_calib import make_page_pdf, measure_offset
    make_page_pdf(grid, "校准页.pdf")            # 打印时必须 100%、不缩放
    r = measure_offset("扫描.png", grid)         # dpi 不给就按图宽反推
    if r.confidence >= 0.5:
        offset_x_mm, offset_y_mm = -r.dx_mm, -r.dy_mm

算法（不认纸边，认格线）：
1. 转灰度 → 用纸白减去原图去掉光照不均 → Otsu 阈值 → 墨迹掩膜；
2. 按 ``grid`` 算出每条格线「应该」在哪，只在期望位置 ±3 mm 的窗里找实际线，
   所以纸摆歪 ≲1°、边被裁掉一点都没关系（歪太多会明确报「找不到格线」）；
3. 每条边取格阵正中一小段投影，用暗度做亚像素重心；几十条边的残差取中位数
   （顺便用最小二乘看有没有缩放），一条边被污点带歪不至于毁掉结果。

精度预期：300 dpi 扫描约 ±0.1 mm（1 px = 0.085 mm）；手机拍照受纸翘影响 ±0.3~0.5 mm。
量不出来时（空白、全黑、长宽比不是 A4、线太淡）返回 ``confidence < 0.3`` 并在
``warnings`` 里写清原因，**不抛异常**。

只用 Pillow + numpy（不引 reportlab / OpenCV），Linux 上没有中文字体也能跑。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

try:                                  # 量偏移要算二维投影；没装 numpy 时只保留「出校准页」
    import numpy as np

    _HAS_NUMPY = True
except ImportError:                   # pragma: no cover - 轻量 exe 走的就是这条
    np = None                         # type: ignore[assignment]
    _HAS_NUMPY = False

from PIL import Image, ImageDraw, ImageFont

from .templates import GridSpec   # 和界面同一份 GridSpec（templates 再导出 config 的那个类）
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
DEFAULT_DPI = 300
FRAME_GRAY = 120           # 格子细线灰度：浅一点，打印不会糊成一坨
CORNER_MM = 5.0            # 四角角标的方块边长
MARK_INSET_MM = 5.0        # 角标距纸边
HEADER_TEXT = "校准页 / Calibration page — 请按 100% 实际大小打印"
BAND_MM = 16.0             # 每条边只取格阵正中一小段来量：纸歪 ≲1° 也不会糊成一片
SEARCH_MM = 3.0            # 期望位置附近的粗找窗口（硬上限，再大就认错线）
REFINE_MM = 1.0            # 精找窗口上限（还要再被相邻两条边的间距限制）
MIN_COVERAGE = 0.45        # 一条边上的墨迹要盖住这么长才算找到线
MIN_CONTRAST = 30.0        # 最深的那批像素比纸白浅多少以内就算空白/全黑
MIN_INK, MAX_INK = 0.0005, 0.70   # 阈值化后墨迹占比的合理区间
ASPECT_TOL = 0.08          # 长宽比允许的偏差（8%）


@dataclass
class OffsetResult:
    """一次纠偏测量的结果。dx/dy 是「打印内容相对纸」的偏移，正 = 偏右 / 偏下。"""

    dx_mm: float
    dy_mm: float
    confidence: float
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- 校准页
def _font(px: int):
    """中文字体：优先系统微软雅黑，取不到（比如 CI 是 Linux）退回 Pillow 自带字体。"""
    try:
        return ImageFont.truetype(FONT_PATH, int(px))
    except Exception:
        try:
            return ImageFont.load_default(size=int(px))
        except Exception:
            return ImageFont.load_default()


def render_page(grid: GridSpec, dpi: int = DEFAULT_DPI) -> Image.Image:
    """把校准页画成灰度图：每个格子的四边细线框 + 四角角标 + 一行中英页眉。"""
    px_per_mm = float(dpi) / 25.4
    width = max(1, int(round(float(grid.page_w) * px_per_mm)))
    height = max(1, int(round(float(grid.page_h) * px_per_mm)))
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)

    # 1) 每格四边的细线框：线的中心落在 grid 的理论位置上，300 dpi 下就是 1~2 px
    lw = max(1, int(round(float(dpi) / 300.0)))
    for row in range(int(grid.rows)):
        top = (grid.margin_top + row * grid.pitch_y) * px_per_mm
        bottom = top + grid.cell_h * px_per_mm
        for col in range(int(grid.cols)):
            left = (grid.margin_x + col * grid.pitch_x) * px_per_mm
            right = left + grid.cell_w * px_per_mm
            draw.rectangle([left, top, right, bottom], outline=FRAME_GRAY, width=lw)

    # 2) 四角角标：小实心方块，一眼看出打印有没有被缩放；太小/太长会被当成格线，别改成 L 形
    half_mark = 0.5 * CORNER_MM * px_per_mm
    inset = MARK_INSET_MM * px_per_mm
    for x, y in ((inset, inset), (width - inset, inset),
                 (inset, height - inset), (width - inset, height - inset)):
        draw.rectangle([x - half_mark, y - half_mark, x + half_mark, y + half_mark],
                       fill=0)

    # 3) 页眉：字高约 2.8 mm，只占顶部留白的中间，不会盖到第一行格线
    draw.text((int(round(10.0 * px_per_mm)), int(round(1.2 * px_per_mm))),
              HEADER_TEXT, font=_font(max(8, int(round(8.0 * float(dpi) / 72.0)))),
              fill=0)
    return img


def make_page_pdf(grid: GridSpec, path: str, dpi: int = DEFAULT_DPI) -> str:
    """按 grid 的节距/相位生成一张校准页 PDF（打印在普通 A4 上）。返回写出的路径。"""
    img = render_page(grid, dpi)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    img.save(path, "PDF", resolution=float(dpi))
    return path


# ---------------------------------------------------------------- 量图
def _fail(reason: str) -> OffsetResult:
    """量不出来的统一出口：置信度 0，原因写进 warnings。"""
    return OffsetResult(0.0, 0.0, 0.0, [reason])


def _otsu(values: np.ndarray) -> float:
    """Otsu 阈值：在 0~255 直方图上最大化类间方差。"""
    hist, _ = np.histogram(values, bins=256, range=(0.0, 256.0))
    hist = hist.astype(np.float64)
    total = float(hist.sum())
    if total <= 0.0:
        return 0.0
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256, dtype=np.float64)) / total
    sigma = (mu[-1] * omega - mu) ** 2 / np.maximum(omega * (1.0 - omega), 1e-12)
    return float(np.argmax(sigma))


def _mm_per_px(width: int, grid: GridSpec, dpi: Optional[float],
               warnings: List[str]) -> float:
    """1 px 对应多少 mm：给了 dpi 就按 dpi，否则按图宽 / 页宽反推。"""
    if dpi:
        return 25.4 / float(dpi)
    ppmm = float(width) / float(grid.page_w)
    warnings.append("dpi: 没给分辨率，按图宽 %.0f px / 页宽 %.0f mm 反推 %.0f dpi"
                    % (width, float(grid.page_w), ppmm * 25.4))
    return 1.0 / ppmm


def _edges_mm(first_mm: float, count: int, pitch_mm: float,
              cell_mm: float) -> List[float]:
    """一族边的理论位置（mm）：每格的近边 + 远边，去重排序。"""
    vals = []
    for i in range(int(count)):
        base = float(first_mm) + i * float(pitch_mm)
        vals.append(round(base, 4))
        vals.append(round(base + float(cell_mm), 4))
    return sorted(set(vals))


def _refine_half(gap_mm: float) -> float:
    """精找半径：不超过相邻两条边间距的一半（节距 - 格宽 常常只有 1.5~2 mm）。"""
    gap = abs(float(gap_mm))
    if gap <= 1e-6:
        return REFINE_MM
    return min(REFINE_MM, max(0.35, 0.5 * gap))


def _centroid(weights: np.ndarray, idx: int, half: int = 2) -> float:
    """idx 附近 ±half 像素的墨量重心（亚像素）。

    返回连续像素坐标：第 i 个像素覆盖 [i, i+1)，中心在 i+0.5，这样可以直接和
    ``mm / scale`` 算出来的理论坐标比（差一个 0.5 px = 0.04 mm 就是系统偏差）。
    """
    lo = max(0, int(idx) - half)
    hi = min(int(weights.size), int(idx) + half + 1)
    seg = weights[lo:hi].astype(np.float64)
    total = float(seg.sum())
    if total <= 0.0:
        return float(idx) + 0.5
    center = float((np.arange(lo, hi, dtype=np.float64) * seg).sum() / total)
    return center + 0.5


def _locate(weights: np.ndarray, cover: np.ndarray, exp_px: float,
            half_px: float) -> Optional[float]:
    """在 exp_px ± half_px 内找一条线，返回亚像素位置；找不到返回 None。"""
    lo = max(0, int(math.floor(exp_px - half_px)))
    hi = min(int(cover.size), int(math.ceil(exp_px + half_px)) + 1)
    if hi - lo < 1:
        return None
    seg = cover[lo:hi]
    if float(seg.max()) < MIN_COVERAGE:
        return None
    return _centroid(weights, lo + int(np.argmax(seg)))


def _residual_mm(pos_px: float, expected_mm: float, scale: float) -> float:
    """亚像素位置 → 残差（mm，实测 - 期望）。"""
    return pos_px * scale - expected_mm


def _summary(pairs: Sequence[Tuple[float, float]]) -> Tuple[float, float, float]:
    """(中位数, MAD, 缩放斜率)：pairs = [(理论位置 mm, 残差 mm)]。"""
    exp = np.array([p[0] for p in pairs], dtype=np.float64)
    res = np.array([p[1] for p in pairs], dtype=np.float64)
    center = float(np.median(res))
    mad = float(np.median(np.abs(res - center)))
    slope = 0.0
    if np.unique(exp).size >= 3:
        slope = float(np.polyfit(exp, res, 1)[0])
    return center, mad, slope


def _band_px(center_mm: float, size: int, scale: float) -> Tuple[int, int]:
    """格阵正中那一小段（``BAND_MM``）的像素区间 [lo, hi)，夹在画面里。"""
    middle = center_mm / scale
    half = 0.5 * BAND_MM / scale
    return max(0, int(math.floor(middle - half))), min(int(size),
                                                       int(math.ceil(middle + half)))


def _edge_patch(mask: np.ndarray, dark: np.ndarray, axis: str, exp_px: float,
                band: Tuple[int, int], half_px: float):
    """取一条边周围的窄条投影成一维：(墨量, 覆盖率, 起点像素)；取不到返回 None。

    axis="x" 表示要量竖线（沿 y 求和），此时 band 是 y 方向的那一小段；
    axis="y" 反之。只取格阵正中一小段（``BAND_MM``），纸歪 ≲1° 时线也不会糊掉。
    """
    n = mask.shape[1] if axis == "x" else mask.shape[0]
    lo = max(0, int(math.floor(exp_px - half_px)))
    hi = min(int(n), int(math.ceil(exp_px + half_px)) + 1)
    if hi - lo < 2 or band[1] - band[0] < 4:
        return None
    if axis == "x":
        weights = dark[band[0]:band[1], lo:hi].sum(axis=0)
        cover = mask[band[0]:band[1], lo:hi].mean(axis=0)
    else:
        weights = dark[lo:hi, band[0]:band[1]].sum(axis=1)
        cover = mask[lo:hi, band[0]:band[1]].mean(axis=1)
    return weights, cover, lo


def _edge_pos(mask: np.ndarray, dark: np.ndarray, axis: str, exp_px: float,
              band: Tuple[int, int], half_px: float) -> Optional[float]:
    """量一条边，返回亚像素位置（像素坐标）；这条边不在就返回 None。"""
    patch = _edge_patch(mask, dark, axis, exp_px, band, half_px)
    if patch is None:
        return None
    weights, cover, origin = patch
    local = _locate(weights, cover, exp_px - origin, half_px)
    return None if local is None else origin + local


def _measure_axis(mask: np.ndarray, dark: np.ndarray, axis: str,
                  expected: Sequence[float], band: Tuple[int, int],
                  gap_mm: float,
                  scale: float) -> Tuple[Optional[Tuple[float, float, float]], int]:
    """量一族边。返回 ((中位数, MAD, 斜率), 找到的条数)；一条都没找到返回 (None, 0)。

    先用最外侧两条边粗对齐（只有它们 ±3 mm 内不会有邻居），再拿粗偏移去逐条精找，
    这样节距 - 格宽只有 1.5 mm 时也不会认错线。
    """
    inner = 1.0 / scale
    near = _edge_pos(mask, dark, axis, expected[0] * inner, band, SEARCH_MM * inner)
    far = _edge_pos(mask, dark, axis, expected[-1] * inner, band, SEARCH_MM * inner)
    offsets = []
    if near is not None:
        offsets.append(near - expected[0] * inner)
    if far is not None:
        offsets.append(far - expected[-1] * inner)
    if not offsets:
        return None, 0
    offset = float(np.mean(offsets))

    half_px = _refine_half(gap_mm) * inner
    pairs = []
    for edge in expected:
        pos = _edge_pos(mask, dark, axis, edge * inner + offset, band, half_px)
        if pos is not None:
            pairs.append((float(edge), _residual_mm(pos, edge, scale)))
    if not pairs:
        return None, 0
    return _summary(pairs), len(pairs)


def _warnings_for(frac: float, scatter: float, slope: float,
                  dx: float, dy: float) -> List[str]:
    """把「量到了但可能不准」的情况写成提示（约定：fail: 前缀表示彻底没量出来）。"""
    out: List[str] = []
    if frac < 0.6:
        out.append("edges: 只找到 %.0f%% 的格线，可能扫描不全或被裁掉了边"
                   % (frac * 100.0))
    if scatter > 0.25:
        out.append("scatter: 各条边量出来散得有点开（MAD %.2f mm），检查纸有没有翘"
                   % scatter)
    if slope > 0.003:
        out.append("scale: 实测节距与理论差 %.1f%%，打印可能被缩放了（先确认 100%% 打印）"
                   % (slope * 100.0))
    if max(abs(dx), abs(dy)) > SEARCH_MM - 0.5:
        out.append("search: 偏移已经贴近 ±%.0f mm 搜索窗边缘，数字可能不准" % SEARCH_MM)
    return out


def measure_offset(image_path: str, grid: GridSpec,
                   dpi: Optional[float] = None) -> OffsetResult:
    """从扫描件/照片里量出实测位置与期望位置的差（正 = 偏右 / 偏下）。

    dpi 为 None 时按扫描件宽度 / grid.page_w 反推（假定整张 A4 都在画面里）。
    """
    if float(grid.page_w) <= 0 or float(grid.page_h) <= 0:
        return _fail("fail: grid 的页宽/页高不合法")
    if int(grid.cols) < 1 or int(grid.rows) < 1:
        return _fail("fail: grid 的行列数不合法")
    if not _HAS_NUMPY:
        return _fail("fail: 这台机器没装 numpy（pip install numpy 或装 photo extra 后可用）")

    try:
        with Image.open(image_path) as handle:
            gray = np.asarray(handle.convert("L"), dtype=np.uint8)
    except Exception as exc:  # 打不开、不是图、没权限：一律给低置信度，不抛
        return _fail("fail: 读不了这张图（%s）" % exc)
    if gray.ndim != 2 or gray.shape[0] < 8 or gray.shape[1] < 8:
        return _fail("fail: 图片太小或不是灰度图")

    height, width = int(gray.shape[0]), int(gray.shape[1])
    warnings: List[str] = []

    # 1) 长宽比先过关：不是整张 A4 的话，后面按 mm 换算全是错的
    want = float(grid.page_w) / float(grid.page_h)
    have = float(width) / float(height)
    if abs(have / want - 1.0) > ASPECT_TOL:
        return _fail("fail: 长宽比不像 A4（图 %.2f:1，A4 %.2f:1），可能裁过或没拍全"
                     % (have, want))

    scale = _mm_per_px(width, grid, dpi, warnings)

    # 2) 去光照不均：纸白（90 分位）减原图，越黑的线数值越大
    paper = float(np.percentile(gray, 90.0))
    dark = paper - gray.astype(np.float32)
    np.clip(dark, 0.0, 255.0, out=dark)

    # 3) 空白 / 全黑 / 太淡：拿"最深的那 0.5% 像素"看，细线只占千分之几也能看见
    peak = float(np.percentile(dark, 99.5))
    if peak < MIN_CONTRAST:
        mean = float(gray.mean())
        if mean <= 40.0:
            reason = "整张图几乎全黑（平均灰阶 %.0f）" % mean
        elif mean >= 215.0:
            reason = "整张图几乎全白（平均灰阶 %.0f），像空白页" % mean
        else:
            reason = "对比度太低（最深只比纸白深 %.0f 灰阶）" % peak
        return _fail("fail: " + reason)

    thresh = max(_otsu(dark), 0.4 * peak)
    mask = dark > thresh
    ink = float(mask.mean())
    if ink < MIN_INK:
        return _fail("fail: 阈值化后几乎没有墨迹（%.4f），图里找不到格线" % ink)
    if ink > MAX_INK:
        return _fail("fail: 阈值化后墨迹占了 %.0f%%，图太黑或太乱" % (ink * 100.0))

    # 4) 格阵在画面上的位置（用来挑「正中那一小段」来量）
    block_w = (int(grid.cols) - 1) * float(grid.pitch_x) + float(grid.cell_w)
    block_h = (int(grid.rows) - 1) * float(grid.pitch_y) + float(grid.cell_h)
    band_x = _band_px(float(grid.margin_x) + 0.5 * block_w, width, scale)
    band_y = _band_px(float(grid.margin_top) + 0.5 * block_h, height, scale)
    if band_x[1] - band_x[0] < 4 or band_y[1] - band_y[0] < 4:
        return _fail("fail: 格阵算出来的位置不在画面里，dpi 或 grid 可能不对")

    # 5) 理论位置 + 逐条边量残差
    exp_x = _edges_mm(grid.margin_x, grid.cols, grid.pitch_x, grid.cell_w)
    exp_y = _edges_mm(grid.margin_top, grid.rows, grid.pitch_y, grid.cell_h)
    stats_x, found_x = _measure_axis(mask, dark, "x", exp_x, band_y,
                                     float(grid.pitch_x) - float(grid.cell_w), scale)
    stats_y, found_y = _measure_axis(mask, dark, "y", exp_y, band_x,
                                     float(grid.pitch_y) - float(grid.cell_h), scale)
    if stats_x is None or stats_y is None:
        bad = "竖直格线" if stats_x is None else "水平格线"
        return _fail("fail: 找不到%s（打印太淡、扫描没扫全、偏移超过 ±%.0f mm，"
                     "或不是这张校准页）" % (bad, SEARCH_MM))

    dx, mad_x, slope_x = stats_x
    dy, mad_y, slope_y = stats_y
    total = len(exp_x) + len(exp_y)
    frac = (found_x + found_y) / float(total) if total else 0.0
    scatter = max(mad_x, mad_y)
    slope = max(abs(slope_x), abs(slope_y))

    # 6) 置信度：找到的边越多、残差越整齐、越不像被缩放，就越敢给数字
    conf = 0.95
    conf -= (1.0 - frac) * 0.45
    conf -= min(0.30, scatter / 0.6 * 0.30)
    conf -= min(0.20, slope / 0.02 * 0.20)
    conf = max(0.0, min(1.0, conf))

    warnings.extend(_warnings_for(frac, scatter, slope, dx, dy))
    return OffsetResult(dx_mm=round(dx, 3), dy_mm=round(dy, 3),
                        confidence=round(conf, 3), warnings=warnings)

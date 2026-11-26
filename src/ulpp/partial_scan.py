# -*- coding: utf-8 -*-
"""接着打：从扫描件判断哪些格已经用过了。

背景：用剩的半张纸，原来要一格一格右键标灰。这里把它自动化——扫一张（300dpi 平板最好），
量出格阵、逐格判断「空白 / 已用 / 拿不准」。

判据（真实样张验证过，分离度很大）：

- 每格统计「蓝偏」= B − (R+G)/2。标签撕掉后露出**离型底纸**，底纸通常偏蓝；
  标签还在时是暖白。
- 先在所有格子的中位蓝偏上做 Otsu 切一刀，得到「这一张纸的底纸色」；
  再用**每格里蓝偏超过阈值像素的占比**（剥掉比例）来判：
  ``>= 0.6`` 已用、``<= 0.05`` 空、中间是「部分撕，拿不准」。
- 另外看灰度标准差：纸面被剪刀切过、撕口翘起、压痕明显时会显著偏高 → 也标成「拿不准」。

只用 Pillow + numpy（和各处一致：没装 numpy 就只给低置信度，不抛异常）。

用法::

    from ulpp.partial_scan import analyze
    verdict = analyze("半张纸.png", grid)
    if verdict.ok:
        used = verdict.used          # 直接写进 SheetRecord.used
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

try:                                  # 统计要算二维分布；没装 numpy 时只给低置信度
    import numpy as np

    _HAS_NUMPY = True
except ImportError:                   # pragma: no cover - 轻量 exe 走这条
    np = None                         # type: ignore[assignment]
    _HAS_NUMPY = False

from PIL import Image

from .templates import GridSpec

# 判据阈值（真实样张上：空 0.00 / 已用 0.99 / 部分撕 0.15，间隔很宽）
USED_FRACTION = 0.60
EMPTY_FRACTION = 0.05
UNSURE_TEXTURE = 3.2                  # 标准差高于「整张纸中位数 + 3.2」算疑似破损
INSET = 0.12                          # 每格四周留 12% 不用：避开格线与纸边
SEARCH_MM = 4.0                       # 相位在期望位置 ±4 mm 内找
MIN_SPREAD = 2.0                      # 各格蓝偏差距小于这个值 → 视为整张都空


@dataclass
class CellVerdict:
    """单格结论。``index`` 是行优先的 0 基序号，可直接写进 ``SheetRecord.used``。"""

    row: int                          # 1 基，便于和界面对话
    col: int
    index: int
    state: str                        # "used" | "empty" | "unsure"
    peeled: float                     # 剥掉比例 0~1
    blueness: float                   # 中位蓝偏（相对值）
    texture: float                    # 灰度标准差
    reason: str = ""                  # 给用户看的一句话（拿不准时用）


@dataclass
class ScanVerdict:
    """一张图的整体结论。"""

    cells: List[List[CellVerdict]] = field(default_factory=list)
    used: List[int] = field(default_factory=list)
    unsure: List[int] = field(default_factory=list)
    confidence: float = 0.0
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.confidence >= 0.5 and not any(w.startswith("fail:") for w in self.warnings)

    @property
    def empty(self) -> List[int]:
        return [c.index for row in self.cells for c in row if c.state == "empty"]


def _fail(reason: str) -> ScanVerdict:
    """量不出来时的统一出口：低置信度 + 一条 ``fail:`` 开头的原因。"""
    return ScanVerdict(confidence=0.0, warnings=["fail: " + reason])


def _grid_ok(grid: GridSpec) -> bool:
    """格阵参数是否可用。"""
    return float(grid.page_w) > 0 and float(grid.page_h) > 0 \
        and int(grid.cols) >= 1 and int(grid.rows) >= 1


def _load_rgb(image_path: str) -> Optional["np.ndarray"]:
    """读成 HxWx3 的 int16 数组；读不了返回 None。"""
    try:
        with Image.open(image_path) as handle:
            return np.asarray(handle.convert("RGB")).astype(np.int16)
    except Exception:                 # 打不开 / 不是图 / 没权限
        return None


def _profile(profile) -> Tuple["np.ndarray", "np.ndarray"]:
    """按行、按列统计"比纸面暗多少"，用来找格线。"""
    bg = float(np.median(profile))
    dark = np.clip(bg - profile, 0.0, None)
    return dark.sum(axis=0), dark.sum(axis=1)


def _fit_shift(values, start_mm: float, pitch_mm: float, count: int,
               px_per_mm: float, limit_px: int) -> int:
    """在所有格线同时打分，找让线压在暗处的最佳偏移（像素）。"""
    best_shift, best_score = 0, -1.0
    for shift in range(-limit_px, limit_px + 1):
        score = 0.0
        for i in range(count + 1):
            pos = int((start_mm + i * pitch_mm) * px_per_mm) + shift
            if 1 <= pos < len(values) - 1:
                score += float(values[pos - 1] + values[pos] + values[pos + 1])
        if score > best_score:
            best_score, best_shift = score, shift
    return best_shift


def _otsu(samples) -> Optional[float]:
    """一维 Otsu；样本分不开时返回 None（表示"这张纸全都是空"）。"""
    v = np.sort(samples.astype(np.float64))
    if v.size < 4 or (v[-1] - v[0]) < MIN_SPREAD:
        return None
    best, thr = -1.0, None
    for i in range(1, v.size):
        score = i * (v.size - i) * (v[:i].mean() - v[i:].mean()) ** 2
        if score > best:
            best, thr = score, float((v[i - 1] + v[i]) / 2.0)
    return thr


def _line_pixels(grid: GridSpec, gray, px_per_mm: float,
                 limit_px: int) -> Optional[Tuple[List[int], List[int]]]:
    """吻合格线相位，返回横竖两条像素坐标（含两边）。"""
    cols, rows = int(grid.cols), int(grid.rows)
    block_w = (cols - 1) * float(grid.pitch_x) + float(grid.cell_w)
    block_h = (rows - 1) * float(grid.pitch_y) + float(grid.cell_h)
    left_mm = float(grid.margin_left) if grid.margin_left is not None else \
        (float(grid.page_w) - block_w) / 2.0
    top_mm = float(grid.margin_top) if grid.margin_top is not None else \
        (float(grid.page_h) - block_h) / 2.0
    col_prof, row_prof = _profile(gray)
    sx = _fit_shift(col_prof, left_mm, float(grid.pitch_x), cols, px_per_mm, limit_px)
    sy = _fit_shift(row_prof, top_mm, float(grid.pitch_y), rows, px_per_mm, limit_px)
    xs = [int((left_mm + i * float(grid.pitch_x)) * px_per_mm) + sx for i in range(cols + 1)]
    ys = [int((top_mm + i * float(grid.pitch_y)) * px_per_mm) + sy for i in range(rows + 1)]
    h, w = gray.shape[:2]
    if xs[-1] <= 0 or ys[-1] <= 0 or xs[0] >= w or ys[0] >= h:
        return None
    return xs, ys


def _cell_patch(arr, xs: Sequence[int], ys: Sequence[int], r: int, c: int):
    """切出一格（四周内缩 12%）。"""
    x0, x1 = int(xs[c]), int(xs[c + 1])
    y0, y1 = int(ys[r]), int(ys[r + 1])
    dx = int((x1 - x0) * INSET)
    dy = int((y1 - y0) * INSET)
    h, w = arr.shape[:2]
    return arr[max(0, y0 + dy):min(h, y1 - dy), max(0, x0 + dx):min(w, x1 - dx)]


def _cell_stats(grid: GridSpec, arr, blue, gray, xs, ys):
    """逐格算中位蓝偏与灰度标准差。"""
    rows, cols = int(grid.rows), int(grid.cols)
    med = np.zeros((rows, cols), dtype=np.float64)
    texture = np.zeros_like(med)
    for r in range(rows):
        for c in range(cols):
            patch_blue = _cell_patch(blue, xs, ys, r, c)
            patch_gray = _cell_patch(gray, xs, ys, r, c)
            if patch_blue.size == 0:
                return None
            med[r, c] = float(np.median(patch_blue))
            texture[r, c] = float(patch_gray.std())
    return med, texture


def _classify(peeled: float, texture: float, texture_limit: float) -> Tuple[str, str]:
    """单格状态：used / empty / unsure，附带一句原因。"""
    if peeled >= USED_FRACTION:
        return "used", ""
    if peeled <= EMPTY_FRACTION and texture <= texture_limit:
        return "empty", ""
    if peeled <= EMPTY_FRACTION:
        return "unsure", "纸面异常（可能有刀痕/撕口），确认一下"
    return "unsure", "只撕掉了一部分（%.0f%%），确认一下再用" % (peeled * 100)


def _build_verdict(grid: GridSpec, blue, med, texture, xs, ys, w: int, h: int,
                   warnings: List[str]) -> ScanVerdict:
    """把逐格统计翻成结论。"""
    rows, cols = int(grid.rows), int(grid.cols)
    thr = _otsu(med.ravel())
    if thr is None:                   # 各格颜色分不开：整张都当空的
        warnings.append("sheet: 各格颜色几乎一致，按「整张都是空的」处理")
        thr = float(med.max()) + 1.0
    texture_limit = float(np.median(texture)) + UNSURE_TEXTURE

    verdict = ScanVerdict(warnings=warnings)
    for r in range(rows):
        line: List[CellVerdict] = []
        for c in range(cols):
            patch_blue = _cell_patch(blue, xs, ys, r, c)
            peeled = float((patch_blue > thr).mean()) if patch_blue.size else 0.0
            tex = float(texture[r, c])
            state, reason = _classify(peeled, tex, texture_limit)
            index = r * cols + c
            if state == "used":
                verdict.used.append(index)
            elif state == "unsure":
                verdict.unsure.append(index)
            line.append(CellVerdict(row=r + 1, col=c + 1, index=index, state=state,
                                    peeled=round(peeled, 3), blueness=round(float(med[r, c]), 1),
                                    texture=round(tex, 2), reason=reason))
        verdict.cells.append(line)

    spread = float(med.max() - np.median(med)) if med.size else 0.0
    conf = 0.55 + min(0.35, spread / 20.0)
    if verdict.used or verdict.unsure:
        conf -= 0.05 * len(verdict.unsure) / max(1, len(verdict.used) + len(verdict.unsure))
    verdict.confidence = round(max(0.0, min(1.0, conf)), 2)
    return verdict


def analyze(image_path: str, grid: GridSpec,
            dpi: Optional[float] = None) -> ScanVerdict:
    """读一张扫描件，逐格判断。量不出来时返回低置信度（不抛异常）。"""
    if not _HAS_NUMPY:
        return _fail("这台机器没装 numpy（pip install numpy 后用）")
    if not _grid_ok(grid):
        return _fail("格阵参数不合法")
    arr = _load_rgb(image_path)
    if arr is None:
        return _fail("读不了这张图")
    h, w = arr.shape[:2]
    if h < 200 or w < 200:
        return _fail("图片太小")

    px_per_mm = (w / float(grid.page_w)) if not dpi else float(dpi) / 25.4
    gray = arr.mean(axis=2).astype(np.float32)
    blue = arr[:, :, 2] - (arr[:, :, 0] + arr[:, :, 1]) / 2.0
    lines = _line_pixels(grid, gray, px_per_mm, max(4, int(SEARCH_MM * px_per_mm)))
    if lines is None:
        return _fail("格阵跑到画面外了，检查纸型或换一张图")
    xs, ys = lines
    stats = _cell_stats(grid, arr, blue, gray, xs, ys)
    if stats is None:
        return _fail("格子太小，图分辨率不够")
    med, texture = stats
    return _build_verdict(grid, blue, med, texture, xs, ys, w, h, [])


def describe(verdict: ScanVerdict) -> str:
    """给日志用的一行摘要。"""
    return "扫出来：已用 %d 格，拿不准 %d 格，空 %d 格（置信度 %.2f）" % (
        len(verdict.used), len(verdict.unsure), len(verdict.empty), verdict.confidence)

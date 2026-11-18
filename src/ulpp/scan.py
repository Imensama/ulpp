# -*- coding: utf-8 -*-
"""扫描标定：从一张扫描图/PDF 里量出胶纸的格阵（节距、首条线位置、歪斜）。

只用 Pillow + pypdf（和主程序现有依赖一致，不引 numpy）：
- 去光照不均：大核模糊做背景，相减得到"暗度"图；
- 投影 + **折叠拟合**求节距与相位：把投影按候选节距折叠，等距线阵得分最高，
  缺线/双线/圆角都被其它线摊平，比逐个找峰稳得多（ADF 瓢、平板切边都不靠纸边）；
- 由页面宽高反推行列数，用残差与线数算一个置信度；
- 量不准时给 warnings（太淡、线太少、残差大），界面据此提示重扫。

用法：
    from ulpp.scan import measure_file
    m = measure_file("扫描.pdf")
    m.pitch_x_mm, m.cols, m.confidence ...
命令行自检：
    python -m ulpp.scan 扫描.pdf
"""
from __future__ import annotations

from .i18n import tr

import statistics
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageFilter

A4_W_MM, A4_H_MM = 210.0, 297.0
DEFAULT_DPI = 300
MIN_RATIO = 0.35          # 线数 / 期望线数 低于这个就算"没量到"
MAX_RESIDUAL_MM = 0.35    # 折叠后单条线偏离拟合网格的上限


@dataclass(frozen=True)
class Measurement:
    """一次扫描量出来的东西。单位 mm，坐标原点在页面左上角。"""

    page_w_mm: float
    page_h_mm: float
    mm_per_px: float
    pitch_x_mm: float
    pitch_y_mm: float
    first_x_mm: float          # 第一条竖线中心
    first_y_mm: float          # 第一条横线中心
    cols: int
    rows: int
    cell_w_mm: float           # 节距 - 缝宽（估算）
    cell_h_mm: float
    rotation_deg: float
    confidence: float
    dpi: float
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return self.confidence >= 0.5 and not any(w.startswith("fail:") for w in self.warnings)


# ---------------------------------------------------------------- 读图
def _load(path: str) -> Tuple[Image.Image, float, float, float, List[str]]:
    """返回 (灰度图, 页宽 mm, 页高 mm, dpi, warnings)。"""
    warnings: List[str] = []
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        page = reader.pages[0]
        box = page.mediabox
        page_w = float(box.width) * 25.4 / 72.0
        page_h = float(box.height) * 25.4 / 72.0
        images = list(page.images)
        if not images:
            raise ValueError(tr("scan.err.pdf_no_image"))
        img = images[0].image.convert("L")
        dpi = img.width / (page_w / 25.4)
        return img, page_w, page_h, dpi, warnings

    img = Image.open(path).convert("L")
    dpi_info = img.info.get("dpi")
    if dpi_info:
        dx = float(dpi_info[0])
        dpi = dx if dx > 1 else DEFAULT_DPI
    else:
        dpi = DEFAULT_DPI
        warnings.append("no-dpi: 图里没有分辨率信息，按 %d dpi 处理（绝对尺寸可能偏）" % dpi)
    page_w = img.width / dpi * 25.4
    page_h = img.height / dpi * 25.4
    return img, page_w, page_h, dpi, warnings


def _darkness(img: Image.Image) -> Image.Image:
    """去光照不均：背景（大核模糊）减原图 → 越黑的线数值越大。"""
    radius = max(8, int(round(min(img.size) / 24)))
    bg = img.filter(ImageFilter.GaussianBlur(radius))
    return ImageChops.subtract(bg, img)


def _profiles(dark: Image.Image) -> Tuple[List[float], List[float]]:
    w, h = dark.size
    col = dark.resize((w, 1), Image.BOX).tobytes()
    row = dark.resize((1, h), Image.BOX).tobytes()
    return [float(v) for v in col], [float(v) for v in row]


def _smooth(values: Sequence[float], window: int = 5) -> List[float]:
    half = max(1, window // 2)
    out = []
    n = len(values)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _sharpness(profile: Sequence[float]) -> float:
    """投影"尖锐度"：线越清楚，峰值相对均值越高。"""
    mean = sum(profile) / len(profile)
    if mean <= 1e-9:
        return 0.0
    return max(profile) / mean


def _estimate_skew(dark: Image.Image, limit: float = 1.5, step: float = 0.25) -> float:
    """ADF 会瓢：找让行/列投影最尖的旋转角（粗搜 0.25°）。"""
    best_angle, best_score = 0.0, -1.0
    n = int(round(limit / step))
    for k in range(-n, n + 1):
        angle = k * step
        rotated = dark.rotate(angle, resample=Image.BILINEAR, expand=False) if angle else dark
        col, row = _profiles(rotated)
        score = _sharpness(_smooth(col)) + _sharpness(_smooth(row))
        if score > best_score:
            best_angle, best_score = angle, score
    return best_angle


def _period_autocorr(profile: Sequence[float], pmin: float, pmax: float) -> Optional[float]:
    """自相关找基频：取"相关度接近最大值里最小的那个周期"，避免锁到二次谐波。"""
    prof = _smooth(profile, 3)
    n = len(prof)
    mean = sum(prof) / n
    centred = [v - mean for v in prof]
    energy = sum(v * v for v in centred)
    if energy <= 1e-9:
        return None
    lo = max(2, int(pmin))
    hi = min(n - 2, int(pmax))
    if hi <= lo:
        return None
    scores = {}
    for lag in range(lo, hi + 1):
        s = 0.0
        for i in range(n - lag):
            s += centred[i] * centred[i + lag]
        scores[lag] = s / energy
    best = max(scores.values())
    for lag in sorted(scores):
        if scores[lag] >= best * 0.97:      # 最小周期优先，且拉到 ±0.5px 再细化
            return float(lag)
    return None



def _fold_profile(profile: Sequence[float], period: float) -> Tuple[List[float], int]:
    """按候选节距把投影折叠成一个周期：所有线叠在一起，信噪比高得多。"""
    prof = _smooth(profile, 3)
    bins = max(16, int(round(period * 8)))
    acc = [0.0] * bins
    for x, v in enumerate(prof):
        idx = int((x % period) / period * bins) % bins
        acc[idx] += v
    # 圆周平滑，避免峰值被切在边界
    sm = [(acc[(i - 1) % bins] + 2 * acc[i] + acc[(i + 1) % bins]) / 4.0 for i in range(bins)]
    return sm, bins


def _lattice_fit(profile: Sequence[float], coarse_period: float):
    """由粗节距精修出 (节距, 相位, 各线中心, 残差)。

    相位用折叠后的峰（相当于把所有线叠一起求平均），比逐条线稳；
    节距用逐条线的质心做最小二乘，窗口贴到图像边缘的那些线直接跳过（纸边会把质心带偏）。
    """
    if coarse_period <= 2 or len(profile) < coarse_period * 1.5:
        return None
    prof = _smooth(profile, 3)
    n = len(prof)
    period = float(coarse_period)

    folded, bins = _fold_profile(prof, period)
    k = max(range(bins), key=lambda i: folded[i])
    left, right = folded[(k - 1) % bins], folded[(k + 1) % bins]
    denom = left + right + folded[k]
    frac = 0.5 * (left - right) / denom if denom > 1e-9 else 0.0
    phase = ((k + frac) % bins) * period / bins

    peak_max = max(prof) if prof else 0.0
    win = 0.22 * period
    centres, idxs = [], []
    kmin = int((0 - phase) // period) - 1
    kmax = int((n - phase) // period) + 1
    for kk in range(kmin, kmax + 1):
        pos = phase + kk * period
        lo, hi = int(round(pos - win)), int(round(pos + win))
        if lo <= 1 or hi >= n - 2:          # 贴边的不参与（纸边/裁切边会污染）
            continue
        seg = prof[lo:hi + 1]
        if max(seg) < 0.25 * peak_max:
            continue
        w = sum(seg)
        if w <= 1e-9:
            continue
        centres.append(sum((lo + i) * v for i, v in enumerate(seg)) / w)
        idxs.append(kk)
    if len(centres) >= 2:
        kk_mean = sum(idxs) / len(idxs)
        c_mean = sum(centres) / len(centres)
        denom2 = sum((kk - kk_mean) ** 2 for kk in idxs)
        if denom2 > 1e-9:
            a = sum((kk - kk_mean) * (c - c_mean) for kk, c in zip(idxs, centres)) / denom2
            if 0.5 * period < a < 1.5 * period:
                period = a
                phase = (c_mean - a * kk_mean) % a
    predicted = [phase + kk * period for kk in idxs]
    residuals = [c - p for c, p in zip(centres, predicted)]
    return {"period": period, "phase": phase % period, "centres": centres,
            "idxs": idxs, "residuals": residuals, "count": len(centres)}


def _fold_fit(profile: Sequence[float], pmin: float, pmax: float,
              coarse: float = 0.25, fine: float = 0.02) -> Optional[dict]:
    """在 pmin..pmax 里找"最像等距线阵"的节距/相位（像素单位）。"""
    prof = _smooth(profile)
    n = len(prof)
    if n < 32:
        return None

    def score(period: float, phase: float) -> Tuple[float, int]:
        total, k = 0.0, 0
        pos = phase
        while pos < n - 1:
            i = int(pos)
            frac = pos - i
            total += prof[i] * (1 - frac) + prof[i + 1] * frac
            k += 1
            pos += period
        return (total / k if k else 0.0), k

    best = None
    period = pmin
    while period <= pmax:
        phase = 0.0
        while phase < period:
            value, count = score(period, phase)
            if count >= 3 and (best is None or value > best[0]):
                best = (value, period, phase)
            phase += period / 12.0
        period += coarse
    if best is None:
        return None
    _, period, phase = best

    # 细搜：节距 ±0.6px、相位 ±period/12
    fine_best = best
    step_p = fine
    p = period - 0.6
    while p <= period + 0.6:
        ph = max(0.0, phase - period / 12.0)
        while ph <= phase + period / 12.0:
            value, count = score(p, ph)
            if count >= 3 and value > fine_best[0]:
                fine_best = (value, p, ph)
            ph += 0.1
        p += step_p
    _, period, phase = fine_best

    centres, residuals = [], []
    pos = phase
    while pos < n - 1:
        lo, hi = int(max(0, pos - 4)), int(min(n - 1, pos + 4))
        seg = prof[lo:hi + 1]
        weight = sum(seg)
        centre = (sum((lo + i) * v for i, v in enumerate(seg)) / weight) if weight > 1e-9 else pos
        centres.append(centre)
        residuals.append(centre - pos)
        pos += period
    return {"period": period, "phase": phase, "centres": centres,
            "residuals": residuals, "count": len(centres)}


# ---------------------------------------------------------------- 主流程
def _band_width_mm(profile: Sequence[float], centres: Sequence[float],
                   mm_per_px: float, lo: float, hi: float) -> Optional[float]:
    """量暗带的半高宽（≈相邻标签之间的切割缝宽），换算成 mm 并夹进 lo..hi。"""
    if not centres:
        return None
    widths = []
    n = len(profile)
    for centre in centres:
        c = int(round(centre))
        if not (0 <= c < n):
            continue
        peak = profile[c]
        if peak <= 1e-9:
            continue
        half = peak * 0.5
        left = c
        while left > 0 and profile[left] > half:
            left -= 1
        right = c
        while right < n - 1 and profile[right] > half:
            right += 1
        widths.append(right - left)
    if not widths:
        return None
    return max(lo, min(hi, statistics.median(widths) * mm_per_px))


def measure_file(path: str, expect_cols: Optional[int] = None,
                 expect_rows: Optional[int] = None) -> Measurement:
    """量一张扫描件 / 校正过的照片。行列数优先用预设（`expect_*`），没给就按满版推。"""
    img, page_w, page_h, dpi, warnings = _load(path)
    return measure_image(img, page_w, page_h, dpi, warnings, expect_cols, expect_rows)


def measure_image(img: Image.Image, page_w_mm: float, page_h_mm: float, dpi: float,
                  warnings: Optional[Sequence[str]] = None,
                  expect_cols: Optional[int] = None,
                  expect_rows: Optional[int] = None) -> Measurement:
    """从一张"已经被拉成正视 A4"的图里量格阵（照片校正后也走这里）。"""
    warnings = list(warnings or [])
    page_w, page_h = page_w_mm, page_h_mm
    mm_per_px = page_w / img.width
    dark = _darkness(img)
    angle = _estimate_skew(dark)
    if abs(angle) >= 0.25:
        dark = dark.rotate(angle, resample=Image.BILINEAR, expand=False)

    # 扫描件的边框（纸边/整页框）会被当成一条线，先裁掉 2% 再找格阵
    w, h = dark.size
    pad_x, pad_y = int(w * 0.02), int(h * 0.02)
    if w - 2 * pad_x > 32 and h - 2 * pad_y > 32:
        dark = dark.crop((pad_x, pad_y, w - pad_x, h - pad_y))
    else:
        pad_x = pad_y = 0
    col_prof, row_prof = _profiles(dark)

    # 先用自相关定基频（避开二次谐波），再在它附近折叠细化。
    # 知道行列数时把候选范围收窄到"纸宽/列数"附近，避免锁到半格/双线这类谐波上。
    if expect_cols:
        centre_x = page_w / float(expect_cols)
        pmin_x, pmax_x = 0.7 * centre_x, 1.3 * centre_x
    else:
        pmin_x, pmax_x = 8.0, 60.0
    if expect_rows:
        centre_y = page_h / float(expect_rows)
        pmin_y, pmax_y = 0.7 * centre_y, 1.3 * centre_y
    else:
        pmin_y, pmax_y = 8.0, 60.0
    base_x = _period_autocorr(col_prof, pmin_x / mm_per_px, pmax_x / mm_per_px)
    base_y = _period_autocorr(row_prof, pmin_y / mm_per_px, pmax_y / mm_per_px)
    if base_x is None or base_y is None:
        raise ValueError(tr("scan.err.no_lattice"))
    col = _lattice_fit(col_prof, base_x)
    row = _lattice_fit(row_prof, base_y)
    if not col or not row:
        raise ValueError(tr("scan.err.fold_failed"))

    pitch_x = col["period"] * mm_per_px
    pitch_y = row["period"] * mm_per_px
    cols = int(expect_cols) if expect_cols else max(1, int(round(page_w / pitch_x)))
    rows = int(expect_rows) if expect_rows else max(1, int(round(page_h / pitch_y)))
    if expect_cols:
        span = (len(col["centres"]) - 1) * pitch_x
        if abs(span - (cols - 1) * pitch_x) > pitch_x * 1.5:
            warnings.append("count-x: 只量到 %d 条竖线，和预设 %d 列对不上" % (len(col["centres"]), cols))
    resid_x = max(abs(r) for r in col["residuals"]) * mm_per_px
    resid_y = max(abs(r) for r in row["residuals"]) * mm_per_px

    tol = max(MAX_RESIDUAL_MM, 2.0 * mm_per_px)   # 100dpi 一个像素就 0.25mm，容差跟着像素走
    if resid_x > tol or resid_y > tol:
        warnings.append("resid: 拟合残差 %.2f/%.2f mm，可能有褶皱或缺线" % (resid_x, resid_y))
    if len(col["centres"]) < max(2, cols - 1):
        warnings.append("few-cols: 只找到 %d 条竖线（预期约 %d 条）" % (len(col["centres"]), cols + 1))
    if len(row["centres"]) < max(2, rows - 1):
        warnings.append("few-rows: 只找到 %d 条横线（预期约 %d 条）" % (len(row["centres"]), rows + 1))
    if page_w > A4_W_MM + 5 or page_h > A4_H_MM + 5:
        warnings.append("size: 页面 %.0f×%.0f mm 不像 A4，确认是不是整页扫描" % (page_w, page_h))

    # 贴边的线会被主动跳过，所以按"内部线数"算应有条数，别把跳过当成没找到
    expected = max(1, (max(1, cols - 1)) + (max(1, rows - 1)))
    found = min(1.0, (len(col["centres"]) + len(row["centres"])) / float(expected))
    conf = max(0.0, min(1.0, 0.55 * found + 0.45 * (1.0 - min(1.0, max(resid_x, resid_y) / tol))))
    if found < MIN_RATIO:
        warnings.append("fail: 找到的线太少，扫得太淡或不是这张纸")

    # 缝宽：量暗带的半高宽（相邻两格的切割缝就是这条暗带），夹在 0.3~5mm
    seam_x = _band_width_mm(_smooth(col_prof), col["centres"], mm_per_px, 0.3, 5.0)
    seam_y = _band_width_mm(_smooth(row_prof), row["centres"], mm_per_px, 0.3, 5.0)
    if seam_x is None or seam_y is None:
        seam_x = seam_x or 2.0
        seam_y = seam_y or 2.0
        warnings.append("seam: 缝宽没量准，格尺寸按 2 mm 缝估算")
    return Measurement(
        page_w_mm=page_w, page_h_mm=page_h, mm_per_px=mm_per_px,
        pitch_x_mm=round(pitch_x, 3), pitch_y_mm=round(pitch_y, 3),
        # 相位：把第一条线折进 [0, 节距) —— 左/上边被裁掉时也对得上纸边
        first_x_mm=round(((col["centres"][0] + pad_x) * mm_per_px) % pitch_x, 2),
        first_y_mm=round(((row["centres"][0] + pad_y) * mm_per_px) % pitch_y, 2),
        cols=cols, rows=rows,
        cell_w_mm=round(pitch_x - seam_x, 2), cell_h_mm=round(pitch_y - seam_y, 2),
        rotation_deg=round(angle, 2), confidence=round(conf, 2), dpi=round(dpi, 1),
        warnings=tuple(warnings),
    )



def describe(m: Measurement) -> str:
    lines = [
        "页面 %.1f × %.1f mm @ %.0f dpi（%.3f mm/px）" % (m.page_w_mm, m.page_h_mm, m.dpi, m.mm_per_px),
        "格阵 %d 列 × %d 行 · 节距 %.2f × %.2f mm" % (m.cols, m.rows, m.pitch_x_mm, m.pitch_y_mm),
        "首线 %.2f / %.2f mm · 格 %.2f × %.2f mm · 歪斜 %.2f°" % (
            m.first_x_mm, m.first_y_mm, m.cell_w_mm, m.cell_h_mm, m.rotation_deg),
        "置信度 %.2f" % m.confidence,
    ]
    lines += ["  ! " + w for w in m.warnings]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法: python -m ulpp.scan <扫描.pdf|png|jpg> [...]")
        return 2
    code = 0
    for path in args:
        try:
            m = measure_file(path)
        except Exception as exc:
            print("%s: 量不了 —— %s" % (path, exc))
            code = 1
            continue
        print("%s\n%s\n" % (path, describe(m)))
        if not m.ok:
            code = 1
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

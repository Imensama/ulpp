# -*- coding: utf-8 -*-
"""格线拉直（plumb-line dewarp）：胶纸翘起来时，切割线在照片里是弯的。

思路（不需要用户多做任何事）：
1. 在"已经按 A4 拉正"的图上，用现有格阵拟合拿到列/行的大致位置；
2. 沿每条线在多个高度带里找它实际的位置（局部最暗的列/行）；
3. 把"实际位置 - 应有位置"当成一个平滑残差场（低阶二维多项式）拟合；
4. 用这个残差场把图反向扭正，再迭代一次。

它对**翘曲**有效（翘曲是低频、平滑的形变），对褶皱/气泡这种高频形变效果有限。
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageFilter

BANDS = 12            # 每条线沿方向切几段采样
SEARCH = 0.22         # 在期望位置附近 ±22% 节距内找线
FEATURES = 6          # 多项式项数：1, x, y, xy, x², y²


def _darkness(img: Image.Image) -> np.ndarray:
    bg = img.filter(ImageFilter.GaussianBlur(max(8, int(min(img.size) / 24))))
    return np.clip(np.asarray(bg, dtype=np.float32) - np.asarray(img, dtype=np.float32), 0, None)


def _lattice(profile: np.ndarray, lo: float, hi: float) -> Tuple[float, float]:
    """粗拟合：返回 (节距, 相位)，用折叠法（跟 scan.py 里的思路一致但更简单）。"""
    prof = profile.astype(np.float64)
    prof = prof - prof.mean()
    n = len(prof)
    best = (float("inf"), lo)
    for period in np.arange(lo, hi, max(0.25, (hi - lo) / 400.0)):
        for phase in np.arange(0, period, period / 10.0):
            pos = np.arange(phase, n - 1, period)
            idx = pos.astype(int)
            score = prof[idx].mean() if len(idx) >= 3 else -1e9
            if -score < best[0]:          # 线是暗的，prof 已经取反（暗为正）
                best = (-score, period)
    return best[1], 0.0


def _fold(profile: np.ndarray, period: float) -> Tuple[float, float]:
    """折叠求相位：把所有线叠起来找峰（亚像素）。"""
    prof = profile.astype(np.float64)
    prof = prof - prof.mean()
    n = len(prof)
    bins = max(16, int(round(period * 8)))
    acc = np.zeros(bins)
    xs = np.arange(n)
    idx = ((xs % period) / period * bins).astype(int) % bins
    np.add.at(acc, idx, prof)
    sm = np.convolve(np.r_[acc[-1], acc, acc[0]], [0.25, 0.5, 0.25], mode="valid")
    k = int(np.argmax(sm))
    left, right = sm[(k - 1) % bins], sm[(k + 1) % bins]
    denom = left + right + sm[k]
    frac = 0.5 * (left - right) / denom if denom > 1e-9 else 0.0
    return (k + frac) * period / bins, float(sm[k])


def _sample_lines_at(dark: np.ndarray, expected: Sequence[float], axis: int,
                     half: float, bands: int = BANDS) -> np.ndarray:
    """给定期望位置，沿方向分带找每条线的实际位置 → (跨向坐标, 沿向坐标, 残差)。"""
    if axis == 0:
        band_prof = dark                 # 竖线：列是"跨向"，行是"沿向"
        n_along, n_cross = dark.shape[0], dark.shape[1]
    else:
        band_prof = dark.T
        n_along, n_cross = dark.shape[1], dark.shape[0]

    xs, ys, rs = [], [], []
    for pos in expected:
        lo, hi = int(round(pos - half)), int(round(pos + half))
        if lo < 1 or hi >= n_cross - 1:
            continue
        for b in range(bands):
            b0 = int(b * n_along / bands)
            b1 = int((b + 1) * n_along / bands)
            if b1 - b0 < 3:
                continue
            seg = band_prof[b0:b1, lo:hi].mean(axis=0)
            seg = np.clip(seg - seg.min(), 0, None)
            total = seg.sum()
            if total <= 1e-6:
                continue
            centre = lo + float((np.arange(len(seg)) * seg).sum() / total)
            if abs(centre - pos) > half:
                continue
            xs.append(centre)
            ys.append(0.5 * (b0 + b1))
            rs.append(centre - pos)
    if not xs:
        return np.empty((0, 3))
    return np.column_stack([np.array(xs), np.array(ys), np.array(rs)])


def refine_grid(img: Image.Image, expected_x: Sequence[float], expected_y: Sequence[float],
                iterations: int = 2, half_ratio: float = 0.22,
                period_hint: float = 0.0) -> Tuple[Image.Image, dict]:
    """按格线把图拉直。expected_* 是每条线当前（未拉直前）的像素位置。"""
    stats = {"before": [], "after": []}
    current = img
    cur_x = list(expected_x)
    cur_y = list(expected_y)
    period = period_hint or (np.median(np.diff(cur_x)) if len(cur_x) > 1 else 40.0)
    half = half_ratio * period
    for _ in range(iterations):
        dark = _darkness(current)
        sx = _sample_lines_at(dark, cur_x, 0, half)
        sy = _sample_lines_at(dark, cur_y, 1, half)
        if len(sx) < 20 and len(sy) < 20:
            break
        stats["before"].append(round(float(np.abs(sx[:, 2]).mean()) if len(sx) else 0.0, 2))
        coef_x = _fit_field(sx, dark.shape, 0) if len(sx) >= 20 else None
        coef_y = _fit_field(sy, dark.shape, 1) if len(sy) >= 20 else None
        if coef_x is None and coef_y is None:
            break
        current = _apply_field(current, coef_x, coef_y)
        dark2 = _darkness(current)
        sx2 = _sample_lines_at(dark2, cur_x, 0, half)
        sy2 = _sample_lines_at(dark2, cur_y, 1, half)
        vals = [float(np.abs(a[:, 2]).mean()) for a in (sx2, sy2) if len(a)]
        stats["after"].append(round(sum(vals) / len(vals), 2) if vals else 0.0)
    return current, stats


def _fit_field(samples: np.ndarray, shape, axis: int):
    """把残差拟合成一个低阶二维多项式，返回可在整幅图上求值的系数。"""
    h, w = shape
    if len(samples) < 20:
        return None
    x = samples[:, 0] / w
    y = samples[:, 1] / h
    A = np.column_stack([np.ones_like(x), x, y, x * y, x * x, y * y])
    r = samples[:, 2]
    coef, *_ = np.linalg.lstsq(A, r, rcond=None)
    return coef


def _apply_field(img: Image.Image, coef_x, coef_y) -> Image.Image:
    """按残差场扭正（x' = x - dx(x,y)；行同理）。"""
    src = np.asarray(img, dtype=np.float32)
    h, w = src.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = xs / w, ys / h

    def field(coef):
        return (coef[0] + coef[1] * nx + coef[2] * ny + coef[3] * nx * ny
                + coef[4] * nx * nx + coef[5] * ny * ny)

    dx = field(coef_x) if coef_x is not None else 0.0
    dy = field(coef_y) if coef_y is not None else 0.0
    # 残差 r = 实际 - 期望；把内容整体挪 r 才能落回期望位置
    map_x = np.clip(xs - dx, 0, w - 1).astype(np.float32)
    map_y = np.clip(ys - dy, 0, h - 1).astype(np.float32)
    # 双线性重采样
    x0 = np.floor(map_x).astype(int)
    y0 = np.floor(map_y).astype(int)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    fx = map_x - x0
    fy = map_y - y0
    out = (src[y0, x0] * (1 - fx) * (1 - fy) + src[y0, x1] * fx * (1 - fy)
           + src[y1, x0] * (1 - fx) * fy + src[y1, x1] * fx * fy)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

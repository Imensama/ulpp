# -*- coding: utf-8 -*-
"""v2 外壳的显示尺度：DPI 感知、按 ``tk scaling`` 缩放、字体与配色。

v1 的界面"糊"不是 Tk 的锅：exe 默认不声明 DPI 感知，Windows 在 175% 下把整个窗口
当位图放大 1.75 倍。v2 外壳从第一行起就按 ``z`` 设计 —— 像素过 ``Metrics.s()``，
字号给磅值由 Tk 自己跟 DPI 走，素材按 ``z >= 1.4`` 选 980px 版。
"""
from __future__ import annotations

import os
from tkinter import font as tkfont
from typing import Optional, Tuple

BASE_SCALING = 1.3345          # 与 wizard.py 同一套设计稿基准
DESIGN_W, DESIGN_H = 1100, 720  # 设计稿窗口大小（未缩放）

LIGHT = dict(
    name="light", bg="#F3F5F9", card="#FFFFFF", border="#E2E8F0", text="#1F2937",
    muted="#5B6574", accent="#2563EB", accent_text="#FFFFFF", soft="#EFF6FF",
    soft_text="#1E3A8A", chip="#E8EEF7", dot_off="#D3DBE6", dot_done="#9DB7E8",
    green="#16A34A",
)
MONO = dict(
    name="mono", bg="#FFFFFF", card="#FFFFFF", border="#111111", text="#000000",
    muted="#444444", accent="#000000", accent_text="#FFFFFF", soft="#F1F1F1",
    soft_text="#000000", chip="#E9E9E9", dot_off="#CCCCCC", dot_done="#666666",
    green="#000000",
)
# 暖色版：橘红只做"强调色"（按钮/进度点），大面积仍是中性浅灰，避免刺眼
WARM = dict(LIGHT)
WARM.update(
    name="warm", accent="#C2410C", accent_text="#FFFFFF",
    soft="#FFF1E6", soft_text="#9A3412", dot_done="#FDBA8C",
    green="#15803D",
)
# 铜色（Wilier ramato 那种偏棕的橘）：更沉、更不刺
COPPER = dict(LIGHT)
COPPER.update(
    name="copper", accent="#A9532B", accent_text="#FFFFFF",
    soft="#FBF0E7", soft_text="#7C3A1D", dot_done="#E3B79A",
)
# Vista/Aero 味：浅蓝底 + 白卡 + 冷冷的蓝强调色
VISTA = dict(LIGHT)
VISTA.update(
    name="vista", bg="#EAF2FB", card="#FFFFFF", text="#16202B", muted="#5B6B80",
    border="#B9C7D9", accent="#1F6FB2", accent_text="#FFFFFF",
    soft="#DCEEFF", soft_text="#0B4F8A", dot_done="#7FC4FF", chip="#F3F8FE",
)
# 好莱坞橙青（浅色版）：青灰底 + 一点橙做强调，暗部带青
TEAL = dict(LIGHT)
TEAL.update(
    name="teal", bg="#F1F6F5", card="#FFFFFF", text="#123035", muted="#5D7B82",
    border="#C7D8D6", accent="#E4572E", accent_text="#FFFFFF",
    soft="#FDEBE4", soft_text="#9A3412", dot_done="#F7B267", chip="#F7FBFA",
    accent2="#FF9A62",
)
# GMK Aero 风味：官方说"用 5 个 GMK 标准色复刻 Vista Aero"——浅青 TU2 / 深青 TU1 /
# 白 CP / 亮黄 N6 / 灰 2B。直接用原色做小字按钮会花，所以主按钮压深一档保对比度。
AERO = dict(LIGHT)
AERO.update(
    name="aero", bg="#F8FCFD", card="#FFFFFF", text="#123A40", muted="#6A868B",
    border="#D7EAEB", accent="#14A6AB", accent_text="#FFFFFF",
    soft="#E8F6F7", soft_text="#0A5C64", dot_done="#6FD6DA", chip="#FBFEFE",
    green="#2E7D6B", accent2="#6FD6DA",
)
AERO_CHIPS = {"CP 白": "#F5F5F5", "TU2 浅青": "#00A4A9", "TU1 深青": "#00627A",
              "N6 亮黄": "#E5A100", "2B 灰": "#858A8D"}
THEMES = {"light": LIGHT, "mono": MONO, "warm": WARM, "copper": COPPER,
          "vista": VISTA, "teal": TEAL, "aero": AERO}


def enable_dpi_awareness() -> str:
    """声明进程 DPI 感知；返回做了什么（写日志 / 测试断言用，不抛异常）。"""
    if os.name != "nt":
        return "skipped:not-windows"
    try:
        import ctypes

        hr = int(ctypes.windll.shcore.SetProcessDpiAwareness(1))  # SYSTEM_DPI_AWARE
        return "shcore:ok" if hr == 0 else f"shcore:hr={hr}"
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
        return "user32:ok"
    except Exception as exc:  # pragma: no cover - 老系统 / 非 Windows
        return f"failed:{type(exc).__name__}"


class Metrics:
    """把设计稿像素换成当前屏幕像素，并提供统一的字体/配色入口。"""

    def __init__(self, root, theme: str = "light") -> None:
        self.root = root
        self.z = max(1.0, round(float(root.tk.call("tk", "scaling")) / BASE_SCALING, 3))
        self.img_px = 980 if self.z >= 1.4 else 560
        try:
            families = set(tkfont.families(root))
        except Exception:  # pragma: no cover - 极少数无字体服务的环境
            families = set()
        # 中文字体按平台挑：Windows 雅黑 / macOS 苹方 / Linux Noto
        for candidate in ("Microsoft YaHei UI", "PingFang SC", "Hiragino Sans GB",
                          "Noto Sans CJK SC", "Segoe UI", "DejaVu Sans"):
            if candidate in families:
                self.family = candidate
                break
        else:
            self.family = "TkDefaultFont"
        self.theme = LIGHT if theme not in THEMES else THEMES[theme]

    def s(self, px: float) -> int:
        """设计稿像素 → 屏幕像素。"""
        return int(round(px * self.z))

    def font(self, size: float, bold: bool = False) -> Tuple[str, int, str]:
        size = max(8, int(round(size)))
        return (self.family, size, "bold") if bold else (self.family, size)

    def screen(self) -> Tuple[int, int]:
        return int(self.root.winfo_screenwidth()), int(self.root.winfo_screenheight())

    def window_size(self) -> Tuple[int, int]:
        """按设计稿算窗口大小，但绝不超出屏幕（175% 下设计稿会比屏幕高）。"""
        sw, sh = self.screen()
        w = min(self.s(DESIGN_W), max(self.s(760), sw - self.s(60)))
        h = min(self.s(DESIGN_H), max(self.s(520), sh - self.s(100)))
        return w, h

    def palette(self, key: str, fallback: Optional[str] = None) -> str:
        return self.theme.get(key, fallback or "#000000")

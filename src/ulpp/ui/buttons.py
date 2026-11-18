# -*- coding: utf-8 -*-
"""全应用唯一的按钮入口：固定语义样式，调用方只能选 ``button_type``。

设计见 ``docs/design/button-system.md``。要点：

- 五种类型：submit / cancel / warning / danger / info；
- 颜色、字号、内边距、悬停/禁用态都在本文件内决定，调用方传不进来；
- 支持三档尺寸 sm/md/lg，像素走传入的 ``scale``（v2 是 Metrics.s，v1 是默认缩放）；
- 除 ``buttons.py`` 外，源码里不允许直接构造 ``tk.Button``/``ttk.Button``
  （由 ``tests/test_constraints.py`` 静态扫描兜底）。
"""
from __future__ import annotations

import tkinter as tk
from enum import Enum
from typing import Callable, Dict, Optional

from .scale import LIGHT

FONT_FAMILY = "TkDefaultFont"


class ButtonType(str, Enum):
    SUBMIT = "submit"      # 主操作：保存 / 生成 / 下一步 / 打开
    CANCEL = "cancel"      # 取消 / 返回 / 关闭
    WARNING = "warning"    # 需要留意的不可逆操作：覆盖、清空
    DANGER = "danger"      # 破坏性：删除纸张、抹掉配置
    INFO = "info"          # 说明性 / 帮助 / 查看


# 每个类型固定的视觉规则：背景、文字、悬停背景、边框；None = 无边框
_STYLES: Dict[ButtonType, Dict[str, Optional[str]]] = {
    ButtonType.SUBMIT: {"bg_key": "accent", "fg_key": "accent_text",
                        "hover_key": "soft_text", "border_key": None,
                        "bg": "#2563EB", "fg": "#FFFFFF", "hover": "#1E3A8A"},
    ButtonType.CANCEL: {"bg_key": "card", "fg_key": "text",
                        "hover_key": "chip", "border_key": "border",
                        "bg": "#FFFFFF", "fg": "#1F2937", "hover": "#E8EEF7"},
    ButtonType.WARNING: {"bg": "#B45309", "fg": "#FFFFFF", "hover": "#92400E",
                         "bg_key": None, "fg_key": None, "hover_key": None,
                         "border_key": None},
    ButtonType.DANGER: {"bg": "#B91C1C", "fg": "#FFFFFF", "hover": "#991B1B",
                        "bg_key": None, "fg_key": None, "hover_key": None,
                        "border_key": None},
    ButtonType.INFO: {"bg_key": "soft", "fg_key": "soft_text",
                      "hover_key": "chip", "border_key": None,
                      "bg": "#EFF6FF", "fg": "#1E3A8A", "hover": "#E8EEF7"},
}

# size -> (font pt, padx 设计稿 px, pady 设计稿 px, 最小高度 px, bold)
_SIZES = {
    "sm": (10, 10, 5, 28, False),
    "md": (11, 16, 9, 36, False),
    "lg": (13, 24, 13, 48, True),
}


def _default_scale(widget) -> float:
    """没有传 scale 时按 Tk 的 scaling 粗略缩放；最小 1.0。"""
    try:
        scaling = float(widget.tk.call("tk", "scaling"))
    except Exception:                     # pragma: no cover - 极端环境
        scaling = 1.0
    return max(1.0, round(scaling / 1.3345, 3))


def _default_font(size: int, bold: bool = False):
    return (FONT_FAMILY, size, "bold") if bold else (FONT_FAMILY, size)


class AppButton(tk.Button):
    """固定样式的按钮。只允许 ``button_type`` 选语义，样式参数一律拒绝。"""

    _ALLOWED = {"text", "command", "button_type", "palette", "font",
                "scale", "size", "state", "width", "wraplength"}

    def __init__(self, master, text: str, command: Optional[Callable] = None,
                 *, button_type, palette: Optional[dict] = None,
                 font: Optional[Callable] = None,
                 scale: Optional[Callable] = None, size: str = "md",
                 state: str = "normal", width: Optional[int] = None,
                 wraplength: Optional[int] = None,
                 **kwargs) -> None:
        if kwargs:
            raise TypeError(
                "AppButton 不接受样式参数：%s（样式只能由 button_type 决定）"
                % ", ".join(sorted(kwargs)))
        try:
            kind = ButtonType(button_type)
        except ValueError as exc:
            raise ValueError(
                "button_type 只能是 %s，收到 %r"
                % ("/".join(t.value for t in ButtonType), button_type)) from exc
        if size not in _SIZES:
            raise ValueError("size 只能是 sm/md/lg，收到 %r" % (size,))

        P = palette or LIGHT
        self._font = font or _default_font
        self._scale = scale or (lambda px: int(round(px * _default_scale(master))))
        self._size = size
        self._kind = kind
        self._palette = P
        self._style = _STYLES[kind]
        font_pt, padx, pady, min_h, bold = _SIZES[size]

        bg, fg, hover, border = self._colors(kind, P)
        options = dict(
            text=text, command=command, state=state,
            font=self._font(font_pt, bold), fg=fg, bg=bg,
            activeforeground=fg, activebackground=hover,
            relief="flat", bd=0, padx=self._scale(padx),
            pady=self._scale(pady), cursor="hand2",
            highlightthickness=1 if border else 0,
        )
        if border:
            options["highlightbackground"] = border
        if width is not None:
            options["width"] = width
        if wraplength is not None:
            options["wraplength"] = wraplength
            options["justify"] = "left"
        super().__init__(master, **options)
        if state != "normal":
            self.configure(cursor="arrow", bg=self._disabled_colors(P)[0],
                           fg=self._disabled_colors(P)[1],
                           activebackground=self._disabled_colors(P)[0])
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    # ------------------------------------------------------------ 内部
    def _colors(self, kind: ButtonType, P: dict):
        style = _STYLES[kind]

        def resolve(key: str):
            palette_key = style.get(key + "_key")
            if palette_key and P.get(palette_key):
                return P[palette_key]
            return style[key.replace("_key", "")]

        bg = resolve("bg")
        fg = resolve("fg")
        hover = resolve("hover")
        border = P.get("border") if style.get("border_key") else None
        return bg, fg, hover, border

    @staticmethod
    def _disabled_colors(P: dict):
        return P.get("chip", "#E8EEF7"), P.get("muted", "#5B6574")

    def _on_enter(self, _event=None):
        if str(self.cget("state")) == "normal":
            self.configure(bg=self._colors(self._kind, self._palette)[2])

    def _on_leave(self, _event=None):
        if str(self.cget("state")) == "normal":
            self.configure(bg=self._colors(self._kind, self._palette)[0])

    def button_type(self) -> ButtonType:
        return self._kind

    def set_state(self, state: str) -> None:
        self.configure(state=state,
                       cursor="hand2" if state == "normal" else "arrow")
        bg, fg = self._colors(self._kind, self._palette)[0], \
            self._colors(self._kind, self._palette)[1]
        if state != "normal":
            bg, fg = self._disabled_colors(self._palette)
        self.configure(bg=bg, fg=fg, activebackground=bg)

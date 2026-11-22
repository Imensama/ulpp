# -*- coding: utf-8 -*-
"""AppButton：5 种语义、固定样式、非法参数拒绝、状态与缩放。"""
from __future__ import annotations

import unittest

import tkinter as tk

from ulpp.ui.buttons import AppButton, ButtonType
from ulpp.ui.scale import LIGHT

from .ui_harness import UiCase


class ButtonTests(UiCase):
    def _button(self, button_type, **kw):
        btn = AppButton(self.root, "按钮", lambda: None, button_type=button_type,
                        palette=LIGHT, **kw)
        self.addCleanup(btn.destroy)
        return btn

    def test_all_types_use_fixed_colors(self):
        cases = {
            "submit": (LIGHT["accent"], LIGHT["accent_text"]),
            "cancel": (LIGHT["card"], LIGHT["text"]),
            "warning": ("#B45309", "#FFFFFF"),
            "danger": ("#B91C1C", "#FFFFFF"),
            "info": (LIGHT["soft"], LIGHT["soft_text"]),
        }
        for kind, (bg, fg) in cases.items():
            btn = self._button(kind)
            self.assertEqual(btn.cget("bg"), bg, kind)
            self.assertEqual(btn.cget("fg"), fg, kind)
            self.assertIs(btn.button_type(), ButtonType(kind))

    def test_cancel_has_border_others_do_not(self):
        self.assertEqual(int(str(self._button("cancel").cget("highlightthickness"))), 1)
        for kind in ("submit", "warning", "danger", "info"):
            self.assertEqual(int(str(self._button(kind).cget("highlightthickness"))), 0)

    def test_enum_and_string_are_both_accepted(self):
        btn = self._button(ButtonType.SUBMIT)
        self.assertEqual(btn.cget("bg"), LIGHT["accent"])

    def test_unknown_type_and_size_are_rejected(self):
        with self.assertRaises(ValueError):
            self._button("primary")
        with self.assertRaises(ValueError):
            self._button("submit", size="xl")

    def test_style_kwargs_are_rejected(self):
        for kwargs in ({"bg": "#000"}, {"fg": "#000"}, {"font": ("X", 1)},
                       {"padx": 3}, {"relief": "flat"}):
            with self.assertRaises(TypeError):
                AppButton(self.root, "x", lambda: None, button_type="info",
                          palette=LIGHT, **kwargs)

    def test_disabled_state_uses_muted_colors_and_set_state_restores(self):
        btn = self._button("submit", state="disabled")
        self.assertEqual(btn.cget("bg"), LIGHT["chip"])
        self.assertEqual(btn.cget("fg"), LIGHT["muted"])
        btn.set_state("normal")
        self.assertEqual(btn.cget("bg"), LIGHT["accent"])
        self.assertEqual(btn.cget("fg"), LIGHT["accent_text"])

    def test_command_fires(self):
        calls = []
        btn = AppButton(self.root, "go", lambda: calls.append(1),
                        button_type="submit", palette=LIGHT)
        self.addCleanup(btn.destroy)
        btn.invoke()
        self.assertEqual(calls, [1])

    def test_sizes_change_font_and_padding(self):
        sm = self._button("submit", size="sm")
        lg = self._button("submit", size="lg")
        self.assertIn("10", str(sm.cget("font")))
        self.assertIn("13", str(lg.cget("font")))
        self.assertLess(int(str(sm.cget("padx"))), int(str(lg.cget("padx"))))
        self.assertLess(int(str(sm.cget("pady"))), int(str(lg.cget("pady"))))

    def test_palette_override_and_scale(self):
        btn = AppButton(self.root, "x", lambda: None, button_type="submit",
                        palette=dict(LIGHT, accent="#123456"),
                        scale=lambda px: px * 2)
        self.addCleanup(btn.destroy)
        self.assertEqual(btn.cget("bg"), "#123456")
        self.assertEqual(int(str(btn.cget("padx"))), 32)   # md: 16 * 2

    def test_hover_changes_and_restores(self):
        btn = self._button("submit")
        normal = btn.cget("bg")
        btn._on_enter()
        self.assertEqual(btn.cget("bg"), LIGHT["soft_text"])
        btn._on_leave()
        self.assertEqual(btn.cget("bg"), normal)

    def test_hover_is_ignored_when_disabled(self):
        btn = self._button("submit", state="disabled")
        bg = btn.cget("bg")
        btn._on_enter()
        self.assertEqual(btn.cget("bg"), bg)

    def test_wraplength_and_width_are_accepted(self):
        btn = self._button("info", wraplength=200, width=12)
        self.assertEqual(int(str(btn.cget("wraplength"))), 200)
        self.assertEqual(int(str(btn.cget("width"))), 12)

    def test_default_context_uses_light_theme(self):
        btn = AppButton(self.root, "x", lambda: None, button_type="submit")
        self.addCleanup(btn.destroy)
        self.assertEqual(btn.cget("bg"), LIGHT["accent"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

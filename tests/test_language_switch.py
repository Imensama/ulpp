# -*- coding: utf-8 -*-
"""语言切换检查点（CI 里的独立门）：控件必须可见、且真的换掉界面文案。

为什么单独一个文件：语言按钮是"看起来没问题、其实没接线"的高发区——
事件绑了但回调没重建界面、或重建后控件丢了。这里用真实 Tk 把两件事都钉死：

1. 语言控件存在、在布局里、只读、候选语言齐全、当前值正确；
2. 选中另一种语言后，标题 / 状态栏 / 主按钮文案确实变成目标语言，
   并且重建后的语言控件仍然存在、值正确。
"""
from __future__ import annotations

import unittest

from ulpp.gui import App
from ulpp.i18n import (available_languages, current_language, language_name,
                       load_pack, tr)

from .ui_harness import UiCase


class LanguageControlTests(UiCase):
    """v1 主界面的语言下拉框（`lang_cb`）。"""

    def _app(self):
        app = App(self.root, lang="zh_CN")
        self.pump()
        return app

    # ------------------------------------------------------------ 可见性
    def test_control_exists_visible_and_wired(self):
        app = self._app()
        cb = app.lang_cb
        self.assertTrue(cb.winfo_exists(), "语言控件不存在")
        # 根窗口在测试里 withdraw，不能用 ismapped；用布局管理器证明它被放进去了
        self.assertEqual(cb.winfo_manager(), "pack")
        self.assertTrue(cb.master.winfo_exists())
        self.assertIn(cb.master.winfo_manager(), ("pack", "grid"))
        self.assertEqual(str(cb.cget("state")), "readonly")
        self.assertTrue(cb.bind("<<ComboboxSelected>>"),
                        "没有绑定选择事件，点了不会切语言")

    def test_control_lists_every_supported_language(self):
        app = self._app()
        values = tuple(app.lang_cb.cget("values"))
        expected = tuple(language_name(code) for code in available_languages())
        self.assertEqual(values, expected)
        self.assertIn("中文", values)
        self.assertIn("English", values)
        self.assertEqual(app.lang_display.get(), language_name(current_language()))

    # ------------------------------------------------------------ 切换
    def test_switch_language_changes_visible_text(self):
        app = self._app()
        zh_start = tr("gui.btn.start")
        app.lang_display.set(language_name("en_US"))
        app._on_lang_selected()
        self.pump()

        self.assertEqual(current_language(), "en_US")
        self.assertEqual(app.lang_display.get(), "English")
        self.assertEqual(app.status.get(), tr("gui.status.ready"))
        self.assertEqual(app.start_btn.cget("text"), tr("gui.btn.start"))
        # 必须真的换了文案，而不是"重建了但还用旧语言"
        self.assertNotEqual(zh_start, app.start_btn.cget("text"))
        self.assertEqual(app.start_btn.cget("text"),
                         load_pack("en_US")["gui.btn.start"])

    def test_control_survives_rebuild_and_switches_back(self):
        app = self._app()
        app.lang_display.set(language_name("en_US"))
        app._on_lang_selected()
        self.pump()

        # 重建后是一个新控件，但仍然存在、值正确、候选齐全
        cb = app.lang_cb
        self.assertTrue(cb.winfo_exists())
        self.assertEqual(cb.winfo_manager(), "pack")
        self.assertEqual(app.lang_display.get(), "English")
        self.assertIn("中文", tuple(cb.cget("values")))

        app.lang_display.set(language_name("zh_CN"))
        app._on_lang_selected()
        self.pump()
        self.assertEqual(current_language(), "zh_CN")
        self.assertEqual(app.lang_display.get(), "中文")
        self.assertEqual(app.start_btn.cget("text"),
                         load_pack("zh_CN")["gui.btn.start"])

    def test_switch_preserves_user_content(self):
        app = self._app()
        app.files = ["/tmp/a.pdf"]
        app.listbox.insert("end", "a.pdf")
        app.text_box.insert("1.0", "用户粘的文字")
        app.lang_display.set(language_name("en_US"))
        app._on_lang_selected()
        self.pump()
        self.assertEqual(app.listbox.get(0), "a.pdf")
        self.assertIn("用户粘的文字", app.text_box.get("1.0", "end"))

    def test_unknown_language_selection_is_ignored(self):
        app = self._app()
        before = app.lang_display.get()
        app.lang_display.set("Klingon")
        app._on_lang_selected()
        self.assertEqual(app.lang_display.get(), before)
        self.assertEqual(current_language(), "zh_CN")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

# -*- coding: utf-8 -*-
"""v2 向导文案（``ulpp.ui.texts``）：不建窗口就能查出的那类错。

界面跑起来才发现"少一句翻译"太晚，这里把能静态查的规则钉住：
中英 key 必须一一对应、每一站都要有标题/正文/提示、占位符两边写法一致。
"""

import re
import string
import unittest

from ulpp.ui import texts as tx
from ulpp.ui.flow import STEP_IDS

_PLACEHOLDER = re.compile(r"\{(\w+)(?::[^}]*)?\}")


def _placeholders(text: str) -> set:
    return {name for name in _PLACEHOLDER.findall(text)}


class TextPackTests(unittest.TestCase):
    def test_supported_languages(self):
        self.assertEqual(set(tx.TEXTS), {"zh_CN", "en_US"})

    def test_key_sets_match(self):
        zh = set(tx.TEXTS["zh_CN"])
        en = set(tx.TEXTS["en_US"])
        self.assertEqual(zh - en, set(), "中文有、英文缺")
        self.assertEqual(en - zh, set(), "英文有、中文缺")

    def test_every_step_has_title_body_tip(self):
        for step in STEP_IDS:
            for suffix in ("title", "body", "tip"):
                key = "%s.%s" % (step, suffix)
                for lang in tx.TEXTS:
                    self.assertIn(key, tx.TEXTS[lang], "%s 缺 %s" % (lang, key))
                    self.assertTrue(tx.TEXTS[lang][key].strip())

    def test_step_names_for_status_dots(self):
        for step in STEP_IDS:
            for lang in tx.TEXTS:
                self.assertIn("step." + step, tx.TEXTS[lang])

    def test_placeholders_match_between_languages(self):
        zh, en = tx.TEXTS["zh_CN"], tx.TEXTS["en_US"]
        for key in sorted(set(zh) & set(en)):
            self.assertEqual(_placeholders(zh[key]), _placeholders(en[key]),
                             "占位符不一致：%s" % key)

    def test_placeholders_are_real_fields(self):
        """``{list}`` 这种写法是合法的 format 字段，但带空格/点号的不是。"""
        for lang, pack in tx.TEXTS.items():
            for key, value in pack.items():
                for field in _placeholders(value):
                    self.assertTrue(field.isidentifier(), "%s/%s → %r" % (lang, key, field))

    def test_texts_falls_back_to_chinese(self):
        self.assertEqual(tx.texts("en_US")["app"], "Universal Label Printing Platform")
        self.assertEqual(tx.texts("fr_FR")["app"], "通用标签打印平台")

    def test_no_empty_strings(self):
        for lang, pack in tx.TEXTS.items():
            for key, value in pack.items():
                self.assertTrue(value.strip(), "%s/%s 是空的" % (lang, key))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

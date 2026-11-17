# -*- coding: utf-8 -*-
"""卡片字段行的两个回归（2026-11-16 KTX1250 那张报的"缺字"）：

1. 字段之间夹着备注/手写行（如 \"12×4 黑色\"）时，后面的 颜色/数量 不能丢；
2. 字段值为空（\"包络尺寸:\"）时，不能把冒号当成值。
"""

import unittest

from ulpp import parser as P


def word(text, x0, top, width=12.0, height=12.0):
    return {"text": text, "x0": float(x0), "x1": float(x0) + width,
            "top": float(top), "bottom": float(top) + height}


class CardLineTests(unittest.TestCase):
    def test_note_line_between_fields_does_not_end_card(self):
        words = [
            word("文件名称:一体式刮条", 660, 171, 82),
            word("包络尺寸:", 660, 184, 39),
            word("序号:10", 660, 197, 30),
            word("12×4黑色", 730, 203, 56),      # 备注行，插在字段中间
            word("颜色:", 660, 210, 22),
            word("数量:0.6m", 660, 222, 40),
        ]
        lines = P._group_lines(words)
        picked = P._card_lines(lines, words[0])
        texts = [text for text, _ in picked]
        self.assertIn("文件名称:一体式刮条", texts)
        self.assertIn("颜色:", texts)
        self.assertIn("数量:0.6m", texts)
        # 备注行不进字段文本（否则会把 12×4 当颜色值）
        self.assertNotIn("12×4黑色", texts)

    def test_eight_note_lines_do_not_drop_fields(self):
        """内容多到 8 行备注时，颜色/数量 仍然要收进来看（原来跳 6 行就收工）。"""
        words = [
            word("文件名称:一体式刮条", 660, 171, 82),
            word("包络尺寸:", 660, 184, 39),
            word("序号:10", 660, 197, 30),
        ]
        for i in range(8):
            words.append(word("说明第%d行" % (i + 1), 730, 203 + i * 13, 56))
        words.append(word("颜色:", 660, 320, 22))
        words.append(word("数量:0.6m", 660, 333, 40))
        lines = P._group_lines(words)
        picked = P._card_lines(lines, words[0])
        texts = [text for text, _ in picked]
        self.assertIn("颜色:", texts, "8 行备注之后的字段不能丢")
        self.assertIn("数量:0.6m", texts)

    def test_way_too_many_unknown_lines_stops(self):
        """跑飞保护还在：连续 20 行以上都不是字段，就收工。"""
        words = [word("文件名称:A", 0, 0)]
        for i in range(1, 30):
            words.append(word("图纸标注%d" % i, 0, i * 13))
        lines = P._group_lines(words)
        picked = P._card_lines(lines, words[0])
        self.assertEqual(len(picked), 1)

    def test_nine_unknown_lines_do_not_stop(self):
        """9 行备注也还在容差内（上限 20）。"""
        words = [word("文件名称:A", 0, 0)]
        for i in range(1, 10):
            words.append(word("图纸标注%d" % i, 0, i * 13))
        words.append(word("数量:3", 0, 200))
        lines = P._group_lines(words)
        picked = P._card_lines(lines, words[0])
        self.assertIn("数量:3", [t for t, _ in picked])


class EmptyValueTests(unittest.TestCase):
    def test_empty_size_and_color(self):
        out = P.parse_card_text("文件名称:一体式刮条\n包络尺寸:\n序号:10\n颜色:\n数量:1")
        self.assertEqual(out["name"], "一体式刮条")
        self.assertEqual(out["size"], "")
        self.assertEqual(out["color"], "")
        self.assertEqual(out["seq"], 10)

    def test_normal_values_still_parse(self):
        out = P.parse_card_text("文件名称:KTX-1\n包络尺寸:1030x25x3\n颜色:黄铜\n数量:2")
        self.assertEqual(out["size"], "1030x25x3")
        self.assertEqual(out["color"], "黄铜")
        self.assertEqual(out["qty"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

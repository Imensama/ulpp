# -*- coding: utf-8 -*-
"""解析回归：相邻两格文字坐标重叠时，不能把两张卡粘成一张（2026-11-16 泰国小U 事故）。

客户图纸不进仓库，这里用 pypdf 现场合成一份"两段文字故意重叠 10pt"的小 PDF。
"""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from ulpp import parser as P

NAME_A = "J.02.06.R2F16-护板"
NAME_B = "J.02.06.R2F31-安装锁上盖"


def _hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _cid_font() -> DictionaryObject:
    """不嵌字体，用 Adobe-GB1 的标准 CID 字体（查看器都自带）。"""
    descriptor = DictionaryObject({
        NameObject("/Type"): NameObject("/FontDescriptor"),
        NameObject("/FontName"): NameObject("/STSong-Light"),
        NameObject("/Flags"): NumberObject(4),
        NameObject("/FontBBox"): ArrayObject([NumberObject(0), NumberObject(-200),
                                             NumberObject(1000), NumberObject(900)]),
        NameObject("/ItalicAngle"): NumberObject(0),
        NameObject("/Ascent"): NumberObject(880),
        NameObject("/Descent"): NumberObject(-120),
        NameObject("/CapHeight"): NumberObject(700),
        NameObject("/StemV"): NumberObject(80),
    })
    cid = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/CIDFontType0"),
        NameObject("/BaseFont"): NameObject("/STSong-Light"),
        NameObject("/CIDSystemInfo"): DictionaryObject({
            NameObject("/Registry"): TextStringObject("Adobe"),
            NameObject("/Ordering"): TextStringObject("GB1"),
            NameObject("/Supplement"): NumberObject(4),
        }),
        NameObject("/FontDescriptor"): descriptor,
    })
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type0"),
        NameObject("/BaseFont"): NameObject("/STSong-Light"),
        NameObject("/Encoding"): NameObject("/UniGB-UTF16-H"),
        NameObject("/DescendantFonts"): ArrayObject([cid]),
    })
    return font


def make_overlap_pdf(path: Path, gap_pt: float = 10.0) -> Path:
    """两段"文件名称:…"文字，第二段起点比第一段的终点还靠左 → 坐标重叠。"""
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = _cid_font()
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    # 每个字 10pt 宽；第一段 60 → 60+10*len(A)，第二段从 (第一段终点 - gap) 开始
    first_end = 60 + 10 * len("文件名称:" + NAME_A)
    second_x = first_end - gap_pt
    stream = (
        "BT /F1 10 Tf 1 0 0 1 60 700 Tm <%s> Tj ET "
        "BT /F1 10 Tf 1 0 0 1 %.2f 700 Tm <%s> Tj ET"
        % (_hex("文件名称:" + NAME_A), second_x, _hex("文件名称:" + NAME_B))
    ).encode("ascii")
    body = DecodedStreamObject()
    body.set_data(stream)
    page[NameObject("/Contents")] = writer._add_object(body)
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


class OverlapTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_overlap_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pdf = make_overlap_pdf(self.dir / "overlap.pdf")

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def test_overlapping_cards_are_both_parsed(self):
        cards = P.parse_pdf(str(self.pdf)).cards
        names = [c.name for c in cards]
        self.assertEqual(len(cards), 2, names)
        self.assertIn(NAME_A, names)
        self.assertIn(NAME_B, names)
        self.assertEqual(len({(c.col, c.row) for c in cards}), 2)

    def test_no_warning_on_clean_overlap(self):
        page = P.parse_pdf(str(self.pdf)).pages[0]
        self.assertEqual(page.warnings, [])

    def test_merged_anchor_word_is_split(self):
        """两种取词都粘连时，按字符比例切出两个锚点（兜底路径）。"""
        word = {"text": "文件名称:" + NAME_A + "文件名称:" + NAME_B,
                "x0": 10.0, "x1": 410.0, "top": 5.0, "bottom": 15.0}
        _words, anchors = P._split_merged_anchors([word])
        self.assertEqual(len(anchors), 2)
        self.assertTrue(anchors[1]["text"].startswith("文件名称:" + NAME_B))
        self.assertLess(anchors[0]["x1"], anchors[1]["x1"])

    def test_page_noise_is_dropped(self):
        self.assertTrue(P.PAGE_NOISE.search("第10页(共512页)"))
        self.assertTrue(P.PAGE_NOISE.search("Page 3 of 9"))
        self.assertFalse(P.PAGE_NOISE.search("包络尺寸:119x91x28.5"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

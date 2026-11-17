# -*- coding: utf-8 -*-
"""边缘对位刻度（marks）：只在纸边印，不碰标签；边距太小时安静跳过。"""

import tempfile
import unittest
import uuid
from pathlib import Path

from pypdf import PdfReader

from ulpp.builder import build_pdf
from ulpp.config import GridSpec


class MarksTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_marks_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def _build(self, name, **kw):
        path = self.dir / name
        build_pdf([], GridSpec(**kw) if kw else GridSpec(), str(path))
        return path

    def _content_size(self, path):
        page = PdfReader(str(path)).pages[0]
        data = page.get_contents().get_data()
        return len(data), PdfReader(str(path)).pages[0]

    def test_marks_add_content(self):
        plain = self.dir / "plain.pdf"
        marked = self.dir / "marked.pdf"
        build_pdf([], GridSpec(), str(plain))
        build_pdf([], GridSpec(), str(marked), marks=True)
        self.assertGreater(self._content_size(marked)[0],
                           self._content_size(plain)[0])
        # 两种都还是 1 页 A4
        for path in (plain, marked):
            page = PdfReader(str(path)).pages[0]
            self.assertAlmostEqual(float(page.mediabox.width), 595.28, places=1)

    def test_tiny_margin_does_not_crash(self):
        path = self.dir / "tight.pdf"
        grid = GridSpec(margin_top=0.5, margin_left=0.2)
        build_pdf([], grid, str(path), marks=True)
        self.assertTrue(path.is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

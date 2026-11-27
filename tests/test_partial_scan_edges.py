# -*- coding: utf-8 -*-
"""补测：PDF 兜底路径、异常分支，把 partial_scan 的覆盖率拉回门槛以上。"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from ulpp import partial_scan
from ulpp.partial_scan import (
    _cell_stats,
    _line_pixels,
    _pdf_image,
    _pdf_image_count,
    _sheet_is_damaged,
    analyze,
)
from ulpp.templates import GridSpec

needs_numpy = unittest.skipUnless(partial_scan._HAS_NUMPY, "需要 numpy")

DPI = 300
PAGE_W, PAGE_H = 210.0, 297.0
COLS, ROWS = 5, 9
CELL_W, CELL_H = 40.0, 30.0
PITCH_X, PITCH_Y = 41.5, 32.0


def make_grid(margin_top: float = 6.0) -> GridSpec:
    return GridSpec(page_w=PAGE_W, page_h=PAGE_H, cols=COLS, rows=ROWS,
                    cell_w=CELL_W, cell_h=CELL_H, pitch_x=PITCH_X, pitch_y=PITCH_Y,
                    margin_top=margin_top, margin_left=None, inset=2.0)


def simple_sheet() -> Image.Image:
    """画一张最朴素的"标签纸"：白纸 + 灰线 + 几个偏蓝的已用格。"""
    px = DPI / 25.4
    img = Image.new("RGB", (int(PAGE_W * px), int(PAGE_H * px)), (252, 251, 246))
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    block_w = (COLS - 1) * PITCH_X + CELL_W
    left = (PAGE_W - block_w) / 2
    for r in range(ROWS):
        for c in range(COLS):
            x0 = (left + c * PITCH_X) * px
            y0 = (margin_top_px := (6.0 + r * PITCH_Y) * px)
            fill = (237, 241, 251) if (r, c) == (0, 0) else (253, 253, 250)
            d.rectangle([x0, y0, x0 + CELL_W * px, y0 + CELL_H * px], fill=fill,
                        outline=(200, 200, 195))
    _ = margin_top_px
    return img


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.gettempdir(), "ulpp_pcov_%s" % uuid.uuid4().hex[:8])
        os.makedirs(self.dir, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.grid = make_grid()

    def save(self, img: Image.Image, name: str) -> str:
        path = os.path.join(self.dir, name)
        img.save(path)
        return path


@needs_numpy
class PdfFallbackTests(Case):
    """没有 pypdfium2 时走 pypdf 取嵌图的老路。"""

    def test_falls_back_when_renderer_missing(self):
        path = self.save(simple_sheet(), "sheet.pdf")
        with mock.patch("ulpp.scan.render_pdf_page", return_value=None):
            verdict = analyze(path, self.grid)
        self.assertIn(0, verdict.used)         # 左上角那格是"撕掉"的
        self.assertTrue(verdict.ok, verdict.warnings)

    def test_layered_pdf_warns(self):
        path = self.save(simple_sheet(), "layered.pdf")
        with mock.patch("ulpp.scan.render_pdf_page", return_value=None), \
                mock.patch.object(partial_scan, "_pdf_image_count", return_value=48):
            verdict = analyze(path, self.grid)
        self.assertTrue(any(w.startswith("pdf_layered") for w in verdict.warnings + [""])
                        or any("多层" in w for w in verdict.warnings), verdict.warnings)

    def test_pdf_without_bitmap_fails_with_reason(self):
        from pypdf import PdfWriter

        path = os.path.join(self.dir, "vector.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with open(path, "wb") as fh:
            writer.write(fh)
        with mock.patch("ulpp.scan.render_pdf_page", return_value=None):
            verdict = analyze(path, self.grid)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.warnings[0].startswith("fail:"))


@needs_numpy
class HelperEdgeTests(Case):
    def test_image_count_counts_image_xobjects(self):
        page = {"_": 1}

        class Obj(dict):
            def get_object(self):
                return self

        class Page(dict):
            def get(self, key, default=None):
                if key == "/Resources":
                    return Obj({"/XObject": Obj({
                        "/Im1": Obj({"/Subtype": "/Image"}),
                        "/Im2": Obj({"/Subtype": "/Image"}),
                        "/Fm1": Obj({"/Subtype": "/Form"}),
                    })})
                return super().get(key, default)

        self.assertEqual(_pdf_image_count(Page()), 2)

    def test_image_count_survives_broken_page(self):
        class Boom(dict):
            def get(self, *_a, **_k):
                raise RuntimeError("bad")

        self.assertEqual(_pdf_image_count(Boom()), 0)

    def test_line_pixels_rejects_grid_outside_page(self):
        import numpy as np

        gray = np.zeros((100, 100), dtype=np.float32)
        far = GridSpec(page_w=210.0, page_h=297.0, cols=5, rows=9, cell_w=40.0,
                       cell_h=30.0, pitch_x=41.5, pitch_y=32.0, margin_top=200.0,
                       margin_left=None, inset=2.0)
        self.assertIsNone(_line_pixels(far, gray, 1.0, 4))

    def test_cell_stats_rejects_empty_cells(self):
        import numpy as np

        tiny = np.zeros((10, 10), dtype=np.int16)
        xs = [0, 2, 2]                    # 第二格宽度为 0：切不出像素
        ys = [0, 2, 2]
        grid = GridSpec(page_w=10.0, page_h=10.0, cols=2, rows=2, cell_w=4.0,
                        cell_h=4.0, pitch_x=5.0, pitch_y=5.0, margin_top=0.0,
                        margin_left=0.0, inset=0.0)
        stats = _cell_stats(grid, tiny, tiny.astype(np.float32), xs, ys)
        self.assertIsNone(stats)          # 格子小到切不出来时必须返回 None

    def test_pdf_image_on_missing_file_is_empty(self):
        image, warns = _pdf_image(os.path.join(self.dir, "nope.pdf"))
        self.assertIsNone(image)
        self.assertTrue(isinstance(warns, list))


if __name__ == "__main__":
    unittest.main()

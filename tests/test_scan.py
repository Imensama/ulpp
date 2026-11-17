# -*- coding: utf-8 -*-
"""扫描标定（``ulpp.scan``）：合成图跑通 + 空图能识别出来。"""

import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from ulpp.scan import describe, measure_file

DPI = 150
PX_PER_MM = DPI / 25.4


def make_sheet(path, cols=5, rows=9, pitch_x=41.5, pitch_y=32.0,
               cell_w=40.0, cell_h=30.0, margin_l=2.0, margin_t=5.0,
               line_w=0.35, paper=240, line=150):
    """画一张"合成胶纸"：白纸 + 细线格阵 + 光照不均 + 噪点。"""
    w, h = int(round(210 * PX_PER_MM)), int(round(297 * PX_PER_MM))
    img = Image.new("L", (w, h), paper)
    d = ImageDraw.Draw(img)
    lw = max(1, int(round(line_w * PX_PER_MM)))
    for c in range(cols + 1):
        x = (margin_l + c * pitch_x) * PX_PER_MM
        d.rectangle([x, 0, x + lw, h], fill=line)
    for r in range(rows + 1):
        y = (margin_t + r * pitch_y) * PX_PER_MM
        d.rectangle([0, y, w, y + lw], fill=line)
    # 光照不均：左上亮、右下暗
    grad = Image.linear_gradient("L").resize((w, h)).rotate(90)
    img = ImageChops.multiply(img, ImageChops.invert(grad.point(lambda v: v // 3)))
    # 噪点
    noise = Image.effect_noise((w, h), 14).point(lambda v: 128 + (v - 128) // 6)
    img = Image.blend(img, noise, 0.06)
    img.save(str(path), dpi=(DPI, DPI))
    return path


class MeasureSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_scan_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def test_standard_45_up(self):
        path = make_sheet(self.dir / "sheet.png")
        m = measure_file(str(path))
        self.assertEqual((m.cols, m.rows), (5, 9))
        self.assertAlmostEqual(m.pitch_x_mm, 41.5, delta=0.2)
        self.assertAlmostEqual(m.pitch_y_mm, 32.0, delta=0.2)
        self.assertGreater(m.confidence, 0.5)
        self.assertLess(m.first_x_mm, m.pitch_x_mm)
        self.assertTrue(m.ok, m.warnings)

    def test_other_layout_4x10(self):
        path = make_sheet(self.dir / "sheet40.png", cols=4, rows=10,
                          pitch_x=41.5, pitch_y=32.0, cell_w=40.0, cell_h=30.0)
        m = measure_file(str(path), expect_cols=4, expect_rows=10)
        self.assertEqual((m.cols, m.rows), (4, 10))
        self.assertAlmostEqual(m.pitch_x_mm, 41.5, delta=0.2)
        self.assertAlmostEqual(m.pitch_y_mm, 32.0, delta=0.2)

    def test_blank_scan_is_rejected(self):
        path = self.dir / "blank.png"
        Image.new("L", (1240, 1754), 252).save(str(path), dpi=(DPI, DPI))
        with self.assertRaises(ValueError):
            measure_file(str(path))

    def test_missing_dpi_warns(self):
        src = make_sheet(self.dir / "sheet.png")
        plain = self.dir / "nodpi.png"
        Image.open(src).save(str(plain))          # 不加 dpi 元数据
        m = measure_file(str(plain))
        self.assertTrue(any(w.startswith("no-dpi") for w in m.warnings))

    def test_describe_is_readable(self):
        path = make_sheet(self.dir / "sheet.png")
        text = describe(measure_file(str(path)))
        self.assertIn("列", text)
        self.assertIn("节距", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

# -*- coding: utf-8 -*-
"""图片贴纸：JPG/PNG 每张算一张卡，能独立排版、也能接着打。"""

import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from ulpp.builder import ImageSticker, build_all, build_partial_all, collect_entries
from ulpp.config import GridSpec


def _png(path: Path, size=(240, 160)) -> Path:
    img = Image.new("RGB", size)
    px = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            px[x, y] = (x % 256, y % 256, 128)
    img.save(str(path))
    return path


class ImageStickerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_img_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.png = _png(self.dir / "零件照片.png")

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def test_collect_entries_puts_images_between(self):
        entries = collect_entries([], [], [str(self.png)])
        self.assertEqual(len(entries), 1)
        self.assertIsInstance(entries[0], ImageSticker)
        self.assertEqual(entries[0].path, str(self.png))

    def test_build_all_embeds_image(self):
        out = self.dir / "out"
        results = build_all([], GridSpec(), str(out), base_name="图",
                            make_proof=False, make_csv=False,
                            image_paths=[str(self.png)])
        pdf = results["production"]
        self.assertTrue(Path(pdf).is_file())
        page = PdfReader(pdf).pages[0]
        xobjects = (page.get("/Resources") or {}).get("/XObject")
        self.assertIsNotNone(xobjects)
        images = [o.get_object() for o in xobjects.values()
                  if o.get_object().get("/Subtype") == "/Image"]
        self.assertTrue(images, "PDF 里应该有图片 XObject")
        self.assertEqual(str(images[0]["/ColorSpace"]), "/DeviceRGB")
        self.assertEqual(str(images[0]["/Filter"]), "/DCTDecode")

    def test_partial_with_image(self):
        out = self.dir / "partial"
        placements = {3: ImageSticker(path=str(self.png))}
        results = build_partial_all(placements, GridSpec(), str(out), base_name="图")
        self.assertTrue(Path(results["production"]).is_file())

    def test_missing_image_is_reported(self):
        with self.assertRaises(Exception):
            build_all([], GridSpec(), str(self.dir / "x"), base_name="图",
                      make_proof=False, make_csv=False,
                      image_paths=[str(self.dir / "不存在.png")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

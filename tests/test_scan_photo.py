# -*- coding: utf-8 -*-
"""拍照量纸（``ulpp.scan_photo``）：合成一张"斜拍照片"，拉正后量格阵。

没装 OpenCV 的环境自动跳过（照片功能是可选的）。
"""

import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

try:
    import cv2  # noqa: F401
    import numpy as np  # noqa: F401

    _HAS_CV = True
except Exception:  # pragma: no cover
    _HAS_CV = False

DPI = 300
PX = DPI / 25.4
W, H = int(210 * PX), int(297 * PX)


def make_sheet(cols=5, rows=9, pitch=(41.5, 32.0), cell=(40.0, 30.0),
               margin_x=2.0, margin_y=5.0) -> Image.Image:
    img = Image.new("L", (W, H), 250)
    d = ImageDraw.Draw(img)
    lw = max(1, int(round(0.35 * PX)))
    block_w = (cols - 1) * pitch[0] + cell[0]
    block_h = (rows - 1) * pitch[1] + cell[1]
    for c in range(cols + 1):
        x = (margin_x + c * pitch[0]) * PX
        d.rectangle([x, margin_y * PX, x + lw, (margin_y + block_h) * PX], fill=170)
    for r in range(rows + 1):
        y = (margin_y + r * pitch[1]) * PX
        d.rectangle([margin_x * PX, y, (margin_x + block_w) * PX, y + lw], fill=170)
    return img


def make_photo(sheet: Image.Image, seed: int = 3):
    """纸放在深色桌面上，再做一次透视变换 + 光照不均 + 噪点，模拟手持拍摄。"""
    import cv2
    import numpy as np

    bg = np.full((int(H * 1.35), int(W * 1.35), 3), 38, dtype=np.uint8)
    paper = np.array(sheet.convert("RGB"))
    ox, oy = int(W * 0.18), int(H * 0.17)
    bg[oy:oy + H, ox:ox + W] = paper
    h, w = bg.shape[:2]
    dx, dy = W * 0.04, H * -0.03
    src = np.float32([[ox, oy], [ox + W, oy], [ox + W, oy + H], [ox, oy + H]])
    dst = np.float32([[ox + dx, oy + dy], [ox + W - dx * 0.6, oy + dy * 1.4],
                      [ox + W + dx * 0.4, oy + H - dy], [ox - dx * 0.8, oy + H - dy * 0.5]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(bg, matrix, (w, h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
    yy, xx = np.mgrid[0:h, 0:w]
    vig = 1.0 - 0.25 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    warped = np.clip(warped.astype(np.float32) * vig[..., None], 0, 255).astype(np.uint8)
    rng = np.random.default_rng(seed)
    warped = np.clip(warped.astype(np.float32) + rng.normal(0, 4.0, warped.shape),
                     0, 255).astype(np.uint8)
    return warped


@unittest.skipUnless(_HAS_CV, "没装 OpenCV")
class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_photo_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def _write_photo(self) -> Path:
        import cv2

        photo = make_photo(make_sheet())
        path = self.dir / "phone.jpg"
        ok, buf = cv2.imencode(".jpg", photo, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        self.assertTrue(ok)
        path.write_bytes(buf.tobytes())
        return path

    def test_measure_from_photo(self):
        from ulpp.scan_photo import measure_photo

        m = measure_photo(str(self._write_photo()), expect_cols=5, expect_rows=9)
        self.assertEqual((m.cols, m.rows), (5, 9))
        self.assertAlmostEqual(m.pitch_x_mm, 41.5, delta=0.4)
        self.assertAlmostEqual(m.pitch_y_mm, 32.0, delta=0.4)
        self.assertAlmostEqual(m.first_x_mm, 2.0, delta=1.2)
        self.assertAlmostEqual(m.first_y_mm, 5.0, delta=1.2)
        self.assertTrue(any(w.startswith("photo") for w in m.warnings))

    def test_no_paper_is_rejected(self):
        import cv2
        import numpy as np

        from ulpp.scan_photo import measure_photo

        blank = np.full((1200, 900, 3), 40, dtype=np.uint8)   # 全深色：没有纸
        path = self.dir / "dark.jpg"
        ok, buf = cv2.imencode(".jpg", blank)
        path.write_bytes(buf.tobytes())
        with self.assertRaises(ValueError):
            measure_photo(str(path))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

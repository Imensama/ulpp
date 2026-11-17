# -*- coding: utf-8 -*-
"""标定板模式（``ulpp.scan_calib``）：合成"板 + 胶纸并排 + 透视 + 畸变"的照片，验证精度。

没装 OpenCV 的环境自动跳过。
"""

import tempfile
import unittest
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

try:
    import cv2
    import numpy as np

    _HAS_CV = True
except Exception:  # pragma: no cover
    _HAS_CV = False

from ulpp.scan_board import dot_positions

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


def make_board(mark_mm=4.0) -> Image.Image:
    img = Image.new("L", (W, H), 250)
    d = ImageDraw.Draw(img)
    half = mark_mm / 2 * PX
    for cx, cy in dot_positions():
        x, y = cx * PX, cy * PX
        d.rectangle([x - half, y - half, x + half, y + half], fill=0)
    return img


def make_scene(k1=0.06, tilt=(0.05, -0.04), seed=5) -> np.ndarray:
    board, sheet = make_board(), make_sheet()
    gap = int(W * 0.12)
    canvas_w = W * 2 + gap
    canvas = np.full((H, canvas_w, 3), 40, dtype=np.uint8)
    canvas[:, :W] = np.array(board.convert("RGB"))
    canvas[:, W + gap:] = np.array(sheet.convert("RGB"))

    h, w = canvas.shape[:2]
    dx, dy = w * tilt[0], h * tilt[1]
    pad_x, pad_y = int(w * 0.06), int(h * 0.04)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[pad_x + dx, pad_y + dy], [w - pad_x - dx * 0.7, pad_y + dy * 1.3],
                      [w - pad_x + dx * 0.3, h - pad_y - dy], [pad_x - dx * 0.6, h - pad_y - dy * 0.4]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(canvas, matrix, (w, h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(40, 40, 40))

    if abs(k1) > 1e-9:
        hh, ww = warped.shape[:2]
        cx, cy = ww / 2, hh / 2
        r = max(1.0, 0.5 * (ww ** 2 + hh ** 2) ** 0.5)
        ys, xs = np.mgrid[0:hh, 0:ww].astype(np.float32)
        nx = (xs - cx) / r
        ny = (ys - cy) / r
        f = 1 + k1 * (nx * nx + ny * ny)
        warped = cv2.remap(warped, (cx + nx * f * r).astype(np.float32),
                           (cy + ny * f * r).astype(np.float32), cv2.INTER_CUBIC,
                           borderValue=(40, 40, 40))

    rng = np.random.default_rng(seed)
    warped = np.clip(warped.astype(np.float32) + rng.normal(0, 3.0, warped.shape),
                     0, 255).astype(np.uint8)
    return warped


@unittest.skipUnless(_HAS_CV, "没装 OpenCV")
class CalibTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_calib_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def _write(self, scene, name="scene.jpg") -> Path:
        path = self.dir / name
        ok, buf = cv2.imencode(".jpg", scene, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        self.assertTrue(ok)
        path.write_bytes(buf.tobytes())
        return path

    def test_board_found_and_measured(self):
        from ulpp.scan_calib import measure_photo_calibrated

        m = measure_photo_calibrated(str(self._write(make_scene())), expect_cols=5, expect_rows=9)
        self.assertEqual((m.cols, m.rows), (5, 9))
        self.assertAlmostEqual(m.pitch_x_mm, 41.5, delta=0.35)
        self.assertAlmostEqual(m.pitch_y_mm, 32.0, delta=0.35)
        self.assertTrue(any("标定板" in w for w in m.warnings))

    def test_calibration_beats_plain_on_lens_distortion(self):
        from ulpp.scan_calib import measure_photo_calibrated
        from ulpp.scan_photo import measure_photo

        path = str(self._write(make_scene(k1=0.10)))
        plain = measure_photo(path, expect_cols=5, expect_rows=9)
        calib = measure_photo_calibrated(path, expect_cols=5, expect_rows=9)
        err_plain = abs(plain.pitch_x_mm - 41.5) + abs(plain.pitch_y_mm - 32.0)
        err_calib = abs(calib.pitch_x_mm - 41.5) + abs(calib.pitch_y_mm - 32.0)
        self.assertLess(err_calib, err_plain, "标定后应当更准")

    def test_missing_board_is_reported(self):
        from ulpp.scan_calib import measure_photo_calibrated

        only_sheet = np.full((H, W, 3), 40, dtype=np.uint8)
        only_sheet[:, :] = np.array(make_sheet().convert("RGB"))
        with self.assertRaises(ValueError):
            measure_photo_calibrated(str(self._write(only_sheet, "sheet_only.jpg")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

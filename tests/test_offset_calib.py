# -*- coding: utf-8 -*-
"""试打自动纠偏（``ulpp.offset_calib``）：合成校准页 → 已知平移 → 量回来。

图都是现画的（不往仓库里放真实扫描件）：``render_page`` 出标准页，再用仿射变换
整体平移一个已知量（亚像素 + 轻微模糊，模拟扫描），看 ``measure_offset`` 能不能量回来。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import uuid

from PIL import Image, ImageFilter

from ulpp.offset_calib import OffsetResult, make_page_pdf, measure_offset, render_page
from ulpp.templates import GridSpec

DPI = 300
TOL_MM = 0.2          # 要求：已知平移量回来的误差 ≤ 0.2 mm


def shift_mm(img: Image.Image, dx_mm: float, dy_mm: float) -> Image.Image:
    """把整张图平移 dx/dy 毫米（亚像素），模拟"打印内容相对纸"偏了。"""
    px = DPI / 25.4
    return img.transform(img.size, Image.AFFINE,
                         (1.0, 0.0, -dx_mm * px, 0.0, 1.0, -dy_mm * px),
                         resample=Image.BICUBIC, fillcolor=255)


def scan_like(img: Image.Image, dx_mm: float = 0.0, dy_mm: float = 0.0) -> Image.Image:
    """平移 + 一点模糊：扫描出来的线本来就不是 1 px 硬边。"""
    return shift_mm(img, dx_mm, dy_mm).filter(ImageFilter.GaussianBlur(0.6))


class OffsetCalibTests(unittest.TestCase):
    """校准页出图 / 量偏移 / 各种量不出来的极端情况。"""

    @classmethod
    def setUpClass(cls):
        cls.grid = GridSpec()                 # 默认 5×9，210×297 mm
        cls.page = render_page(cls.grid, DPI)  # 只渲染一次，各用例共用
        cls.dir = os.path.join(tempfile.gettempdir(),
                               "ulpp_offset_%s" % uuid.uuid4().hex[:8])
        os.makedirs(cls.dir, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _save(self, img: Image.Image, name: str) -> str:
        path = os.path.join(self.dir, name)
        img.save(path)
        return path

    def _blank_like_page(self, gray: int) -> str:
        return self._save(Image.new("L", self.page.size, gray), "flat_%d.png" % gray)

    # ------------------------------------------------------------ 正常路径
    def test_known_shift_is_recovered(self):
        """整体偏 +1.2 / −0.8 mm：量回来误差 ≤ 0.2 mm，置信度要够高。"""
        path = self._save(scan_like(self.page, 1.2, -0.8), "shift.png")
        result = measure_offset(path, self.grid, dpi=DPI)

        self.assertLessEqual(abs(result.dx_mm - 1.2), TOL_MM, result)
        self.assertLessEqual(abs(result.dy_mm - (-0.8)), TOL_MM, result)
        self.assertGreaterEqual(result.confidence, 0.5, result)
        self.assertFalse([w for w in result.warnings if w.startswith("fail:")])

    def test_zero_shift_is_zero(self):
        """没偏的时候不该凭空给出偏移（差一点是像素量化，≤0.15 mm）。"""
        path = self._save(scan_like(self.page), "zero.png")
        result = measure_offset(path, self.grid, dpi=DPI)

        self.assertLessEqual(abs(result.dx_mm), 0.15, result)
        self.assertLessEqual(abs(result.dy_mm), 0.15, result)
        self.assertGreaterEqual(result.confidence, 0.5, result)

    def test_dpi_can_be_inferred(self):
        """不给 dpi 时按图宽 / 页宽反推，结果要和给 dpi 时一样准。"""
        path = self._save(scan_like(self.page, 1.2, -0.8), "infer.png")
        result = measure_offset(path, self.grid)

        self.assertLessEqual(abs(result.dx_mm - 1.2), TOL_MM, result)
        self.assertLessEqual(abs(result.dy_mm - (-0.8)), TOL_MM, result)
        self.assertTrue(any(w.startswith("dpi:") for w in result.warnings), result)

    # ------------------------------------------------------------ 量不出来
    def test_blank_page_is_low_confidence(self):
        """空白页：低置信度 + 写清原因，不抛异常。"""
        result = measure_offset(self._blank_like_page(255), self.grid, dpi=DPI)

        self.assertIsInstance(result, OffsetResult)
        self.assertLess(result.confidence, 0.3, result)
        self.assertTrue(result.warnings, result)

    def test_all_black_page_is_low_confidence(self):
        """全黑图：同上。"""
        result = measure_offset(self._blank_like_page(0), self.grid, dpi=DPI)

        self.assertLess(result.confidence, 0.3, result)
        self.assertTrue(result.warnings, result)

    def test_unrelated_aspect_ratio_is_low_confidence(self):
        """正方形（明显不是 A4）：低置信度，并且提示长宽比不对。"""
        side = min(self.page.size)
        path = self._save(self.page.crop((0, 0, side, side)), "square.png")
        result = measure_offset(path, self.grid, dpi=DPI)

        self.assertLess(result.confidence, 0.3, result)
        self.assertTrue(any("A4" in w for w in result.warnings), result)

    def test_tiny_image_is_low_confidence(self):
        """小得离谱的图不能抛异常。"""
        result = measure_offset(self._save(Image.new("L", (16, 16), 200), "tiny.png"),
                                self.grid, dpi=DPI)

        self.assertLess(result.confidence, 0.3, result)
        self.assertTrue(result.warnings, result)

    def test_missing_file_is_low_confidence(self):
        """文件不存在也不能抛异常。"""
        result = measure_offset(os.path.join(self.dir, "没有这张图.png"),
                                self.grid, dpi=DPI)

        self.assertLess(result.confidence, 0.3, result)
        self.assertTrue(result.warnings, result)

    # ------------------------------------------------------------ 出 PDF
    def test_make_page_pdf_writes_pdf(self):
        """校准页 PDF：非空、文件头是 %PDF、返回同一路径。"""
        path = os.path.join(self.dir, "校准页.pdf")
        returned = make_page_pdf(self.grid, path)

        self.assertEqual(returned, path)
        self.assertTrue(os.path.isfile(path))
        self.assertGreater(os.path.getsize(path), 1000)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(4), b"%PDF")

    def test_make_page_pdf_creates_missing_folder(self):
        """目标目录不存在时自己建（界面里传的是用户选的输出目录）。"""
        path = os.path.join(self.dir, "sub", "校准页.pdf")
        make_page_pdf(self.grid, path)

        self.assertTrue(os.path.isfile(path))

    # ------------------------------------------------------------ 数据结构
    def test_warnings_lists_are_independent(self):
        """warnings 用 default_factory：两条结果不能共用同一个 list。"""
        first = OffsetResult(0.0, 0.0, 1.0)
        second = OffsetResult(0.0, 0.0, 0.0)
        first.warnings.append("x")
        self.assertEqual(second.warnings, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

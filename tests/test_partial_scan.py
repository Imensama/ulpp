# -*- coding: utf-8 -*-
"""``ulpp.partial_scan``：合成半张纸 → 判断哪些格用过了。

图都是现画的（不往仓库里放真实扫描件）：一张"标签纸"，标签偏暖白、撕掉后露出偏蓝的底纸，
再用已知集合标出"已用 / 部分撕 / 刀痕"，看能不能判回来。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import uuid
from typing import Optional, Sequence

from PIL import Image, ImageDraw

from ulpp import partial_scan
from ulpp.partial_scan import analyze, describe
from ulpp.templates import GridSpec

needs_numpy = unittest.skipUnless(partial_scan._HAS_NUMPY, "需要 numpy")

DPI = 300
PX = DPI / 25.4
PAGE_W, PAGE_H = 210.0, 297.0
COLS, ROWS = 5, 9
CELL_W, CELL_H = 40.0, 30.0
PITCH_X, PITCH_Y = 41.5, 32.0
MARGIN_TOP = 6.0

PAPER = (252, 251, 246)      # 纸面（暖白）
LABEL = (253, 253, 250)      # 标签还在（更白一点）
LINER = (237, 241, 251)      # 撕掉后露出的底纸（浅蓝紫，实测样张就是这个色阶）
STAIN = (226, 222, 206)      # 水渍（偏黄）
INK = (35, 35, 35)           # 打印的墨
GRID = (198, 198, 192)       # 格线


def make_grid() -> GridSpec:
    return GridSpec(page_w=PAGE_W, page_h=PAGE_H, cols=COLS, rows=ROWS,
                    cell_w=CELL_W, cell_h=CELL_H, pitch_x=PITCH_X, pitch_y=PITCH_Y,
                    margin_top=MARGIN_TOP, margin_left=None, inset=2.0)


def render(peeled: Sequence[int] = (), partial: Sequence[int] = (),
           damaged: Sequence[int] = (), printed: Sequence[int] = (),
           stained: Sequence[int] = ()) -> Image.Image:
    """画一张标签纸。索引口径：行优先，0 基（和分析结果一致）。"""
    block_w = (COLS - 1) * PITCH_X + CELL_W
    left = (PAGE_W - block_w) / 2.0
    img = Image.new("RGB", (int(PAGE_W * PX), int(PAGE_H * PX)), PAPER)
    d = ImageDraw.Draw(img)

    def box(r: int, c: int):
        x0 = (left + c * PITCH_X) * PX
        y0 = (MARGIN_TOP + r * PITCH_Y) * PX
        return x0, y0, x0 + CELL_W * PX, y0 + CELL_H * PX

    for r in range(ROWS):
        for c in range(COLS):
            i = r * COLS + c
            x0, y0, x1, y1 = box(r, c)
            if i in peeled:
                d.rectangle([x0, y0, x1, y1], fill=LINER)
            elif i in partial:                     # 只撕掉左半边
                d.rectangle([x0, y0, x1, y1], fill=LABEL)
                d.rectangle([x0, y0, (x0 + x1) / 2, y1], fill=LINER)
            else:
                d.rectangle([x0, y0, x1, y1], fill=LABEL)
            if i in stained:                       # 水渍：一块偏黄的污迹
                d.rectangle([x0 + 6, y0 + 6, x1 - 30, y1 - 30], fill=STAIN)
            if i in printed:                       # 打印：几道墨迹（约 5% 面积）
                for k in range(3):
                    yy = y0 + 20 + k * 26
                    d.rectangle([x0 + 24, yy, x1 - 24, yy + 9], fill=INK)
            if i in damaged:                       # 刀痕/撕口：一条深色斜线
                d.line([x0 + 8, y1 - 8, x1 - 20, y1 - 40], fill=(120, 120, 120), width=6)

    # 格线
    for r in range(ROWS + 1):
        y = (MARGIN_TOP + r * PITCH_Y) * PX
        d.line([left * PX, y, (left + block_w) * PX, y], fill=GRID, width=2)
    for c in range(COLS + 1):
        x = (left + c * PITCH_X) * PX
        d.line([x, MARGIN_TOP * PX, x, (MARGIN_TOP + (ROWS - 1) * PITCH_Y + CELL_H) * PX],
               fill=GRID, width=2)
    return img


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(tempfile.gettempdir(), "ulpp_pscan_%s" % uuid.uuid4().hex[:8])
        os.makedirs(self.dir, exist_ok=True)
        self.grid = make_grid()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def save(self, img: Image.Image, name: str = "sheet.png") -> str:
        path = os.path.join(self.dir, name)
        img.save(path)
        return path


@needs_numpy
class ClassifyTests(Case):
    def test_all_labels_on_means_nothing_used(self):
        verdict = analyze(self.save(render()), self.grid, dpi=DPI)
        self.assertTrue(verdict.ok, verdict)
        self.assertEqual(verdict.used, [])
        self.assertEqual(len(verdict.empty), ROWS * COLS)

    def test_peeled_cells_are_found(self):
        peeled = [4, 12, 30, 43]      # 分散在几张排上
        verdict = analyze(self.save(render(peeled=peeled)), self.grid, dpi=DPI)
        self.assertTrue(verdict.ok, verdict)
        self.assertEqual(sorted(verdict.used), sorted(peeled))
        self.assertEqual(verdict.unsure, [])

    def test_whole_row_peeled(self):
        peeled = list(range(40, 45))
        verdict = analyze(self.save(render(peeled=peeled)), self.grid, dpi=DPI)
        self.assertEqual(sorted(verdict.used), peeled)

    def test_half_peeled_cell_is_unsure(self):
        verdict = analyze(self.save(render(partial=[7])), self.grid, dpi=DPI)
        self.assertIn(7, verdict.unsure)
        self.assertNotIn(7, verdict.used)
        cell = verdict.cells[7 // COLS][7 % COLS]
        self.assertGreater(cell.peeled, partial_scan.EMPTY_FRACTION)
        self.assertLess(cell.peeled, partial_scan.USED_FRACTION)

    def test_scissor_mark_is_unsure(self):
        verdict = analyze(self.save(render(damaged=[38])), self.grid, dpi=DPI)
        self.assertIn(38, verdict.unsure)
        self.assertTrue(verdict.cells[38 // COLS][38 % COLS].reason)

    def test_mixed_sheet(self):
        verdict = analyze(self.save(render(peeled=[0, 1, 2], partial=[20], damaged=[33])),
                          self.grid, dpi=DPI)
        self.assertEqual(sorted(verdict.used), [0, 1, 2])
        self.assertIn(20, verdict.unsure)
        self.assertIn(33, verdict.unsure)
        self.assertEqual(len(verdict.empty), ROWS * COLS - 5)

    def test_describe_mentions_counts(self):
        verdict = analyze(self.save(render(peeled=[0])), self.grid, dpi=DPI)
        text = describe(verdict)
        self.assertIn("已用", text)

    def test_printed_cells_are_used_even_if_rotated(self):
        """打印过的格算「已用」——歪不歪、转不转都靠墨迹占比，不看方向。"""
        printed = list(range(0, 10))     # 两整排打印过
        verdict = analyze(self.save(render(printed=printed)), self.grid, dpi=DPI)
        self.assertEqual(sorted(verdict.used), printed)
        self.assertEqual(verdict.unsure, [])

    def test_printed_and_peeled_can_coexist(self):
        verdict = analyze(self.save(render(printed=[0, 1, 2], peeled=[40, 41])),
                          self.grid, dpi=DPI)
        self.assertEqual(sorted(verdict.used), [0, 1, 2, 40, 41])

    def test_water_damage_still_recognises_peeled_cells(self):
        """纸被泡过也要认得出「撕掉」：真撕掉是蓝偏 +11~+20，水渍是负的。"""
        stained = [20, 23, 24, 25, 26, 27, 28]
        verdict = analyze(self.save(render(stained=stained, peeled=[40])),
                          self.grid, dpi=DPI)
        self.assertTrue(any(w.startswith("sheet:") for w in verdict.warnings), verdict.warnings)
        self.assertIn(40, verdict.used)                  # 撕掉照样认出来
        self.assertLessEqual(verdict.confidence, 0.6)    # 但整体置信度封顶

    def test_water_stain_cell_is_unsure(self):
        """水渍格（偏暗、蓝偏为负）不能算空，也不能算已用。"""
        verdict = analyze(self.save(render(stained=[7])), self.grid, dpi=DPI)
        self.assertIn(7, verdict.unsure)
        self.assertNotIn(7, verdict.used)
        self.assertTrue(verdict.cells[7 // COLS][7 % COLS].reason)


@needs_numpy
class EdgeCaseTests(Case):
    def test_missing_file_is_low_confidence(self):
        verdict = analyze(os.path.join(self.dir, "nope.png"), self.grid)
        self.assertFalse(verdict.ok)
        self.assertTrue(verdict.warnings[0].startswith("fail:"))

    def test_tiny_image_is_rejected(self):
        img = Image.new("RGB", (80, 80), PAPER)
        verdict = analyze(self.save(img), self.grid)
        self.assertFalse(verdict.ok)

    def test_bad_grid_is_rejected(self):
        bad = GridSpec(page_w=0.0, page_h=297.0, cols=0, rows=9, cell_w=40.0, cell_h=30.0,
                       pitch_x=41.5, pitch_y=32.0, margin_top=6.0, margin_left=None, inset=2.0)
        verdict = analyze(self.save(render()), bad)
        self.assertFalse(verdict.ok)

    def test_dpi_is_optional(self):
        path = self.save(render(peeled=[9]))
        with_dpi = analyze(path, self.grid, dpi=DPI)
        without = analyze(path, self.grid)
        self.assertEqual(with_dpi.used, without.used)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""纸面方向标记：横向箭头（只印正式版，留白不够就不印）。"""
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from pypdf import PdfReader

from ulpp.builder import ORIENT_MIN_H_MM, build_pdf, orient_mark_ops
from ulpp.templates import GridSpec


def grid_with_top(margin_top: float) -> GridSpec:
    """一张上留白可调的格阵（其它参数照 45 格预设）。"""
    return GridSpec(page_w=210.0, page_h=297.0, cols=5, rows=9,
                    cell_w=40.0, cell_h=30.0, pitch_x=41.5, pitch_y=32.0,
                    margin_top=margin_top, margin_left=None, inset=2.0)


class OrientMarkOpsTests(unittest.TestCase):
    def test_room_enough_draws_ops(self):
        ops = orient_mark_ops(grid_with_top(6.0))
        self.assertGreater(len(ops), 6)
        self.assertEqual(ops[0][1], b"q")          # 先压栈、再设填充色
        self.assertEqual(ops[1][1], b"g")
        self.assertEqual(ops[-1][1], b"Q")
        self.assertIn(b"f", [op[1] for op in ops])  # 有填充

    def test_no_room_draws_nothing(self):
        # 上留白 4.6mm：减去 0.5 余量与 4mm 可印边距，只剩 0.1mm → 不放
        self.assertEqual(orient_mark_ops(grid_with_top(4.6)), [])

    def test_height_grows_but_caps(self):
        small = orient_mark_ops(grid_with_top(6.0))
        big = orient_mark_ops(grid_with_top(20.0))
        self.assertGreater(len(small), 0)
        self.assertGreater(len(big), 0)
        # 高度封顶在 2.4mm，所以留白再大也是同一套指令结构
        self.assertEqual(len(small), len(big))

    def test_arrow_points_left(self):
        """尖端在左：第一条 m 的 x 必须是所有坐标里最小的 x。"""
        ops = orient_mark_ops(grid_with_top(6.0))
        xs = [float(op[0][0]) for op in ops
              if op[1] == b"m" or op[1] == b"l"]
        self.assertTrue(xs, ops)
        self.assertAlmostEqual(xs[0], min(xs), places=3)


class OrientMarkInPdfTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_orient_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: [p.unlink() for p in self.dir.glob("*")])

    def _content(self, name: str, **kw) -> bytes:
        path = self.dir / name
        build_pdf([], kw.pop("grid", grid_with_top(6.0)), str(path), **kw)
        return PdfReader(str(path)).pages[0].get_contents().get_data()

    def test_production_has_mark(self):
        with_mark = self._content("on.pdf")
        without = self._content("off.pdf", orient=False)
        self.assertGreater(len(with_mark), len(without))

    def test_proof_stays_clean(self):
        """参考版是拿来对位的，不印方向标记。"""
        proof = self._content("proof.pdf", knife_lines=True)
        proof_off = self._content("proof_off.pdf", knife_lines=True, orient=False)
        self.assertEqual(len(proof), len(proof_off))

    def test_no_room_pdf_still_builds(self):
        """放不下标记时不能影响出图：空白页照样能生成、能读。"""
        path = self.dir / "tight.pdf"
        build_pdf([], grid_with_top(4.6), str(path))
        self.assertTrue(path.exists())
        self.assertEqual(len(PdfReader(str(path)).pages), 1)


class OrientFloorTests(unittest.TestCase):
    def test_threshold_is_sane(self):
        self.assertGreaterEqual(ORIENT_MIN_H_MM, 1.0)
        self.assertLess(ORIENT_MIN_H_MM, 2.0)


if __name__ == "__main__":
    unittest.main()

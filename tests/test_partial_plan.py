# -*- coding: utf-8 -*-
"""接着打的内容分配（`ulpp.partial.plan_placements`）：不建窗口就能测。"""

import unittest

from ulpp.partial import plan_placements


class PlanTests(unittest.TestCase):
    def test_fills_free_cells_in_order(self):
        placements, leftover = plan_placements([0, 2, 5, 7], ["a", "b"])
        self.assertEqual(placements, {0: "a", 2: "b"})
        self.assertEqual(leftover, 0)

    def test_truncates_when_too_many_entries(self):
        placements, leftover = plan_placements([1, 3], ["a", "b", "c", "d"])
        self.assertEqual(placements, {1: "a", 3: "b"})
        self.assertEqual(leftover, 2)

    def test_no_free_cells(self):
        placements, leftover = plan_placements([], ["a"])
        self.assertEqual(placements, {})
        self.assertEqual(leftover, 1)

    def test_no_entries(self):
        placements, leftover = plan_placements([0, 1], [])
        self.assertEqual(placements, {})
        self.assertEqual(leftover, 0)

    def test_keeps_free_cell_order(self):
        placements, _ = plan_placements([9, 1, 4], ["x", "y", "z"])
        self.assertEqual(list(placements), [9, 1, 4])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

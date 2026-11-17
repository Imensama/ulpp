# -*- coding: utf-8 -*-
"""胶纸模板库（``ulpp.templates``）：存取、去重、翻成 GridSpec。"""

import tempfile
import unittest
import uuid
from pathlib import Path

from ulpp.templates import Template, TemplateStore, adjusted


def sample(**kw):
    base = dict(id="t1", name="我的 45 格", cols=5, rows=9,
                cell_w_mm=37.9, cell_h_mm=30.6,
                pitch_x_mm=41.45, pitch_y_mm=32.13,
                origin_x_mm=0.3, origin_y_mm=5.1,
                confidence=0.64, source="scan:scan_45_adf.pdf")
    base.update(kw)
    return Template(**base)


class TemplateTests(unittest.TestCase):
    def test_to_grid(self):
        g = sample().to_grid()
        self.assertEqual((g.cols, g.rows), (5, 9))
        self.assertAlmostEqual(g.pitch_x, 41.45)
        self.assertAlmostEqual(g.margin_left, 0.3)
        self.assertAlmostEqual(g.margin_top, 5.1)
        self.assertEqual(g.per_sheet, 45)

    def test_dict_roundtrip(self):
        t = sample()
        back = Template.from_dict(t.to_dict())
        self.assertEqual(back, t)

    def test_bad_dict_is_rejected(self):
        for bad in (None, [], {"id": "x"}, {"id": "x", "cols": "no"}):
            self.assertIsNone(Template.from_dict(bad))

    def test_label_is_readable(self):
        self.assertIn("5×9", sample().label())
        self.assertIn("41", sample().label())

    def test_new_id_is_unique(self):
        a, b = Template.new_id("scan"), Template.new_id("scan")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("scan-"))


class AdjustTests(unittest.TestCase):
    def test_from_grid(self):
        from ulpp.presets import by_key
        grid = by_key("45").to_grid()
        t = Template.from_grid(grid, name="预设 45", source="preset:45")
        self.assertEqual((t.cols, t.rows), (grid.cols, grid.rows))
        self.assertAlmostEqual(t.pitch_x_mm, grid.pitch_x)
        self.assertTrue(t.id.startswith("preset"))

    def test_adjust_changes_only_requested(self):
        t = sample()
        new = adjusted(t, pitch_x_mm=42.2, name="改过的")
        self.assertAlmostEqual(new.pitch_x_mm, 42.2)
        self.assertAlmostEqual(new.pitch_y_mm, t.pitch_y_mm)
        self.assertEqual(new.id, t.id)          # 同一张纸：改数不换 id
        self.assertIn("改过的", new.name)

    def test_adjust_nudge(self):
        t = sample()
        new = adjusted(t, dx_mm=1.5, dy_mm=-0.5)
        self.assertAlmostEqual(new.origin_x_mm, t.origin_x_mm + 1.5)
        self.assertAlmostEqual(new.origin_y_mm, t.origin_y_mm - 0.5)

    def test_rejects_impossible(self):
        with self.assertRaises(ValueError):
            adjusted(sample(), cols=0)
        with self.assertRaises(ValueError):
            adjusted(sample(), pitch_x_mm=10.0)   # 节距小于格宽


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.gettempdir()) / ("ulpp_tpl_%s" % uuid.uuid4().hex[:8])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "templates.json"

    def tearDown(self):
        for item in list(self.dir.glob("*")):
            try:
                item.unlink()
            except OSError:
                pass

    def test_save_load(self):
        store = TemplateStore(path=self.path)
        store.upsert(sample())
        again = TemplateStore(path=self.path)
        self.assertEqual(len(again), 1)
        self.assertEqual(again.get("t1").pitch_x_mm, 41.45)

    def test_upsert_replaces(self):
        store = TemplateStore(path=self.path)
        store.upsert(sample())
        store.upsert(sample(name="改名了", pitch_x_mm=42.0))
        self.assertEqual(len(store), 1)
        self.assertEqual(store.get("t1").name, "改名了")
        self.assertAlmostEqual(store.get("t1").pitch_x_mm, 42.0)

    def test_remove(self):
        store = TemplateStore(path=self.path)
        store.upsert(sample())
        self.assertTrue(store.remove("t1"))
        self.assertFalse(store.remove("t1"))
        self.assertEqual(len(TemplateStore(path=self.path)), 0)

    def test_corrupt_file_yields_empty_store(self):
        self.path.write_text("{oops", encoding="utf-8")
        store = TemplateStore(path=self.path)
        self.assertEqual(len(store), 0)
        store.upsert(sample())
        self.assertEqual(len(TemplateStore(path=self.path)), 1)

    def test_bad_entries_are_skipped(self):
        self.path.write_text('[{"id": "ok", "cols": 5, "rows": 9, "cell_w_mm": 40,'
                             ' "cell_h_mm": 30, "pitch_x_mm": 41.45, "pitch_y_mm": 32.13},'
                             ' "junk", {"id": "broken"}]', encoding="utf-8")
        store = TemplateStore(path=self.path)
        self.assertEqual([t.id for t in store.items], ["ok"])

    def test_save_failure_is_soft(self):
        blocker = self.dir / "file.txt"
        blocker.write_text("x", encoding="utf-8")
        store = TemplateStore(path=blocker / "templates.json")
        store.upsert(sample())        # 写不进去也不能抛
        self.assertIsNotNone(store.last_error)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

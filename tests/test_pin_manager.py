"""釘選管理器：toggle / is_pinned / reload / 合併置頂去重。"""

import os
import tempfile
import unittest

from core.pin_manager import PinManager
from tests import _helpers


class TestPinManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_pin_")
        self.db = os.path.join(self.tmp.name, "t.db")
        _helpers.build_real_db(self.db)
        self.data_store = [
            {"path": "D:/img/a.png", "norm_path": os.path.normpath("D:/img/a.png"),
             "filename": "a.png", "mtime": 1, "width": 8, "height": 8},
            {"path": "D:/img/b.png", "norm_path": os.path.normpath("D:/img/b.png"),
             "filename": "b.png", "mtime": 2, "width": 8, "height": 8},
        ]
        self.pm = PinManager(
            db_path=self.db,
            db_conn_factory=lambda: _helpers.connect(self.db),
            data_store_provider=lambda: self.data_store,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_toggle_and_is_pinned(self):
        self.assertFalse(self.pm.is_pinned("D:/img/a.png"))
        self.assertTrue(self.pm.toggle("D:/img/a.png"))   # 變成已釘選
        self.assertTrue(self.pm.is_pinned("D:/img/a.png"))
        self.assertFalse(self.pm.toggle("D:/img/a.png"))  # 取消釘選
        self.assertFalse(self.pm.is_pinned("D:/img/a.png"))

    def test_reload_persists(self):
        self.pm.toggle("D:/img/b.png")
        fresh = PinManager(
            db_path=self.db,
            db_conn_factory=lambda: _helpers.connect(self.db),
            data_store_provider=lambda: self.data_store,
        )
        fresh.reload()
        self.assertTrue(fresh.is_pinned("D:/img/b.png"))

    def test_merge_pinned_to_top_dedupes(self):
        self.pm.toggle("D:/img/b.png")
        # 一般搜尋結果同時含 a 與 b
        results = [
            {"path": "D:/img/a.png", "filename": "a.png", "score": 0.5, "mtime": 1},
            {"path": "D:/img/b.png", "filename": "b.png", "score": 0.3, "mtime": 2},
        ]
        merged = self.pm.merge_pinned_to_top(results)
        # b 被釘選 → 置頂且只出現一次
        self.assertEqual(merged[0]["path"], "D:/img/b.png")
        self.assertTrue(merged[0].get("is_pinned"))
        self.assertEqual(sum(1 for r in merged if r["path"] == "D:/img/b.png"), 1)
        self.assertEqual(len(merged), 2)

    def test_merge_no_pins_returns_original(self):
        results = [{"path": "D:/img/a.png", "filename": "a.png", "score": 0.5}]
        self.assertEqual(self.pm.merge_pinned_to_top(results), results)


if __name__ == "__main__":
    unittest.main()

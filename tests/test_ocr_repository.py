"""OCR 資料存取層：get / upsert 合併 / 刪框 / 改文字（含 ±2px 容忍比對）。"""

import os
import tempfile
import unittest

from core.ocr_repository import OcrRepository
from tests import _helpers


def box(x, y, w=10, h=10):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class TestOcrRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_ocr_")
        self.db = os.path.join(self.tmp.name, "t.db")
        _helpers.build_real_db(self.db)
        conn = _helpers.connect(self.db)
        _helpers.insert_file(conn, "D:/img/x.png")
        conn.commit()
        conn.close()
        self.repo = OcrRepository(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_and_get(self):
        ok = self.repo.upsert("D:/img/x.png",
                              [{"lang": "ch", "box": box(0, 0), "text": "hello", "conf": 0.9}])
        self.assertTrue(ok)
        rows = self.repo.get_by_path("D:/img/x.png")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "hello")
        self.assertEqual(rows[0]["lang"], "ch")

    def test_upsert_merges_same_lang(self):
        self.repo.upsert("D:/img/x.png",
                         [{"lang": "ch", "box": box(0, 0), "text": "a", "conf": 0.9}])
        self.repo.upsert("D:/img/x.png",
                         [{"lang": "ch", "box": box(0, 30), "text": "b", "conf": 0.8}])
        rows = self.repo.get_by_path("D:/img/x.png")
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["text"] for r in rows}, {"a", "b"})

    def test_update_box_text_with_tolerance(self):
        self.repo.upsert("D:/img/x.png",
                         [{"lang": "ch", "box": box(0, 0), "text": "old", "conf": 0.9}])
        # 用偏移 1px 的框（在 ±2px 容忍內）更新文字
        ok = self.repo.update_box_text("D:/img/x.png", "ch", box(1, 1), "new")
        self.assertTrue(ok)
        rows = self.repo.get_by_path("D:/img/x.png")
        self.assertEqual(rows[0]["text"], "new")

    def test_delete_box(self):
        self.repo.upsert("D:/img/x.png", [
            {"lang": "ch", "box": box(0, 0), "text": "keep", "conf": 0.9},
            {"lang": "ch", "box": box(0, 50), "text": "drop", "conf": 0.9},
        ])
        ok = self.repo.delete_box("D:/img/x.png", "ch", box(0, 50))
        self.assertTrue(ok)
        rows = self.repo.get_by_path("D:/img/x.png")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "keep")

    def test_get_missing_returns_empty(self):
        self.assertEqual(self.repo.get_by_path("D:/img/nope.png"), [])

    def test_upsert_unknown_file_fails(self):
        self.assertFalse(self.repo.upsert("D:/img/nope.png",
                         [{"lang": "ch", "box": box(0, 0), "text": "x", "conf": 1.0}]))


if __name__ == "__main__":
    unittest.main()

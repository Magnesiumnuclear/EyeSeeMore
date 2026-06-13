"""搜尋歷史：MRU 排序、去重、上限裁切、刪除、持久化。"""

import json
import os
import tempfile
import unittest

from core.search_history_manager import SearchHistoryManager


class TestSearchHistoryManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_hist_")
        self.path = os.path.join(self.tmp.name, "history.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_is_mru(self):
        h = SearchHistoryManager(self.path)
        h.add("a"); h.add("b"); h.add("c")
        self.assertEqual(h.get_all(), ["c", "b", "a"])

    def test_add_dedup_moves_to_front(self):
        h = SearchHistoryManager(self.path)
        h.add("a"); h.add("b"); h.add("a")
        self.assertEqual(h.get_all(), ["a", "b"])

    def test_cap_at_max_items(self):
        h = SearchHistoryManager(self.path)
        for i in range(SearchHistoryManager.MAX_ITEMS + 5):
            h.add(f"q{i}")
        self.assertEqual(len(h.get_all()), SearchHistoryManager.MAX_ITEMS)

    def test_empty_query_ignored(self):
        h = SearchHistoryManager(self.path)
        h.add("a"); h.add("")
        self.assertEqual(h.get_all(), ["a"])

    def test_delete(self):
        h = SearchHistoryManager(self.path)
        h.add("a"); h.add("b")
        h.delete("a")
        self.assertEqual(h.get_all(), ["b"])

    def test_persistence(self):
        h = SearchHistoryManager(self.path)
        h.add("keep")
        # 另一個實例從同一檔案載入
        h2 = SearchHistoryManager(self.path)
        self.assertIn("keep", h2.get_all())
        # 確認確實寫成 JSON
        with open(self.path, encoding="utf-8") as f:
            self.assertIn("keep", json.load(f))


if __name__ == "__main__":
    unittest.main()

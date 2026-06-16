"""資料夾拆分任務:split_into_folder_tasks 拆分/去重/巢狀歸併,以及
scan_folder_task 逐資料夾掃描的安全性(不誤刪其他資料夾)。"""

import os
import tempfile
import unittest

from tests import _helpers


class TestSplitIntoFolderTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_split_")
        self.db = os.path.join(self.tmp.name, "t.db")
        self.svc = _helpers.build_real_db(self.db, model_name="M")

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_returns_empty(self):
        self.assertEqual(self.svc.split_into_folder_tasks([]), [])

    def test_separate_folders_one_task_each(self):
        cfg = [
            {"path": "D:/a", "enabled_langs": ["ch"]},
            {"path": "D:/b", "enabled_langs": []},
            {"path": "D:/c", "enabled_langs": ["en"]},
        ]
        tasks = self.svc.split_into_folder_tasks(cfg)
        self.assertEqual(len(tasks), 3)
        for t in tasks:
            self.assertEqual(len(t["config"]), 1)
        self.assertEqual({t["path"] for t in tasks},
                         {os.path.normpath(p) for p in ("D:/a", "D:/b", "D:/c")})

    def test_dedup_exact_path(self):
        cfg = [
            {"path": "D:/a", "enabled_langs": ["ch"]},
            {"path": "D:/a", "enabled_langs": ["ch"]},
        ]
        tasks = self.svc.split_into_folder_tasks(cfg)
        self.assertEqual(len(tasks), 1)

    def test_nested_merged_into_parent(self):
        parent = os.path.normpath("D:/photos")
        child = os.path.normpath("D:/photos/2024")
        cfg = [
            {"path": parent, "enabled_langs": ["ch"]},
            {"path": child, "enabled_langs": ["en"]},
        ]
        tasks = self.svc.split_into_folder_tasks(cfg)
        # 只剩父資料夾一個任務,但 config 同時含父與子(保留各自語系)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["path"], parent)
        self.assertEqual(tasks[0]["enabled_langs"], ["ch"])
        self.assertEqual(len(tasks[0]["config"]), 2)
        child_conf = next(c for c in tasks[0]["config"]
                          if os.path.normpath(c["path"]) == child)
        self.assertEqual(child_conf["enabled_langs"], ["en"])

    def test_sibling_not_merged(self):
        # D:/img 與 D:/img-backup 是兄弟,不可因字串前綴而誤併
        cfg = [
            {"path": "D:/img", "enabled_langs": []},
            {"path": "D:/img-backup", "enabled_langs": []},
        ]
        tasks = self.svc.split_into_folder_tasks(cfg)
        self.assertEqual(len(tasks), 2)


class TestScanFolderTaskSafety(unittest.TestCase):
    """逐資料夾掃描不得誤刪其他資料夾的索引記錄。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_split_scan_")
        self.fa = os.path.join(self.tmp.name, "A")
        self.fb = os.path.join(self.tmp.name, "B")
        os.makedirs(self.fa)
        os.makedirs(self.fb)
        # A 有一張新圖在磁碟(尚未入庫);B 有一張圖已入庫且仍在磁碟
        self.a_new = os.path.normpath(os.path.join(self.fa, "a1.png"))
        self.b_old = os.path.normpath(os.path.join(self.fb, "b1.png"))
        _helpers.make_tiny_png(self.a_new)
        _helpers.make_tiny_png(self.b_old)

        self.svc = _helpers.build_real_db(self.db_path(), model_name="M")
        conn = _helpers.connect(self.db_path())
        _helpers.insert_file(conn, self.b_old, folder=self.fb, with_meta=True)
        conn.commit()
        conn.close()

    def db_path(self):
        return os.path.join(self.tmp.name, "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_folder_task_does_not_prune_other_folders(self):
        cfg = [
            {"path": self.fa, "enabled_langs": []},
            {"path": self.fb, "enabled_langs": []},
        ]
        tasks = self.svc.split_into_folder_tasks(cfg)
        task_a = next(t for t in tasks if t["path"] == os.path.normpath(self.fa))

        full, emb_only, ocr_only, deleted, _map = self.svc.scan_folder_task(task_a)

        # A 的新圖被分類為全新
        self.assertIn(self.a_new, {os.path.normpath(p) for p in full})
        # 關鍵:掃 A 不得刪除 B 的記錄
        self.assertEqual(deleted, 0)
        conn = _helpers.connect(self.db_path())
        paths = {os.path.normpath(r[0]) for r in conn.execute("SELECT file_path FROM files")}
        conn.close()
        self.assertIn(self.b_old, paths, "逐資料夾掃描誤刪了其他資料夾的記錄！")

    def test_full_scan_still_prunes(self):
        # 對照:完整 config 走預設 prune_missing=True,仍會清掉磁碟上不存在的記錄
        os.remove(self.b_old)  # B 的圖從磁碟移除
        cfg = [
            {"path": self.fa, "enabled_langs": []},
            {"path": self.fb, "enabled_langs": []},
        ]
        _full, _emb, _ocr, deleted, _map = self.svc.scan_for_new_files(cfg)
        self.assertEqual(deleted, 1)
        conn = _helpers.connect(self.db_path())
        paths = {os.path.normpath(r[0]) for r in conn.execute("SELECT file_path FROM files")}
        conn.close()
        self.assertNotIn(self.b_old, paths)


if __name__ == "__main__":
    unittest.main()

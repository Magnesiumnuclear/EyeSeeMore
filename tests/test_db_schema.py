"""資料庫 schema 回歸測試：建表、二級索引、欄位遷移、級聯刪除。

對應修復：Phase 3-G 在 init_db() 補上 idx_ocr_file_id / idx_files_folder。
這些索引手動測試幾乎不可能察覺缺失，但攸關級聯刪除與查詢效能。
"""

import os
import sqlite3
import tempfile
import unittest

from tests import _helpers


class TestDbSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_db_")
        self.db = os.path.join(self.tmp.name, "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_tables_created(self):
        _helpers.build_real_db(self.db)
        conn = _helpers.connect(self.db)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        for t in ("files", "embeddings", "model_stats", "collections",
                  "collection_items", "pinned", "ocr_results"):
            self.assertIn(t, names, f"init_db 未建立資料表 {t}")

    def test_indexes_created(self):
        _helpers.build_real_db(self.db)
        conn = _helpers.connect(self.db)
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        conn.close()
        self.assertIn("idx_ocr_file_id", idx, "缺少 ocr_results(file_id) 索引")
        self.assertIn("idx_files_folder", idx, "缺少 files(folder_path) 索引")

    def test_no_embeddings_model_index(self):
        # Phase 3-G 結論：embeddings(model_name) 索引有害，刻意不建
        _helpers.build_real_db(self.db)
        conn = _helpers.connect(self.db)
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        conn.close()
        self.assertNotIn("idx_emb_model", idx)

    def test_migration_adds_size_columns(self):
        # 模擬舊資料庫：files 缺 width/height/file_size
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "file_path TEXT UNIQUE, filename TEXT, folder_path TEXT, mtime REAL)")
        conn.execute("INSERT INTO files (file_path, filename, folder_path, mtime) "
                     "VALUES ('X','X','D',1.0)")
        conn.commit()
        conn.close()

        _helpers.build_real_db(self.db)  # init_db 應自動補欄位

        conn = _helpers.connect(self.db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(files)").fetchall()}
        conn.close()
        for c in ("width", "height", "file_size"):
            self.assertIn(c, cols, f"遷移未補上欄位 {c}")

    def test_cascade_delete(self):
        # 刪除 files 應級聯刪除 embeddings 與 ocr_results（依賴 idx_ocr_file_id 才不會慢）
        _helpers.build_real_db(self.db, model_name="M")
        conn = _helpers.connect(self.db)  # foreign_keys = ON
        fid = _helpers.insert_file(conn, "D:/a.png")
        conn.execute("INSERT INTO embeddings (file_id, model_name, embedding) VALUES (?,?,?)",
                     (fid, "M", b"\x00" * 32))
        conn.execute("INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) "
                     "VALUES (?,?,?,?,?)", (fid, "ch", "hi", "[]", 1.0))
        conn.commit()

        conn.execute("DELETE FROM files WHERE id = ?", (fid,))
        conn.commit()

        emb = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        ocr = conn.execute("SELECT COUNT(*) FROM ocr_results").fetchone()[0]
        conn.close()
        self.assertEqual(emb, 0, "刪除 files 未級聯刪除 embeddings")
        self.assertEqual(ocr, 0, "刪除 files 未級聯刪除 ocr_results")


if __name__ == "__main__":
    unittest.main()

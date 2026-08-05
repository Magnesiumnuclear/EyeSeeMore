"""索引掃描分類回歸測試：scan_for_new_files 的三軌道分類與刪除偵測。

這是索引引擎最核心、最容易因改動而悄悄壞掉的邏輯（軌道 A/B/C 分流），
手動測試難以窮舉所有組合。
"""

import os
import tempfile
import unittest

from tests import _helpers


class TestIndexerScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_scan_")
        self.folder = os.path.join(self.tmp.name, "imgs")
        os.makedirs(self.folder)
        self.db = os.path.join(self.tmp.name, "t.db")

        # 磁碟上有 a / b / c 三張圖
        self.pa = os.path.normpath(os.path.join(self.folder, "a.png"))
        self.pb = os.path.normpath(os.path.join(self.folder, "b.png"))
        self.pc = os.path.normpath(os.path.join(self.folder, "c.png"))
        for p in (self.pa, self.pb, self.pc):
            _helpers.make_tiny_png(p)

        self.svc = _helpers.build_real_db(self.db, model_name="M")

        # DB 既有：b（無向量、無 OCR）、c（有向量+OCR）、d（已不在磁碟）
        conn = _helpers.connect(self.db)
        idb = _helpers.insert_file(conn, self.pb, folder=self.folder)
        idc = _helpers.insert_file(conn, self.pc, folder=self.folder)
        _helpers.insert_file(conn, os.path.normpath(os.path.join(self.folder, "d.png")),
                             folder=self.folder)  # 磁碟上沒有 → 應被刪除
        conn.execute("INSERT INTO embeddings (file_id, model_name, embedding) VALUES (?,?,?)",
                     (idc, "M", b"\x00" * 32))
        conn.execute("INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) "
                     "VALUES (?,?,?,?,?)", (idc, "ch", "x", "[]", 1.0))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_three_track_classification(self):
        cfg = [{"path": self.folder, "enabled_langs": ["ch"]}]
        full, emb_only, ocr_only, deleted, _map = self.svc.scan_for_new_files(cfg)

        full = {os.path.normpath(p) for p in full}
        emb_only = {os.path.normpath(p) for p in emb_only}
        ocr_only = {os.path.normpath(p) for p in ocr_only}

        # a：磁碟新圖 → 軌道 A
        self.assertIn(self.pa, full)
        self.assertNotIn(self.pb, full)
        # b：DB 有但缺向量 → 軌道 B；同時缺 ch OCR → 軌道 C
        self.assertIn(self.pb, emb_only)
        self.assertIn(self.pb, ocr_only)
        # c：向量+OCR 齊全 → 不進任何軌道
        self.assertNotIn(self.pc, emb_only)
        self.assertNotIn(self.pc, ocr_only)
        # d：磁碟消失 → 刪除計數 1
        self.assertEqual(deleted, 1)

    def test_deleted_file_removed_from_db(self):
        cfg = [{"path": self.folder, "enabled_langs": ["ch"]}]
        self.svc.scan_for_new_files(cfg)
        conn = _helpers.connect(self.db)
        paths = {os.path.normpath(r[0]) for r in conn.execute("SELECT file_path FROM files")}
        conn.close()
        self.assertNotIn(os.path.normpath(os.path.join(self.folder, "d.png")), paths)
        self.assertIn(self.pb, paths)
        self.assertIn(self.pc, paths)

    def test_no_langs_means_no_ocr_track(self):
        # 資料夾未啟用任何語系 → 不應有 ocr_only
        cfg = [{"path": self.folder, "enabled_langs": []}]
        _full, _emb, ocr_only, _del, _map = self.svc.scan_for_new_files(cfg)
        self.assertEqual(len(ocr_only), 0)

    def test_modified_file_invalidates_derived_data_but_keeps_row(self):
        """原地覆蓋（mtime 變動）→ 衍生資料失效重跑，但 files 列必須保留。

        刻意不刪 files 列：掃描階段就刪，之後索引一旦被取消或失敗，
        圖片會連同 cascade 的 embeddings/ocr_results 一起從圖庫消失。
        """
        # c 原本向量 + OCR 齊全；把 DB 的 mtime 改成遠古時間 = 模擬檔案已被覆蓋
        conn = _helpers.connect(self.db)
        conn.execute("UPDATE files SET mtime = ?, width = 8, height = 8, file_size = 100"
                     " WHERE file_path = ?", (1700000000.0, self.pc))
        conn.commit()
        conn.close()

        cfg = [{"path": self.folder, "enabled_langs": ["ch"]}]
        _full, emb_only, ocr_only, _del, _map = self.svc.scan_for_new_files(cfg)

        emb_only = {os.path.normpath(p) for p in emb_only}
        ocr_only = {os.path.normpath(p) for p in ocr_only}
        # 衍生資料已失效 → 重新落入軌道 B（缺向量）與軌道 C（缺 OCR）
        self.assertIn(self.pc, emb_only)
        self.assertIn(self.pc, ocr_only)

        conn = _helpers.connect(self.db)
        try:
            # files 列必須還在（圖片不可從圖庫消失）
            row = conn.execute("SELECT id, mtime, width, file_size FROM files WHERE file_path = ?",
                               (self.pc,)).fetchone()
            self.assertIsNotNone(row, "變更偵測不應刪除 files 列")
            fid, new_mtime, width, file_size = row
            # 舊的向量與 OCR 應已清除
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM embeddings WHERE file_id = ?", (fid,)).fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM ocr_results WHERE file_id = ?", (fid,)).fetchone()[0], 0)
            # mtime 已同步為磁碟值，下次掃描才不會重複判定為已變更
            self.assertAlmostEqual(new_mtime, os.path.getmtime(self.pc), delta=1.0)
            # 寬高/大小被清成 NULL 後，軌道 D 會在「同一次掃描內」就依實際檔案補回
            self.assertEqual(width, 8, "軌道 D 應在同次掃描重新量到 8x8 的實際尺寸")
            self.assertIsNotNone(file_size)
        finally:
            conn.close()

    def test_unmodified_file_is_not_reprocessed(self):
        """mtime 相符的圖片不可被誤判為已變更（否則每次掃描都無限重索引）。"""
        cfg = [{"path": self.folder, "enabled_langs": ["ch"]}]
        self.svc.scan_for_new_files(cfg)

        # c 的向量與 OCR 在首次掃描後應原封不動
        conn = _helpers.connect(self.db)
        try:
            fid = conn.execute("SELECT id FROM files WHERE file_path = ?", (self.pc,)).fetchone()[0]
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM embeddings WHERE file_id = ?", (fid,)).fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM ocr_results WHERE file_id = ?", (fid,)).fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

"""向量建立(平行前處理 + 管線化)的 run_ai_processing 軌道 A/B 正確性。

用「假 CLIP session」取代真實 ONNX 模型,讓測試確定性、快速、不需大模型;
重點驗證新的平行/管線化管線的接線正確:寫入筆數、L2 正規化、失敗略過、
以及結果與 worker 數無關。
"""

import os
import tempfile
import unittest

import numpy as np

from indexer import IndexerService, NumpyPreprocess
from tests import _helpers


class FakeClipSession:
    """模擬 ONNX image encoder:輸入 (B,3,224,224) → 輸出 (B, dim) 隨機向量。"""
    def __init__(self, dim=8):
        self.dim = dim

    def get_inputs(self):
        class _I:
            name = "image"
        return [_I()]

    def run(self, _outputs, feed):
        x = next(iter(feed.values()))
        b = x.shape[0]
        return [np.random.rand(b, self.dim).astype(np.float32)]


def make_service(db, workers, model="M"):
    return IndexerService(
        db_path=db, model_name=model,
        perf_config={"preprocess_workers": workers,
                     "indexing_batch_size": 4,
                     "db_commit_threshold": 100})


class TestVectorize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_vec_")
        self.db = os.path.join(self.tmp.name, "t.db")
        _helpers.build_real_db(self.db, model_name="M")
        self.pp = NumpyPreprocess(224)
        self.fake = FakeClipSession(dim=8)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_imgs(self, n, prefix="img"):
        paths = []
        for i in range(n):
            p = os.path.normpath(os.path.join(self.tmp.name, f"{prefix}_{i}.png"))
            _helpers.make_tiny_png(p)
            paths.append(p)
        return paths

    def _emb_rows(self):
        conn = _helpers.connect(self.db)
        rows = conn.execute(
            "SELECT e.embedding FROM embeddings e WHERE e.model_name='M'").fetchall()
        conn.close()
        return [r[0] for r in rows]

    def test_track_b_writes_normalized_embeddings(self):
        # 軌道 B:檔案已在 DB、缺向量
        paths = self._make_imgs(10)
        conn = _helpers.connect(self.db)
        for p in paths:
            _helpers.insert_file(conn, p, with_meta=True)
        conn.commit(); conn.close()

        svc = make_service(self.db, workers=4)
        svc.run_ai_processing([], paths, [], {},
                              shared_model=self.fake, shared_preprocess=self.pp)

        blobs = self._emb_rows()
        self.assertEqual(len(blobs), 10, "軌道 B 應為每張圖寫一筆 embedding")
        for b in blobs:
            vec = np.frombuffer(b, dtype=np.float32)
            self.assertEqual(vec.shape[0], 8)
            self.assertAlmostEqual(float(np.linalg.norm(vec)), 1.0, places=4)

    def test_track_a_writes_files_and_embeddings(self):
        # 軌道 A:全新圖(不在 DB),folder_ocr_map 空 → 無 OCR
        paths = self._make_imgs(7, prefix="new")
        svc = make_service(self.db, workers=4)
        svc.run_ai_processing(paths, [], [], {},
                              shared_model=self.fake, shared_preprocess=self.pp)

        conn = _helpers.connect(self.db)
        nfiles = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        nemb = conn.execute("SELECT COUNT(*) FROM embeddings WHERE model_name='M'").fetchone()[0]
        nocr = conn.execute("SELECT COUNT(*) FROM ocr_results").fetchone()[0]
        conn.close()
        self.assertEqual(nfiles, 7, "軌道 A 應寫入 files")
        self.assertEqual(nemb, 7, "軌道 A 應寫入 embeddings")
        self.assertEqual(nocr, 0, "無語系設定不應產生 OCR")

    def test_failed_image_is_skipped(self):
        # 含一張磁碟上不存在的圖 → 平行前處理回傳 None → 略過,其餘成功
        paths = self._make_imgs(5)
        bad = os.path.normpath(os.path.join(self.tmp.name, "missing.png"))
        conn = _helpers.connect(self.db)
        for p in paths + [bad]:
            _helpers.insert_file(conn, p, with_meta=True)
        conn.commit(); conn.close()

        svc = make_service(self.db, workers=4)
        svc.run_ai_processing([], paths + [bad], [], {},
                              shared_model=self.fake, shared_preprocess=self.pp)
        self.assertEqual(len(self._emb_rows()), 5, "壞檔應被略過,其餘正常寫入")

    def test_result_independent_of_worker_count(self):
        # worker 數不應影響結果筆數(管線化僅改變排程,不改變語意)
        for workers in (1, 8):
            with self.subTest(workers=workers):
                db = os.path.join(self.tmp.name, f"w{workers}.db")
                _helpers.build_real_db(db, model_name="M")
                paths = self._make_imgs(6, prefix=f"w{workers}")
                conn = _helpers.connect(db)
                for p in paths:
                    _helpers.insert_file(conn, p, with_meta=True)
                conn.commit(); conn.close()
                svc = make_service(db, workers=workers)
                svc.run_ai_processing([], paths, [], {},
                                      shared_model=self.fake, shared_preprocess=self.pp)
                conn = _helpers.connect(db)
                n = conn.execute("SELECT COUNT(*) FROM embeddings WHERE model_name='M'").fetchone()[0]
                conn.close()
                self.assertEqual(n, 6)


if __name__ == "__main__":
    unittest.main()

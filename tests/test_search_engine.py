"""搜尋引擎：FAISS 索引建立 / HNSW 磁碟快取 / load_data_from_db 的 norm_path。

對應 Phase 3-G：
  • build_faiss_index 對 >10,000 筆走 HNSW 並做磁碟快取（指紋一致才載入）
  • load_data_from_db 為每筆預快取 norm_path（搜尋過濾用，避免每次 normpath）
這些需要 faiss / onnxruntime / PyQt6，tests/__init__ 已先載 onnxruntime 保護 DLL 順序。
"""

import os
import tempfile
import unittest

import numpy as np

from tests import _helpers


def _qt_app():
    from PyQt6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


class FakeConfig:
    """ImageSearchEngine 只用到 db_path 與 get('model_name')。"""
    def __init__(self, db_path, model_name="TESTMODEL"):
        self.db_path = db_path
        self._model = model_name

    def get(self, key, default=None):
        return {"model_name": self._model}.get(key, default)


class TestFaissIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()
        from core.image_search_engine import ImageSearchEngine
        cls.Engine = ImageSearchEngine

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_engine_")
        # 把 FAISS 快取導向暫存，避免污染專案 .cache/faiss
        import core.image_search_engine as ise
        self._orig_faiss_dir = ise.FAISS_CACHE_DIR
        ise.FAISS_CACHE_DIR = os.path.join(self.tmp.name, "faiss")

    def tearDown(self):
        import core.image_search_engine as ise
        ise.FAISS_CACHE_DIR = self._orig_faiss_dir
        self.tmp.cleanup()

    def _engine(self):
        # db 不存在 → 跳過載入，data_store 空，之後手動呼叫 build_faiss_index
        return self.Engine(FakeConfig(os.path.join(self.tmp.name, "nope.db")))

    def test_flat_index_for_small_set(self):
        eng = self._engine()
        emb = np.random.rand(5, 8).astype(np.float32)
        eng.build_faiss_index(emb)
        self.assertIsNotNone(eng.faiss_index)
        self.assertEqual(eng.faiss_index.ntotal, 5)

    def test_hnsw_cache_roundtrip(self):
        eng = self._engine()
        n, d = 10_001, 8   # > 10,000 → 觸發 HNSW + 磁碟快取
        emb = np.random.rand(n, d).astype(np.float32)
        eng.build_faiss_index(emb)
        self.assertEqual(eng.faiss_index.ntotal, n)

        idx_path, meta_path = eng._faiss_cache_paths()
        self.assertTrue(os.path.exists(idx_path), "HNSW 索引未寫入磁碟快取")
        self.assertTrue(os.path.exists(meta_path), "未寫入指紋 meta")

        # 指紋一致 → 命中快取
        cached = eng._load_cached_hnsw(emb)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.ntotal, n)

        # 內容改變 → 指紋不符 → 不得命中（避免索引與資料錯位）
        emb2 = emb.copy()
        emb2[0, 0] += 1.0
        self.assertIsNone(eng._load_cached_hnsw(emb2))


class TestLoadDataNormPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _qt_app()
        from core.image_search_engine import ImageSearchEngine
        cls.Engine = ImageSearchEngine

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_load_")
        self.db = os.path.join(self.tmp.name, "t.db")
        _helpers.build_real_db(self.db, model_name="TESTMODEL")
        # 真實磁碟檔（load_data_from_db 會以 os.scandir 確認檔案存在）
        self.img = os.path.normpath(os.path.join(self.tmp.name, "a.png"))
        _helpers.make_tiny_png(self.img)
        conn = _helpers.connect(self.db)
        fid = _helpers.insert_file(conn, self.img, with_meta=True)
        emb = np.random.rand(8).astype(np.float32).tobytes()
        conn.execute("INSERT INTO embeddings (file_id, model_name, embedding) VALUES (?,?,?)",
                     (fid, "TESTMODEL", emb))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_norm_path_cached_and_index_built(self):
        eng = self.Engine(FakeConfig(self.db))   # __init__ 內會 load_data_from_db
        self.assertEqual(len(eng.data_store), 1)
        item = eng.data_store[0]
        self.assertIn("norm_path", item, "data_store 項目缺少預快取的 norm_path")
        self.assertEqual(item["norm_path"], os.path.normpath(item["path"]))
        # path_map 以 norm_path 為鍵
        self.assertIn(os.path.normpath(self.img), eng.path_map)
        # FAISS 索引已建立
        self.assertIsNotNone(getattr(eng, "faiss_index", None))
        self.assertEqual(eng.faiss_index.ntotal, 1)


if __name__ == "__main__":
    unittest.main()

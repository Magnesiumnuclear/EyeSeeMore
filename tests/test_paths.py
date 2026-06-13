"""路徑常數中心：快取目錄統一（防止 indexer 與 UI 各自計算造成快取分裂）。"""

import os
import unittest


class TestPaths(unittest.TestCase):
    def test_cache_dirs_under_base(self):
        from core import paths
        self.assertEqual(paths.CACHE_DIR, os.path.join(paths.BASE_DIR, ".cache"))
        self.assertEqual(
            paths.THUMBNAIL_CACHE_DIR, os.path.join(paths.BASE_DIR, ".cache", "thumbnails"))
        self.assertEqual(
            paths.FAISS_CACHE_DIR, os.path.join(paths.BASE_DIR, ".cache", "faiss"))

    def test_thumbnail_cache_inside_cache_dir(self):
        from core import paths
        self.assertTrue(paths.THUMBNAIL_CACHE_DIR.startswith(paths.CACHE_DIR))
        self.assertTrue(paths.FAISS_CACHE_DIR.startswith(paths.CACHE_DIR))

    def test_core_constants_exist(self):
        from core import paths
        for name in ("BASE_DIR", "MODELS_DIR", "CONFIG_PATH", "DB_PATH",
                     "CACHE_DIR", "THUMBNAIL_CACHE_DIR", "FAISS_CACHE_DIR"):
            self.assertTrue(hasattr(paths, name), f"core.paths 缺少常數 {name}")


if __name__ == "__main__":
    unittest.main()

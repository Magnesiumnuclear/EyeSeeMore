"""回歸：縮圖快取路徑必須統一（indexer 寫入端 與 UI 讀取端 同一目錄）。

曾發生的 bug：indexer 寫 <root>/.cache/thumbnails，UI 以自身 __file__ 讀
ui/widgets/.cache/thumbnails，導致預產縮圖永遠 miss。此測試防止再度分裂。
"""

import os
import unittest

from tests import _helpers

ROOT = _helpers.PROJECT_ROOT


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestCachePathConsistency(unittest.TestCase):
    def test_both_sides_import_shared_constant(self):
        indexer_src = _read("indexer.py")
        delegate_src = _read(os.path.join("ui", "widgets", "image_delegate.py"))
        self.assertIn("THUMBNAIL_CACHE_DIR", indexer_src,
                      "indexer.py 未使用共用的 THUMBNAIL_CACHE_DIR")
        self.assertIn("THUMBNAIL_CACHE_DIR", delegate_src,
                      "image_delegate.py 未使用共用的 THUMBNAIL_CACHE_DIR")

    def test_no_file_local_cache_dir(self):
        # 不應再以 __file__ 推導出各自的 .cache/thumbnails
        for rel in ("indexer.py", os.path.join("ui", "widgets", "image_delegate.py")):
            src = _read(rel)
            self.assertNotIn('os.path.join(base_dir, ".cache"', src,
                             f"{rel} 仍以區域 base_dir 自行組出 .cache（會造成快取分裂）")

    def test_constant_resolves_under_project_cache(self):
        from core.paths import THUMBNAIL_CACHE_DIR, BASE_DIR
        self.assertEqual(THUMBNAIL_CACHE_DIR,
                         os.path.join(BASE_DIR, ".cache", "thumbnails"))


if __name__ == "__main__":
    unittest.main()

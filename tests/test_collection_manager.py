"""虛擬資料夾管理器：CRUD、icon 冪等遷移、成員寫入與取回。"""

import os
import tempfile
import unittest

from core.collection_manager import CollectionManager
from tests import _helpers


class TestCollectionManager(unittest.TestCase):
    def setUp(self):
        # icon 遷移使用 class-level 旗標，測試前重置以確保可重現
        CollectionManager._icon_column_ensured = False
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_col_")
        self.db = os.path.join(self.tmp.name, "t.db")
        _helpers.build_real_db(self.db)
        self.img = os.path.normpath(os.path.abspath(os.path.join(self.tmp.name, "p.png")))
        self.data_store = [
            {"path": self.img, "filename": "p.png", "mtime": 5, "width": 8, "height": 8},
        ]
        self.mgr = CollectionManager(self.db, self.data_store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_list(self):
        self.assertTrue(self.mgr.add_collection("最愛", "⭐"))
        cols = self.mgr.get_collections()
        self.assertEqual(len(cols), 1)
        cid, name, icon, count = cols[0]
        self.assertEqual(name, "最愛")
        self.assertEqual(icon, "⭐")   # icon 遷移生效
        self.assertEqual(count, 0)

    def test_duplicate_name_rejected(self):
        self.assertTrue(self.mgr.add_collection("dup"))
        self.assertFalse(self.mgr.add_collection("dup"))

    def test_add_members_and_fetch(self):
        self.mgr.add_collection("c", "📁")
        cid = self.mgr.get_collections()[0][0]
        self.assertTrue(self.mgr.add_to_virtual_folder(cid, [self.img]))
        # 數量更新
        self.assertEqual(self.mgr.get_collections()[0][3], 1)
        # 從 data_store 取回完整 metadata
        imgs = self.mgr.get_virtual_folder_images(cid)
        self.assertEqual(len(imgs), 1)
        self.assertEqual(imgs[0]["path"], self.img)

    def test_update_icon(self):
        self.mgr.add_collection("c", "📁")
        cid = self.mgr.get_collections()[0][0]
        self.assertTrue(self.mgr.update_collection_icon(cid, "🔥"))
        self.assertEqual(self.mgr.get_collections()[0][2], "🔥")

    def test_remove_collection_cascades(self):
        self.mgr.add_collection("c", "📁")
        cid = self.mgr.get_collections()[0][0]
        self.mgr.add_to_virtual_folder(cid, [self.img])
        self.assertTrue(self.mgr.remove_collection(cid))
        self.assertEqual(self.mgr.get_collections(), [])
        conn = _helpers.connect(self.db)
        left = conn.execute(
            "SELECT COUNT(*) FROM collection_items WHERE collection_id=?", (cid,)).fetchone()[0]
        conn.close()
        self.assertEqual(left, 0)


if __name__ == "__main__":
    unittest.main()

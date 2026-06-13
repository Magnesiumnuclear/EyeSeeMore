"""設定管理器：深層合併補預設、舊 use_ocr→enabled_langs 遷移、資料夾增刪。

⚠️ ConfigManager 寫死 core.paths 的路徑常數，測試前必須 monkeypatch 到暫存檔，
否則會覆寫專案真實的 config.json。
"""

import json
import os
import tempfile
import unittest

import core.config_manager as cm


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="esm_test_cfg_")
        self.cfg_path = os.path.join(self.tmp.name, "config.json")
        self.db_path = os.path.join(self.tmp.name, "images.db")
        # 隔離：把模組內的路徑常數指向暫存
        self._orig = (cm.CONFIG_PATH, cm.DB_PATH)
        cm.CONFIG_PATH = self.cfg_path
        cm.DB_PATH = self.db_path

    def tearDown(self):
        cm.CONFIG_PATH, cm.DB_PATH = self._orig
        self.tmp.cleanup()

    def _write(self, data):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def test_fresh_creates_defaults(self):
        c = cm.ConfigManager()
        self.assertTrue(os.path.exists(self.cfg_path))
        self.assertEqual(c.get("model_name"), "xlm-roberta-large-ViT-H-14")
        self.assertIn("performance", c.config)

    def test_deep_merge_fills_missing_subkeys(self):
        # 舊設定缺 ui_state 子鍵與 performance 子鍵
        self._write({"model_name": "x", "ui_state": {"view_mode": "large"},
                     "performance": {"indexing_batch_size": 2}})
        c = cm.ConfigManager()
        self.assertIn("sidebar_expanded", c.config["ui_state"])      # 子鍵被補上
        self.assertIn("thumbnail_cache_size", c.config["performance"])
        self.assertEqual(c.config["performance"]["indexing_batch_size"], 2)  # 既有值保留

    def test_legacy_string_folder_migrated(self):
        # 舊格式：source_folders 是字串陣列 + use_ocr 布林
        self._write({"source_folders": ["D:/x"], "use_ocr": True})
        c = cm.ConfigManager()
        folders = c.get("source_folders")
        self.assertIsInstance(folders[0], dict)
        self.assertEqual(folders[0]["path"], "D:/x")
        self.assertEqual(folders[0]["enabled_langs"], ["ch"])

    def test_add_and_remove_folder(self):
        c = cm.ConfigManager()
        self.assertTrue(c.add_source_folder("D:/photos"))
        self.assertFalse(c.add_source_folder("D:/photos"))   # 重複拒絕
        self.assertEqual(len(c.get("source_folders")), 1)
        c.remove_source_folder("D:/photos")
        self.assertEqual(len(c.get("source_folders")), 0)

    def test_toggle_folder_lang(self):
        c = cm.ConfigManager()
        c.add_source_folder("D:/photos")
        c.toggle_folder_lang("D:/photos", "ch")
        langs = c.get("source_folders")[0]["enabled_langs"]
        self.assertIn("ch", langs)
        c.toggle_folder_lang("D:/photos", "ch")
        self.assertNotIn("ch", c.get("source_folders")[0]["enabled_langs"])


if __name__ == "__main__":
    unittest.main()

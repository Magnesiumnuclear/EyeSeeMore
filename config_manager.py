# config_manager.py
import sys
import os
import json
import shutil

class ConfigManager:
    DEFAULT_CONFIG = {
        "source_folders": [],  # 預設為空，讓使用者自己設定
        "db_filename": "images.db",
        "search_limit": 50,
        "theme": "dark",
        "model_name": "xlm-roberta-large-ViT-H-14",
        "pretrained": "frozen_laion5b_s13b_b90k"
    }

    def __init__(self, config_filename="config.json"):
        self.app_root = self._get_app_root()
        self.config_path = os.path.join(self.app_root, config_filename)
        self.config = self._load_config()

    def _get_app_root(self):
        """
        關鍵方法：判斷應用程式的根目錄。
        如果是在 PyInstaller 打包環境 (Frozen)，sys.executable 是 exe 的位置。
        如果是開發環境，__file__ 是腳本的位置。
        """
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包後，exe 所在的資料夾
            return os.path.dirname(sys.executable)
        else:
            # 開發環境，當前腳本所在的資料夾
            return os.path.dirname(os.path.abspath(__file__))

    def _load_config(self):
        """載入設定，如果檔案不存在則建立預設值"""
        if not os.path.exists(self.config_path):
            print(f"[Config] 設定檔不存在，建立預設檔於: {self.config_path}")
            self.save_config(self.DEFAULT_CONFIG)
            return self.DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config] 載入失敗 ({e})，使用預設值")
            return self.DEFAULT_CONFIG.copy()

    def save_config(self, new_config=None):
        """儲存設定"""
        if new_config:
            self.config = new_config
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            print("[Config] 設定已儲存")
        except Exception as e:
            print(f"[Config] 儲存失敗: {e}")

    # --- Public Accessors ---
    
    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    @property
    def db_path(self):
        """取得資料庫的絕對路徑"""
        return os.path.join(self.app_root, self.config.get("db_filename", "images.db"))

    def get_asset_path(self, relative_path):
        """
        取得靜態資源路徑 (如 icon, 預設圖片)。
        注意：PyInstaller 打包時，靜態資源會被解壓到 sys._MEIPASS 暫存目錄。
        """
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(self.app_root, relative_path)
import os
import json

class ConfigManager:
    def __init__(self):
        # 設定應用程式根目錄 (與 main.py 同層)
        self.app_root = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.app_root, "config.json")
        self.db_path = os.path.join(self.app_root, "images.db")
        
        # 預設設定
        self.default_config = {
            "source_folders": [],
            "model_name": "xlm-roberta-large-ViT-H-14",
            "pretrained": "frozen_laion5b_s13b_b90k",
            "search_limit": 50,
            "use_ocr": True
        }
        
        self.config = self.load_config()

    def load_config(self):
        """載入設定檔，若不存在則建立預設值"""
        if not os.path.exists(self.config_path):
            return self.save_config(self.default_config)
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # 合併預設值 (確保新欄位存在)
                for k, v in self.default_config.items():
                    if k not in loaded:
                        loaded[k] = v
                return loaded
        except Exception as e:
            print(f"[Config] Load error: {e}, using defaults.")
            return self.default_config

    def save_config(self, config_data=None):
        """儲存設定檔"""
        if config_data:
            self.config = config_data
            
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return self.config
        except Exception as e:
            print(f"[Config] Save error: {e}")
            return self.config

    def get(self, key):
        """取得設定值"""
        return self.config.get(key, self.default_config.get(key))

    def set(self, key, value):
        """設定並儲存"""
        self.config[key] = value
        self.save_config()

    def add_source_folder(self, folder_path):
        """
        [關鍵修復] 新增資料夾到來源列表
        回傳: True (新增成功), False (已存在)
        """
        folder_path = os.path.normpath(folder_path)
        current_folders = self.config.get("source_folders", [])
        
        # 檢查是否已存在
        if any(os.path.normpath(f) == folder_path for f in current_folders):
            return False
            
        current_folders.append(folder_path)
        self.set("source_folders", current_folders)
        return True
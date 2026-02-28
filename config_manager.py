import os
import json

class ConfigManager:
    def __init__(self):
        self.app_root = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.app_root, "config.json")
        self.db_path = os.path.join(self.app_root, "images.db")
        
        self.default_config = {
            "source_folders": [], # 新格式: [{"path": "C:\\...", "icon": "🐱"}]
            "model_name": "xlm-roberta-large-ViT-H-14",
            "pretrained": "frozen_laion5b_s13b_b90k",
            "search_limit": 50,
            "use_ocr": True,
            "use_gpu_ocr": False,
            "ui_state": {
                "window_width": 1280,
                "window_height": 900,
                "is_maximized": False,
                "sidebar_expanded": True,
                "view_mode": "large"
            } # [新增] 補上預設值，明確界定初始狀態為 CPU
        }
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_path):
            return self.save_config(self.default_config)
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                for k, v in self.default_config.items():
                    if k not in loaded:
                        loaded[k] = v
                
                # [向下相容無痛轉移] 將舊的字串列表轉為新的物件列表，並預設帶上 global 的 use_ocr 屬性
                new_folders = []
                for item in loaded.get("source_folders", []):
                    if isinstance(item, str):
                        new_folders.append({"path": item, "icon": "", "use_ocr": loaded.get("use_ocr", True)})
                    else:
                        # 確保現有物件也補上 use_ocr 屬性
                        if "use_ocr" not in item:
                            item["use_ocr"] = loaded.get("use_ocr", True)
                        new_folders.append(item)
                loaded["source_folders"] = new_folders
                
                return loaded
        except Exception as e:
            print(f"[Config] Load error: {e}")
            return self.default_config

    def save_config(self, config_data=None):
        if config_data: self.config = config_data
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return self.config
        except Exception as e:
            print(f"[Config] Save error: {e}")
            return self.config

    def get(self, key, default=None):
        return self.config.get(key, self.default_config.get(key))

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    def add_source_folder(self, folder_path):
        folder_path = os.path.normpath(folder_path)
        current = self.config.get("source_folders", [])
        if any(os.path.normpath(f["path"]) == folder_path for f in current):
            return False
        # 新增時預設跟隨全域設定
        current.append({"path": folder_path, "icon": "", "use_ocr": self.config.get("use_ocr", True)})
        self.set("source_folders", current)
        return True

    # [新增] 用於動態切換單一資料夾的 OCR 狀態
    def update_folder_ocr(self, folder_path, use_ocr):
        folder_path = os.path.normpath(folder_path)
        for f in self.config.get("source_folders", []):
            if os.path.normpath(f["path"]) == folder_path:
                f["use_ocr"] = use_ocr
                break
        self.save_config()

    def remove_source_folder(self, folder_path):
        folder_path = os.path.normpath(folder_path)
        current = self.config.get("source_folders", [])
        new_list = [f for f in current if os.path.normpath(f["path"]) != folder_path]
        self.set("source_folders", new_list)

    def update_folder_icon(self, folder_path, new_icon):
        folder_path = os.path.normpath(folder_path)
        for f in self.config.get("source_folders", []):
            if os.path.normpath(f["path"]) == folder_path:
                f["icon"] = new_icon
                break
        self.save_config()

    def update_folder_order(self, ordered_paths):
        """根據傳入的路徑陣列，重新排序 config 內的資料夾"""
        current = self.config.get("source_folders", [])
        lookup = {os.path.normpath(f["path"]): f for f in current}
        
        new_list = []
        for path in ordered_paths:
            norm_path = os.path.normpath(path)
            if norm_path in lookup:
                new_list.append(lookup[norm_path])
        self.set("source_folders", new_list)
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
                "view_mode": "large",
                "precise_ocr_highlight": False
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
                
                # [升級] 將舊的 use_ocr (布林值) 無縫轉移為 enabled_langs (陣列)
                new_folders = []
                for item in loaded.get("source_folders", []):
                    if isinstance(item, str):
                        langs = ["ch"] if loaded.get("use_ocr", True) else []
                        new_folders.append({"path": item, "icon": "", "enabled_langs": langs})
                    else:
                        # 處理已是字典，但還沒升級 enabled_langs 的舊資料
                        if "enabled_langs" not in item:
                            # 讀取舊的 use_ocr，如果有開就預設給 "ch"，沒開就給空陣列
                            langs = ["ch"] if item.get("use_ocr", loaded.get("use_ocr", True)) else []
                            item["enabled_langs"] = langs
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
        # [修改] 新增時預設跟隨全域設定，給予 "ch" 標記
        default_langs = ["ch"] if self.config.get("use_ocr", True) else []
        current.append({"path": folder_path, "icon": "", "enabled_langs": default_langs})
        self.set("source_folders", current)
        return True

    # [新增] 用於動態切換單一資料夾的特定語系標記
    def toggle_folder_lang(self, folder_path, lang_code):
        folder_path = os.path.normpath(folder_path)
        for f in self.config.get("source_folders", []):
            if os.path.normpath(f["path"]) == folder_path:
                langs = f.get("enabled_langs", [])
                if lang_code in langs:
                    langs.remove(lang_code) # 已存在則移除
                else:
                    langs.append(lang_code) # 不存在則加入
                
                # 簡單排序一下讓 UI 顯示更整齊：中文 -> 日文 -> 韓文
                sort_order = {"ch": 1, "jp": 2, "kr": 3}
                f["enabled_langs"] = sorted(langs, key=lambda x: sort_order.get(x, 99))
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
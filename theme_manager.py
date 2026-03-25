import os
import json
from PyQt6.QtWidgets import QApplication

class ThemeManager:
    def __init__(self, config_manager):
        self.config = config_manager
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.themes_dir = os.path.join(self.base_dir, "themes")
        self.current_theme_id = self.config.get("ui_state", {}).get("theme", "dark")
        self.current_colors = {}
        self.current_style_logic = "flat"

    def get_available_themes(self):
        """掃描 themes 資料夾，回傳可用的主題清單"""
        themes = []
        if os.path.exists(self.themes_dir):
            for filename in os.listdir(self.themes_dir):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(self.themes_dir, filename), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            meta = data.get("metadata", {})
                            themes.append({
                                "id": meta.get("id", filename[:-5]),
                                "name": meta.get("name", filename[:-5])
                            })
                    except Exception as e:
                        print(f"[ThemeManager] 解析主題 {filename} 失敗: {e}")
        return themes if themes else [{"id": "dark", "name": "深色模式 (Dark)"}]

    def apply_theme(self, app: QApplication, theme_id: str):
        """讀取 JSON 並將變數注入到 base_style.qss 中，套用到全域"""
        self.current_theme_id = theme_id
        
        # 1. 讀取 JSON
        json_path = os.path.join(self.themes_dir, f"{theme_id}.json")
        if not os.path.exists(json_path):
            json_path = os.path.join(self.themes_dir, "dark.json") # 防呆
            
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.current_colors = data.get("colors", {})
                self.current_style_logic = data.get("metadata", {}).get("style_logic", "flat")
        except Exception as e:
            print(f"[ThemeManager] 讀取主題失敗: {e}")
            return

        # 2. 儲存設定
        ui_state = self.config.get("ui_state", {})
        ui_state["theme"] = theme_id
        self.config.set("ui_state", ui_state)

        # 3. 讀取 QSS 樣板並替換變數
        qss_path = os.path.join(self.themes_dir, "base_style.qss")
        if os.path.exists(qss_path):
            try:
                with open(qss_path, 'r', encoding='utf-8') as f:
                    qss_content = f.read()
                    
                # 執行佔位符替換 (例如把 @bg_app 換成 #1e1e1e)
                for key, hex_color in self.current_colors.items():
                    qss_content = qss_content.replace(f"@{key}", hex_color)
                    
                app.setStyleSheet(qss_content)
                print(f"[ThemeManager] 成功套用主題: {theme_id}")
            except Exception as e:
                print(f"[ThemeManager] 套用 QSS 失敗: {e}")
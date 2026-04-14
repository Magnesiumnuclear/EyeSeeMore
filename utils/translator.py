"""
utils/translator.py  –  多國語言翻譯器
=========================================
從 Blur-main.py 抽離的 Translator class。

路徑設計：
  此檔案位於 <project_root>/utils/translator.py
  languages/ 資料夾位於 <project_root>/languages/
  因此 BASE_DIR 需要向上跳兩層：
    dirname(dirname(abspath(__file__))) → <project_root>/
"""

import os
import json


class Translator:
    def __init__(self, lang_code: str):
        self.lang_code = lang_code
        self.translations: dict = {}
        self.load()

    def load(self) -> None:
        # utils/ 的上一層即為專案根目錄
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.join(base_dir, "languages", f"{self.lang_code}.json")

        # 若找不到指定的語言檔，預設退回繁體中文（防呆機制）
        if not os.path.exists(file_path):
            file_path = os.path.join(base_dir, "languages", "zh_TW.json")

        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations = json.load(f)
            except Exception as e:
                print(f"[Translator] 讀取語言檔失敗: {e}")

    def t(self, section: str, key: str, default: str = "") -> str:
        """取得翻譯字串。使用方式：trans.t('settings', 'window_title', '預設值')"""
        return self.translations.get(section, {}).get(key, default)

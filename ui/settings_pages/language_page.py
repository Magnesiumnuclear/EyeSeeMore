"""Language & translation settings page."""
import os
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QComboBox, QGroupBox
)

from core.paths import LANGS_DIR, USER_CONFIG_PATH


class LanguagePage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("language_page", "page_title", "🌍 語言與翻譯 (Language)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        layout.addWidget(sep)

        ui_state = ctx["config"].get("ui_state", {})
        current_lang = ui_state.get("language", "zh_TW")

        group_lang = QGroupBox(trans.t("language_page", "grp_lang_title", "顯示語言 (Display Language)"))
        layout_lang = QVBoxLayout(group_lang)
        layout_lang.setSpacing(10)

        lbl_desc = QLabel(trans.t(
            "language_page", "lbl_desc",
            "請選擇軟體的顯示語言。系統將會從 languages/ 資料夾讀取對應的翻譯檔。\n"
            "(變更語言後，將於下次啟動程式時生效)"
        ))
        lbl_desc.setObjectName("SettingsHint")
        layout_lang.addWidget(lbl_desc)

        self.combo_lang = QComboBox()
        self.combo_lang.setFixedHeight(38)

        self.lang_options = []
        if os.path.exists(LANGS_DIR):
            for filename in os.listdir(LANGS_DIR):
                if filename.endswith(".json"):
                    code = filename[:-5]
                    display_name = code
                    try:
                        with open(os.path.join(LANGS_DIR, filename), "r", encoding="utf-8") as f:
                            data = json.load(f)
                            display_name = data.get("metadata", {}).get("display_name", code)
                    except Exception as e:
                        print(f"解析 {filename} 失敗: {e}")
                    self.lang_options.append({"name": display_name, "code": code})

        if not self.lang_options:
            self.lang_options = [{"name": "系統預設 (zh_TW)", "code": "zh_TW"}]

        for item in self.lang_options:
            self.combo_lang.addItem(item["name"], item["code"])
        for i, item in enumerate(self.lang_options):
            if item["code"] == current_lang:
                self.combo_lang.setCurrentIndex(i)
                break

        self.combo_lang.currentIndexChanged.connect(self._on_language_changed)
        layout_lang.addWidget(self.combo_lang)

        self.lbl_restart_hint = QLabel(trans.t(
            "language_page", "restart_hint",
            "⚠️ 語言已變更！請手動重新啟動程式以套用新語言。"
        ))
        self.lbl_restart_hint.setObjectName("SettingsWarning")
        self.lbl_restart_hint.hide()
        layout_lang.addWidget(self.lbl_restart_hint)

        layout.addWidget(group_lang)
        layout.addStretch(1)

    # ------------------------------------------------------------------ handlers
    def _on_language_changed(self, index: int):
        selected_code = self.combo_lang.itemData(index)
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["language"] = selected_code
        self.ctx["config"].set("ui_state", ui_state)

        # 同步寫入 user_config.json，供 C++ Launcher 下次啟動讀取
        try:
            ucfg = {}
            if os.path.exists(USER_CONFIG_PATH):
                with open(USER_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    ucfg = json.load(f)
            ucfg["language"] = selected_code
            with open(USER_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(ucfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[LanguagePage] 同步 user_config.json 失敗: {e}")

        self.lbl_restart_hint.show()

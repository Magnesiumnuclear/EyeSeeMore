"""Auto tasks (OCR bindings + schedule) settings page.

Cross-page callbacks via ctx["hub"]:
  - hub["refresh_ocr_status"]()  → AIEnginePage.refresh_ocr_status()
  - hub["refresh_folder_list"]() → FoldersPage.refresh_folder_list()
  - hub["navigate_to_ai_ocr_tab"]() → navigate to AI page, OCR sub-tab

Context keys used beyond hub:
  - config, translator, engine, on_refresh_clicked
"""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTabWidget,
    QGroupBox, QScrollArea, QCheckBox, QMenu, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from core.paths import MODELS_DIR


class AutoTasksPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("auto_tasks", "page_title", "🕒 自動任務 (Automated Tasks)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        # Hide separator — same style as AI engine page
        sep.hide()
        layout.addWidget(sep)

        self.auto_tabs = QTabWidget()
        self.auto_tabs.setObjectName("AutoTabs")

        # ── Tab 1: OCR task folder binding ────────────────────────────────
        tab_ocr_tasks = QWidget()
        ocr_tasks_layout = QVBoxLayout(tab_ocr_tasks)
        ocr_tasks_layout.setContentsMargins(20, 20, 20, 20)
        ocr_tasks_layout.setSpacing(15)

        group_ocr = QGroupBox(trans.t(
            "auto_tasks", "grp_ocr_folders",
            "資料夾 OCR 任務綁定 (Folder OCR Tasks)"
        ))
        group_ocr_layout = QVBoxLayout(group_ocr)
        group_ocr_layout.setSpacing(10)

        lbl_desc = QLabel(trans.t(
            "auto_tasks", "lbl_ocr_desc",
            "為資料夾指定背景自動辨識的語系。當系統偵測到新圖片時，"
            "將自動執行對應的文字萃取任務。"
        ))
        lbl_desc.setObjectName("SettingsHint")
        group_ocr_layout.addWidget(lbl_desc)

        self.ocr_scroll = QScrollArea()
        self.ocr_scroll.setWidgetResizable(True)
        self.ocr_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.ocr_scroll.setObjectName("OcrTaskScrollArea")

        self.ocr_tasks_container = QWidget()
        self.ocr_tasks_container.setObjectName("OcrTaskContainer")
        self.ocr_tasks_list_layout = QVBoxLayout(self.ocr_tasks_container)
        self.ocr_tasks_list_layout.setContentsMargins(0, 5, 0, 0)
        self.ocr_tasks_list_layout.setSpacing(5)
        self.ocr_tasks_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.ocr_scroll.setWidget(self.ocr_tasks_container)
        group_ocr_layout.addWidget(self.ocr_scroll)
        ocr_tasks_layout.addWidget(group_ocr)
        self.auto_tabs.addTab(
            tab_ocr_tasks,
            trans.t("auto_tasks", "tab_ocr_mapping", "📝 OCR 任務綁定")
        )

        # ── Tab 2: Schedule / startup behavior ────────────────────────────
        tab_schedule = QWidget()
        schedule_layout = QVBoxLayout(tab_schedule)
        schedule_layout.setContentsMargins(20, 20, 20, 20)
        schedule_layout.setSpacing(15)

        group_startup = QGroupBox(trans.t("auto_tasks", "grp_startup", "啟動行為 (Startup Behavior)"))
        group_startup_layout = QVBoxLayout(group_startup)
        group_startup_layout.setSpacing(10)

        ui_state = ctx["config"].get("ui_state", {})
        self.chk_scan_on_startup = QCheckBox(trans.t(
            "auto_tasks", "chk_scan_startup",
            "啟動軟體時，自動掃描並更新所有資料夾的圖片 (預設開啟)"
        ))
        self.chk_scan_on_startup.setChecked(ui_state.get("auto_scan_on_startup", True))
        self.chk_scan_on_startup.stateChanged.connect(self._on_auto_scan_changed)
        group_startup_layout.addWidget(self.chk_scan_on_startup)
        schedule_layout.addWidget(group_startup)
        schedule_layout.addStretch(1)
        self.auto_tabs.addTab(
            tab_schedule,
            trans.t("auto_tasks", "tab_schedule", "⏳ 排程與控制")
        )

        layout.addWidget(self.auto_tabs, stretch=1)
        self.refresh_ocr_task_list()

    # ------------------------------------------------------------------ refresh
    def refresh_ocr_task_list(self):
        """Rebuild the OCR task folder UI list."""
        while self.ocr_tasks_list_layout.count():
            item = self.ocr_tasks_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
                item.layout().deleteLater()

        config_folders = self.ctx["config"].get("source_folders", [])
        if not config_folders:
            lbl_empty = QLabel("目前沒有任何圖片資料夾，請先前往「資料夾管理」新增。")
            lbl_empty.setObjectName("SettingsWarning")
            self.ocr_tasks_list_layout.addWidget(lbl_empty)
            return

        for f in config_folders:
            path = f.get("path", "")
            icon = f.get("icon", "") or "📁"
            enabled_langs = f.get("enabled_langs", [])

            row_widget = QWidget()
            row_widget.setObjectName("OcrTaskRow")
            row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row_widget.setCursor(Qt.CursorShape.PointingHandCursor)

            row = QHBoxLayout(row_widget)
            row.setContentsMargins(10, 8, 10, 8)

            # Text block (folder name + path)
            text_container = QWidget()
            text_container.setFixedWidth(260)
            text_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_layout = QVBoxLayout(text_container)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(2)

            lbl_title = QLabel(f"{icon}  {os.path.basename(path)}")
            lbl_title.setObjectName("OcrTaskTitle")
            lbl_path = QLabel(path)
            lbl_path.setObjectName("OcrTaskPath")
            text_layout.addWidget(lbl_title)
            text_layout.addWidget(lbl_path)

            # Language tag badges
            tags_layout = QHBoxLayout()
            tags_layout.setSpacing(5)
            tags_layout.setContentsMargins(10, 0, 0, 0)
            for lang in enabled_langs:
                lbl_tag = QLabel(f"[{lang.upper()}]")
                lbl_tag.setObjectName("FolderTagLabel")
                lbl_tag.setProperty("active", "true")
                lbl_tag.setFixedWidth(42)
                lbl_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
                tags_layout.addWidget(lbl_tag)
            tags_layout.addStretch(1)

            row_widget.mouseReleaseEvent = (
                lambda event, p=path: self._show_ocr_task_menu(p, event.globalPosition().toPoint())
            )

            row.addWidget(text_container)
            row.addLayout(tags_layout, stretch=1)
            self.ocr_tasks_list_layout.addWidget(row_widget)

            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setObjectName("SolidLine")
            self.ocr_tasks_list_layout.addWidget(line)

    # ------------------------------------------------------------------ OCR task menu
    def _show_ocr_task_menu(self, path: str, global_pos):
        """Pop-up menu to toggle OCR language assignments for a folder."""
        config_folders = self.ctx["config"].get("source_folders", [])
        current_langs = []
        for f in config_folders:
            if os.path.normpath(f["path"]) == os.path.normpath(path):
                current_langs = f.get("enabled_langs", [])
                break

        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 14px; } QMenu::item { padding: 8px 30px; }")

        langs_map = [("ch", "中文"), ("jp", "日文"), ("kr", "韓文"), ("en", "英文")]
        for lang_code, lang_name in langs_map:
            if lang_code in current_langs:
                action = QAction(f"❌ 取消 {lang_name} OCR 任務", self)
            else:
                action = QAction(f"✅ 指派 {lang_name} OCR 任務", self)
            action.triggered.connect(
                lambda checked, p=path, lc=lang_code, ln=lang_name:
                    self._on_toggle_lang(p, lc, ln)
            )
            menu.addAction(action)

        menu.exec(global_pos)

    def _on_toggle_lang(self, path: str, lang_code: str, lang_name: str):
        import copy
        config_folders = copy.deepcopy(self.ctx["config"].get("source_folders", []))

        target_folder = None
        current_langs = []
        for f in config_folders:
            if os.path.normpath(f.get("path", "")) == os.path.normpath(path):
                target_folder = f
                current_langs = f.get("enabled_langs", [])
                break
        if target_folder is None:
            return

        is_adding = lang_code not in current_langs
        if is_adding:
            models_dir = os.path.join(MODELS_DIR, "ocr")
            rec_path = os.path.join(models_dir, lang_code, "rec.onnx")
            dict_path = os.path.join(models_dir, lang_code, "dict.txt")
            if not (os.path.exists(rec_path) and os.path.exists(dict_path)):
                reply = QMessageBox.question(
                    self, "語言包未安裝",
                    f"尚未安裝【{lang_name}】語言包。\n\n是否前往「AI 引擎設定」進行下載？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    hub = self.ctx.get("hub", {})
                    if "navigate_to_ai_ocr_tab" in hub:
                        hub["navigate_to_ai_ocr_tab"]()
                return

        if is_adding:
            current_langs.append(lang_code)
        else:
            current_langs.remove(lang_code)
        target_folder["enabled_langs"] = current_langs
        self.ctx["config"].set("source_folders", config_folders)

        # Refresh all affected UIs
        hub = self.ctx.get("hub", {})
        self.refresh_ocr_task_list()
        if "refresh_ocr_status" in hub:
            hub["refresh_ocr_status"]()
        if "refresh_folder_list" in hub:
            hub["refresh_folder_list"]()

        if is_adding:
            reply = QMessageBox.question(
                self,
                "任務已指派",
                f"已成功對資料夾指派【{lang_name}】OCR 任務。\n\n"
                f"是否要立即重新掃描此資料夾，為現有的圖片補跑 {lang_name} 的文字辨識？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                on_refresh = self.ctx.get("on_refresh_clicked")
                if on_refresh:
                    on_refresh()

    # ------------------------------------------------------------------ handlers
    def _on_auto_scan_changed(self, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["auto_scan_on_startup"] = is_checked
        self.ctx["config"].set("ui_state", ui_state)

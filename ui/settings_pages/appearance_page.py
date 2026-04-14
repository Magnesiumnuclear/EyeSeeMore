"""Appearance (theme, startup folder, icon size, OCR tag) settings page."""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QComboBox
)
from PyQt6.QtWidgets import QApplication


class AppearancePage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]
        ui_state = ctx["config"].get("ui_state", {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("appearance", "page_title", "🖥️ 介面與顯示 (Appearance)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        layout.addWidget(sep)

        # ── Theme ─────────────────────────────────────────────────────────
        layout.addWidget(QLabel("軟體主題配色 (Theme):"))
        self.combo_theme = QComboBox()
        self.combo_theme.setFixedHeight(38)
        themes = ctx["theme_manager"].get_available_themes()
        for i, theme in enumerate(themes):
            self.combo_theme.addItem(theme["name"], theme["id"])
            if theme["id"] == ctx["theme_manager"].current_theme_id:
                self.combo_theme.setCurrentIndex(i)
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)
        layout.addWidget(self.combo_theme)
        layout.addSpacing(10)

        # ── Default startup folder ────────────────────────────────────────
        layout.addWidget(QLabel(trans.t("appearance", "lbl_startup", "啟動時預設顯示的資料夾：")))
        self.combo_startup = QComboBox()
        self.combo_startup.setFixedHeight(38)
        self.combo_startup.addItem(
            trans.t("appearance", "startup_all", "全部圖片 (All Images)"), "ALL"
        )
        source_folders = ctx["config"].get("source_folders", [])
        for f in source_folders:
            path = f["path"]
            icon = f.get("icon", "") or "📁"
            folder_name = os.path.basename(path)
            self.combo_startup.addItem(f"{icon}  {folder_name}", path)
        startup_path = ui_state.get("default_startup_folder", "ALL")
        idx = self.combo_startup.findData(startup_path)
        if idx >= 0:
            self.combo_startup.setCurrentIndex(idx)
        self.combo_startup.currentIndexChanged.connect(self._on_startup_folder_changed)
        layout.addWidget(self.combo_startup)
        layout.addSpacing(10)

        # ── Icon size ─────────────────────────────────────────────────────
        layout.addWidget(QLabel(trans.t("appearance", "lbl_size", "預設圖片顯示大小：")))
        self.combo_size = QComboBox()
        self.combo_size.setFixedHeight(38)
        self.combo_size.addItems([
            trans.t("appearance", "size_xl", "超大圖示 (Extra Large)"),
            trans.t("appearance", "size_l",  "大圖示 (Large)"),
            trans.t("appearance", "size_m",  "中圖示 (Medium)"),
        ])
        mode_map = {"xl": 0, "large": 1, "medium": 2}
        # ctx["current_view_mode"] is read once at construction
        current_view_mode = ctx.get("current_view_mode", "large")
        self.combo_size.setCurrentIndex(mode_map.get(current_view_mode, 1))
        self.combo_size.currentIndexChanged.connect(self._on_view_mode_changed)
        layout.addWidget(self.combo_size)
        layout.addSpacing(10)

        # ── OCR tag display mode ──────────────────────────────────────────
        layout.addWidget(QLabel(trans.t("appearance", "lbl_tag_mode", "OCR 懸浮標籤顯示方式：")))
        self.combo_tag_mode = QComboBox()
        self.combo_tag_mode.setFixedHeight(38)
        self.combo_tag_mode.addItems([
            trans.t("appearance", "tag_anchored", "選項 A：固定在 OCR 框邊緣 (Anchored) - 推薦"),
            trans.t("appearance", "tag_follow",   "選項 B：跟隨滑鼠游標 (Follow Mouse)"),
        ])
        tag_mode = ui_state.get("ocr_tag_mode", "anchored")
        self.combo_tag_mode.setCurrentIndex(0 if tag_mode == "anchored" else 1)
        self.combo_tag_mode.currentIndexChanged.connect(self._on_tag_mode_changed)
        layout.addWidget(self.combo_tag_mode)

        layout.addStretch(1)

    # ------------------------------------------------------------------ handlers
    def _on_theme_changed(self, index: int):
        theme_id = self.combo_theme.itemData(index)
        app = QApplication.instance()
        self.ctx["theme_manager"].apply_theme(app, theme_id)

    def _on_startup_folder_changed(self, index: int):
        selected_path = self.combo_startup.itemData(index)
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["default_startup_folder"] = selected_path
        self.ctx["config"].set("ui_state", ui_state)

    def _on_view_mode_changed(self, index: int):
        mode_map = {0: "xl", 1: "large", 2: "medium"}
        self.ctx["change_view_mode"](mode_map.get(index, "large"))

    def _on_tag_mode_changed(self, index: int):
        mode = "anchored" if index == 0 else "follow"
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["ocr_tag_mode"] = mode
        self.ctx["config"].set("ui_state", ui_state)

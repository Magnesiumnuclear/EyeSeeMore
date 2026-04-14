"""Folder management settings page.

Context keys:
  config          – ConfigManager
  translator      – Translator
  engine          – ImageSearchEngine | None
  reload_index    – callable: trigger_background_db_reload
  refresh_sidebar – callable: MainWindow.refresh_sidebar
  on_refresh_clicked – callable: MainWindow.on_refresh_clicked

hub keys (cross-page):
  navigate_to_ai_ocr_tab – callable: go to AI page / OCR sub-tab
"""
import os
import copy

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QAbstractItemView, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QInputDialog,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction

from ui.widgets.drag_list import TransparentDragListWidget


class FoldersPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("folders", "page_title", "📁 資料夾管理 (Folders)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        layout.addWidget(sep)

        lbl_hint = QLabel(trans.t(
            "folders", "hint",
            "提示：拖曳列表項目可改變排序。在項目上「點擊右鍵」可設定語系標記與圖示。"
        ))
        lbl_hint.setObjectName("SettingsHint")
        layout.addWidget(lbl_hint)

        self.folder_list = TransparentDragListWidget()
        self.folder_list.setObjectName("FolderSettingsList")
        self.folder_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.folder_list.model().rowsMoved.connect(self._on_folder_order_changed)
        self.folder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._show_folder_context_menu)
        layout.addWidget(self.folder_list)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton(trans.t("folders", "btn_add", "+ 新增資料夾"))
        self.btn_del = QPushButton(trans.t("folders", "btn_remove", "- 移除選取"))
        self.btn_add.setProperty("cssClass", "ActionBtn")
        self.btn_del.setProperty("cssClass", "DangerBtn")
        self.btn_add.clicked.connect(self._on_add_folder)
        self.btn_del.clicked.connect(self._on_remove_folder)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)

        self.refresh_folder_list()

    # ------------------------------------------------------------------ refresh
    def refresh_folder_list(self):
        self.folder_list.clear()
        config_folders = self.ctx["config"].get("source_folders")
        stats = []
        if self.ctx["engine"]:
            stats = self.ctx["engine"].get_folder_stats()
        stats_dict = {os.path.normpath(p): c for p, c in stats}

        for i, f in enumerate(config_folders, 1):
            path = f["path"]
            icon = f.get("icon", "")
            count = stats_dict.get(os.path.normpath(path), 0)
            display_icon = f"[{icon}]" if icon else f"[{i}]"

            item = QListWidgetItem()
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setSizeHint(QSize(0, 48))

            row_widget = QWidget()
            row_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(15, 0, 20, 0)
            row_layout.setSpacing(10)

            lbl_name = QLabel(f"{display_icon}   {os.path.basename(path)}")
            lbl_name.setStyleSheet("font-size: 15px; font-weight: 500; background: transparent;")
            row_layout.addWidget(lbl_name, stretch=1)

            lbl_count = QLabel(f"({count})")
            lbl_count.setFixedWidth(60)
            lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_count.setObjectName("FolderCountLabel")
            row_layout.addWidget(lbl_count)

            self.folder_list.addItem(item)
            self.folder_list.setItemWidget(item, row_widget)

    # ------------------------------------------------------------------ context menu
    def _show_folder_context_menu(self, pos):
        item = self.folder_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 14px; } QMenu::item { padding: 8px 30px; }")
        action_edit = QAction("✏️ 編輯圖示", self)
        action_edit.triggered.connect(self._on_edit_icon)
        menu.addAction(action_edit)
        menu.exec(self.folder_list.mapToGlobal(pos))

    # ------------------------------------------------------------------ handlers
    def _on_folder_order_changed(self):
        ordered_paths = [
            self.folder_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.folder_list.count())
        ]
        self.ctx["config"].update_folder_order(ordered_paths)
        self.ctx["refresh_sidebar"]()

    def _on_add_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            if self.ctx["config"].add_source_folder(folder):
                self.refresh_folder_list()
                self.ctx["refresh_sidebar"]()
                QMessageBox.information(self, "Success", "加入成功！請點擊側邊欄的「⟳」按鈕進行掃描。")
            else:
                QMessageBox.warning(self, "重複", "此資料夾已經存在。")

    def _on_remove_folder(self):
        item = self.folder_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "確認移除",
            f"確定要移除此資料夾的索引嗎？\n\n{path}\n\n"
            "(這只會從軟體中移除，不會刪除電腦裡的實體照片)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.ctx["config"].remove_source_folder(path)
            if self.ctx["engine"]:
                self.ctx["engine"].remove_folder_data(path)
                self.ctx["reload_index"]()
            self.refresh_folder_list()

    def _on_edit_icon(self):
        item = self.folder_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        icon, ok = QInputDialog.getText(
            self, "編輯圖示",
            "請輸入 1 個 Emoji (或最多 2 個英數字)：\n建議按 Win + . 叫出表情符號小鍵盤"
        )
        if ok:
            icon = icon.strip()
            if len(icon) > 4:
                icon = icon[:4]
            self.ctx["config"].update_folder_icon(path, icon)
            self.refresh_folder_list()
            self.ctx["refresh_sidebar"]()

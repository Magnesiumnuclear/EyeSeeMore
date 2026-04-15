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
    QPushButton, QInputDialog, QTabWidget,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction

from ui.widgets.drag_list import TransparentDragListWidget


class FoldersPage(QWidget):
    addCollectionRequested    = pyqtSignal(str, str)  # name, icon
    removeCollectionRequested = pyqtSignal(int)        # collection_id

    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel(trans.t("folders", "page_title", "📁 資料夾管理 (Folders)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        # ── Tab widget ────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("AITabs")  # 共用 AITabs QSS 樣式
        layout.addWidget(self.tabs, stretch=1)

        # ══ Tab 1：實體資料夾 ════════════════════════════════
        tab_physical = QWidget()
        tab_phys_layout = QVBoxLayout(tab_physical)
        tab_phys_layout.setContentsMargins(20, 20, 20, 20)
        tab_phys_layout.setSpacing(15)

        lbl_hint = QLabel(trans.t(
            "folders", "hint",
            "提示：拖曳列表項目可改變排序。在項目上「點擊右鍵」可設定語系標記與圖示。"
        ))
        lbl_hint.setObjectName("SettingsHint")
        lbl_hint.setWordWrap(True)
        tab_phys_layout.addWidget(lbl_hint)

        self.folder_list = TransparentDragListWidget()
        self.folder_list.setObjectName("FolderSettingsList")
        self.folder_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.folder_list.model().rowsMoved.connect(self._on_folder_order_changed)
        self.folder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._show_folder_context_menu)
        tab_phys_layout.addWidget(self.folder_list, stretch=1)

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
        tab_phys_layout.addLayout(btn_layout)

        self.tabs.addTab(tab_physical, trans.t("folders", "tab_physical", "📂 實體資料夾"))
        self.refresh_folder_list()

        # ══ Tab 2：虛擬收藏夾 ════════════════════════════════
        tab_collections = QWidget()
        tab_col_layout = QVBoxLayout(tab_collections)
        tab_col_layout.setContentsMargins(20, 20, 20, 20)
        tab_col_layout.setSpacing(15)

        lbl_col_hint = QLabel(trans.t(
            "folders", "collections_hint",
            "虛擬收藏夾讓您跨磁碟整理圖片，不移動實體檔案。"
        ))
        lbl_col_hint.setObjectName("SettingsHint")
        lbl_col_hint.setWordWrap(True)
        tab_col_layout.addWidget(lbl_col_hint)

        self.collection_list = TransparentDragListWidget()
        self.collection_list.setObjectName("FolderSettingsList")
        self.collection_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.collection_list.setMinimumHeight(80)
        tab_col_layout.addWidget(self.collection_list, stretch=1)

        col_btn_layout = QHBoxLayout()
        self.btn_add_col = QPushButton(trans.t("folders", "btn_add_collection", "+ 新增收藏夾"))
        self.btn_del_col = QPushButton(trans.t("folders", "btn_remove_collection", "- 刪除選取"))
        self.btn_add_col.setProperty("cssClass", "ActionBtn")
        self.btn_del_col.setProperty("cssClass", "DangerBtn")
        self.btn_add_col.clicked.connect(self._on_add_collection)
        self.btn_del_col.clicked.connect(self._on_remove_collection)
        col_btn_layout.addWidget(self.btn_add_col)
        col_btn_layout.addWidget(self.btn_del_col)
        col_btn_layout.addStretch(1)
        tab_col_layout.addLayout(col_btn_layout)

        self.tabs.addTab(tab_collections, trans.t("folders", "tab_collections", "🏷️ 虛擬收藏夾"))
        self.refresh_collections()

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

    # ------------------------------------------------------------------ collections
    def refresh_collections(self):
        """從 engine 重新載入 collections 列表。"""
        self.collection_list.clear()
        engine = self.ctx.get("engine")
        if not engine:
            return
        for col_id, name, icon, count in engine.get_collections():
            item = QListWidgetItem(f"{icon}  {name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, col_id)
            item.setSizeHint(QSize(0, 40))
            self.collection_list.addItem(item)

    def _on_add_collection(self):
        name, ok = QInputDialog.getText(
            self, "新增收藏夾", "收藏夾名稱："
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, "名稱無效", "名稱不能為空。")
            return
        # 本地重複檢查
        existing = [
            self.collection_list.item(i).text().split("  ")[1].strip()
            for i in range(self.collection_list.count())
        ]
        if name in existing:
            QMessageBox.warning(self, "重複名稱", f"「{name}」已存在，請使用其他名稱。")
            return
        self.addCollectionRequested.emit(name, "🏷️")

    def _on_remove_collection(self):
        item = self.collection_list.currentItem()
        if not item:
            return
        col_id = item.data(Qt.ItemDataRole.UserRole)
        name_text = item.text()
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除此收藏夾嗎？\n\n{name_text}\n\n(收藏夾內的圖片不會被刪除)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.removeCollectionRequested.emit(col_id)

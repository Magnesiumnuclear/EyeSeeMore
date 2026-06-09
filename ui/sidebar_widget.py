import os
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QSize, QTimer, QEvent, QRect, QFileInfo
from PyQt6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QScrollArea, QSizePolicy, QFileIconProvider)
from PyQt6.QtGui import QPixmap, QColor, QFont, QPainter, QIcon, QCursor, QFontMetrics


class StatsMenuWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.setFixedWidth(420)
        self.setFixedHeight(500)
        #  1. 主體面板發放身分證
        self.setObjectName("StatsPanel")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)

        title_container = QWidget()
        #  2. 標題區塊發放身分證
        title_container.setObjectName("StatsHeader")
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(15, 10, 15, 10)
        title_lbl = QLabel("Indexed Folders")
        title_lbl.setObjectName("StatsTitle")
        title_layout.addWidget(title_lbl)
        self.main_layout.addWidget(title_container)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("InspectorScrollArea")

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)

        footer_container = QWidget()
        #  3. 底部區塊發放身分證
        footer_container.setObjectName("StatsFooter")
        footer_layout = QHBoxLayout(footer_container)
        footer_layout.setContentsMargins(15, 8, 15, 8)
        self.total_label = QLabel("Total: 0 images")
        self.total_label.setObjectName("StatsTotal")
        footer_layout.addWidget(self.total_label, alignment=Qt.AlignmentFlag.AlignRight)
        self.main_layout.addWidget(footer_container)

    def update_stats(self, stats):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if not stats:
            self.content_layout.addWidget(QLabel("No statistics available.\nRun indexer.py first."))
            self.total_label.setText("Total: 0 images")
            return

        total_images = 0
        fm = QFontMetrics(QFont("Segoe UI", 13))
        max_text_width = 340

        for folder, count in stats:
            total_images += count

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 5, 5, 5)
            row_layout.setSpacing(10)

            display_text = fm.elidedText(folder, Qt.TextElideMode.ElideMiddle, max_text_width)

            lbl_name = QLabel(display_text)
            lbl_name.setToolTip(folder)
            lbl_name.setObjectName("StatsRowName")


            lbl_count = QLabel(f"{count}")
            lbl_count.setObjectName("StatsRowCount")
            lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            row_layout.addWidget(lbl_name, stretch=1)
            row_layout.addWidget(lbl_count)

            #  4. 資料行發放身分證
            row.setObjectName("StatsRow")

            self.content_layout.addWidget(row)

        self.total_label.setText(f"Total: {total_images:,} images")

class FolderHoverMenu(QWidget):
    """
    [最終修正版] 二級點擊選單
    1. 資料夾顯示：數字索引。
    2. [新增] 重新整理按鈕 (環形箭頭)，位於倒數第二格。
    3. 新增按鈕：位於最右邊。
    """
    folder_clicked = pyqtSignal(str)
    refresh_clicked = pyqtSignal() # [新增] 重新整理訊號
    add_clicked = pyqtSignal()

    mouse_entered = pyqtSignal()
    mouse_left = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 主佈局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 內部容器
        self.container_frame = QFrame()
        self.container_frame.setObjectName("MenuContainer")

        # 容器佈局
        self.container_layout = QHBoxLayout(self.container_frame)
        self.container_layout.setContentsMargins(5, 5, 5, 5)
        self.container_layout.setSpacing(5)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.main_layout.addWidget(self.container_frame)



    #  [新增] 覆寫滑鼠進出事件，通知上層 Sidebar
    def enterEvent(self, event):
        self.mouse_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event)

    def update_menu(self, stats, config_folders):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        btn_size = 48

        # 把 SQL stats 轉成字典方便查詢 (路徑 -> 數量)
        stats_dict = {os.path.normpath(p): c for p, c in stats}

        # 1. 建立資料夾按鈕 (依照 config_folders 的自訂排序)
        for i, f_obj in enumerate(config_folders, 1):
            path = f_obj["path"]
            icon = f_obj.get("icon", "")
            count = stats_dict.get(os.path.normpath(path), 0)

            btn = QPushButton()
            btn.setFixedSize(btn_size, btn_size)

            # 判斷要顯示表情符號還是數字
            if icon:
                btn.setText(icon)
                # 強制使用表情符號字體並加大
                btn.setStyleSheet(btn.styleSheet() + " font-size: 20px; font-family: 'Segoe UI Emoji';")
            else:
                btn.setText(str(i))

            # [修正] 使用 HTML 格式強制鎖定 ToolTip 的字型與大小，打破繼承
            btn.setToolTip(f"<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>{path}<br>({count} 張圖片)</div>")
            btn.clicked.connect(lambda checked, p=path: self.on_folder_click(p))
            self.container_layout.addWidget(btn)

        # 2. [新增] 建立「重新整理按鈕」 (倒數第二格)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setObjectName("RefreshBtn")
        self.btn_refresh.setFixedSize(btn_size, btn_size)
        self.btn_refresh.setToolTip("<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>Rescan all folders (Run AI)</div>")
        self.btn_refresh.clicked.connect(self.on_refresh_click)
        self.container_layout.addWidget(self.btn_refresh)

        # 3. 建立「新增按鈕」 (+) (最右邊)
        self.btn_add = QPushButton("+")
        self.btn_add.setObjectName("AddBtn")
        self.btn_add.setFixedSize(btn_size, btn_size)
        self.btn_add.setToolTip("<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>Add new folder source...</div>")
        self.btn_add.clicked.connect(self.on_add_click)
        self.container_layout.addWidget(self.btn_add)

    def on_folder_click(self, path):
        self.folder_clicked.emit(path)
        self.close()

    def on_refresh_click(self):
        self.refresh_clicked.emit()
        self.close()

    def on_add_click(self):
        self.add_clicked.emit()
        self.close()

    def show_at(self, global_pos, height):
        self.container_frame.setFixedHeight(height)

        # 計算寬度
        btn_count = self.container_layout.count()
        btn_width = 48
        spacing = 5
        margin = 5

        if btn_count > 0:
            total_width = (margin * 2) + (btn_count * btn_width) + ((btn_count - 1) * spacing)
            total_width += 4
        else:
            total_width = 100

        self.resize(total_width, height)
        self.container_frame.setFixedSize(total_width, height)

        self.move(global_pos)
        self.show()

# ==========================================
#  可接收拖曳的虛擬資料夾按鈕
# ==========================================
class DroppableFolderButton(QPushButton):
    """繼承自 QPushButton，具備接收 GalleryListView 拖曳的能力。
    當圖片路徑被拖入並釋放時，透過 files_dropped 訊號往外拋出。
    點擊時透過 collection_selected 訊號向外傳遞 'col:{id}' 格式字串。
    """
    files_dropped = pyqtSignal(int, list)     # (collection_id, [file_paths])
    collection_selected = pyqtSignal(str)     # 'col:{collection_id}'

    def __init__(self, collection_id: int, parent=None):
        super().__init__(parent)
        self._collection_id = collection_id
        self.setAcceptDrops(True)
        # 在此直接連接，self._collection_id 是實例屬性，無閉包問題
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, checked=False):
        self.collection_selected.emit(f"col:{self._collection_id}")

    def _set_drag_hover(self, state: bool):
        self.setProperty("drag_hover", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_hover(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_hover(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_hover(False)
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        file_paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if file_paths:
            event.acceptProposedAction()
            self.files_dropped.emit(self._collection_id, file_paths)
        else:
            event.ignore()


class CollectionHoverMenu(QWidget):
    """
    二級懸浮選單：虛擬資料夾 (Collections) — 收合模式專用。
    行為與 FolderHoverMenu 對稱，每個 collection 以 emoji 圖示顯示。
    """
    collection_clicked = pyqtSignal(str)   # 'col:{id}'
    files_dropped = pyqtSignal(int, list)  # (collection_id, [file_paths])

    mouse_entered = pyqtSignal()
    mouse_left = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.container_frame = QFrame()
        self.container_frame.setObjectName("MenuContainer")

        self.container_layout = QHBoxLayout(self.container_frame)
        self.container_layout.setContentsMargins(5, 5, 5, 5)
        self.container_layout.setSpacing(5)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.main_layout.addWidget(self.container_frame)

    def enterEvent(self, event):
        self.mouse_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event)

    def update_menu(self, collections):
        """collections: list of (col_id, name, icon, count)"""
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        btn_size = 48
        for col_id, name, icon, count in collections:
            btn = DroppableFolderButton(col_id)
            btn.setFixedSize(btn_size, btn_size)
            display_icon = icon or str(col_id)
            btn.setText(display_icon)
            btn.setStyleSheet(btn.styleSheet() + " font-size: 20px; font-family: 'Segoe UI Emoji';")
            btn.setToolTip(f"<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>{name}<br>({count} 張圖片)</div>")
            btn.collection_selected.connect(self._on_collection_clicked)
            btn.files_dropped.connect(self.files_dropped)
            self.container_layout.addWidget(btn)

    def _on_collection_clicked(self, path):
        self.collection_clicked.emit(path)
        self.close()

    def show_at(self, global_pos, height):
        self.container_frame.setFixedHeight(height)

        btn_count = self.container_layout.count()
        btn_width = 48
        spacing = 5
        margin = 5

        if btn_count > 0:
            total_width = (margin * 2) + (btn_count * btn_width) + ((btn_count - 1) * spacing)
            total_width += 4
        else:
            total_width = 100

        self.resize(total_width, height)
        self.container_frame.setFixedSize(total_width, height)
        self.move(global_pos)
        self.show()


class SidebarWidget(QFrame):
    folder_selected = pyqtSignal(str)
    toggled = pyqtSignal(bool)
    add_folder_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    files_dropped_to_collection = pyqtSignal(int, list)  # (collection_id, [file_paths])
    folders_accordion_changed = pyqtSignal(bool)      # 實體資料夾手風琴開/關
    collections_accordion_changed = pyqtSignal(bool)  # 虛擬資料夾手風琴開/關

    def __init__(self, parent=None):
        super().__init__(parent)
        self.expanded_width = 240
        self.collapsed_width = 60
        self.is_expanded = True
        self.stats_cache = []
        self._folders_accordion_open = False      # 實體資料夾手風琴展開狀態
        self._collections_accordion_open = False  # 虛擬資料夾手風琴展開狀態

        self.setObjectName("Sidebar")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 1. 漢堡選單
        self.btn_toggle = QPushButton("≡")
        self.btn_toggle.setObjectName("SidebarToggle")
        self.btn_toggle.setFixedSize(60, 60)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet("font-size: 26px; text-align: center;")
        self.btn_toggle.clicked.connect(self.toggle_sidebar)
        self.layout.addWidget(self.btn_toggle)

        # 2. Row 1: All Images (點擊觸發選單)
        self.row1_container = QWidget()
        self.row1_container.setFixedHeight(60)

        self.row1_layout = QHBoxLayout(self.row1_container)
        self.row1_layout.setContentsMargins(0, 0, 0, 0)
        self.row1_layout.setSpacing(0)

        self.btn_all_images = QPushButton()
        # [修正] 移除重複的 setObjectName，只保留有效的 "Row1"
        self.btn_all_images.setObjectName("Row1")
        self.btn_all_images.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_all_images.setFixedHeight(60)
        self.btn_all_images.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.icon_folder = QFileIconProvider().icon(QFileInfo("."))
        self.btn_all_images.setIcon(self.icon_folder)
        self.btn_all_images.setIconSize(QSize(24, 24))

        self.btn_all_images.clicked.connect(self.on_row1_clicked)

        self.btn_all_images.installEventFilter(self)

        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.check_and_hide_menu)

        self.row1_layout.addWidget(self.btn_all_images)
        self.layout.addWidget(self.row1_container)

        # [新建] 實體資料夾分類標題按鈕 (預設隱藏，僅展開模式顯示)
        self.btn_entity_header = QPushButton("  📁 實體資料夾 (Folders)")
        self.btn_entity_header.setObjectName("SidebarSectionHeader")
        self.btn_entity_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_entity_header.setFixedHeight(36)
        self.btn_entity_header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_entity_header.clicked.connect(self._toggle_sub_folders)
        self.btn_entity_header.setVisible(False)  # 收合時隱藏
        self.layout.addWidget(self.btn_entity_header)

        # [新建] 手風琴展開區塊：實體資料夾按鈕列表 (預設隱藏)
        self.sub_folders_container = QFrame()
        self.sub_folders_container.setObjectName("SubFoldersContainer")
        self._sub_folders_layout = QVBoxLayout(self.sub_folders_container)
        self._sub_folders_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_folders_layout.setSpacing(0)
        self.sub_folders_container.setVisible(False)
        self.layout.addWidget(self.sub_folders_container)

        # 3. 初始化二級懸浮選單 (收合模式專用)
        self.hover_menu = FolderHoverMenu(self)
        self.hover_menu.folder_clicked.connect(self.on_sub_folder_clicked)
        self.hover_menu.add_clicked.connect(self.add_folder_requested.emit)

        self.hover_menu.mouse_entered.connect(self.hover_timer.stop)
        self.hover_menu.mouse_left.connect(lambda: self.hover_timer.start(150))

        # [新增] 虛擬資料夾單一圖示按鈕（收合模式專用，對稱於 btn_all_images）
        self.btn_col_icon = QPushButton()
        self.btn_col_icon.setObjectName("Row1")
        self.btn_col_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_col_icon.setFixedHeight(60)
        self.btn_col_icon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_col_icon.hide()
        self.btn_col_icon.installEventFilter(self)
        self.layout.addWidget(self.btn_col_icon)

        self.col_hover_timer = QTimer(self)
        self.col_hover_timer.setSingleShot(True)
        self.col_hover_timer.timeout.connect(self.check_and_hide_col_menu)

        # [新增] 虛擬資料夾懸浮選單（收合模式專用）
        self.col_hover_menu = CollectionHoverMenu(self)
        self.col_hover_menu.collection_clicked.connect(self.folder_selected.emit)
        self.col_hover_menu.files_dropped.connect(self.files_dropped_to_collection)
        self.col_hover_menu.mouse_entered.connect(self.col_hover_timer.stop)
        self.col_hover_menu.mouse_left.connect(lambda: self.col_hover_timer.start(150))

        # ─── Collections 容器（Phase 13）───────────────────────────────
        self._col_separator = QFrame()
        self._col_separator.setFrameShape(QFrame.Shape.HLine)
        self._col_separator.setObjectName("SidebarSeparator")
        self._col_separator.hide()
        self.layout.addWidget(self._col_separator)

        self.btn_col_header = QPushButton("  🏷️ 收資料夾 (Collections)")
        self.btn_col_header.setObjectName("SidebarSectionHeader")
        self.btn_col_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_col_header.setFixedHeight(36)
        self.btn_col_header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_col_header.clicked.connect(self._toggle_col_container)
        self.btn_col_header.setVisible(False)
        self.layout.addWidget(self.btn_col_header)

        self._col_container = QWidget()
        self._col_layout = QVBoxLayout(self._col_container)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.setSpacing(0)
        self._col_container.hide()
        self.layout.addWidget(self._col_container)
        # ────────────────────────────────────────────────────────────────

        # ==========================================
        # [新增] 側邊欄底部的設定入口
        # ==========================================
        self.layout.addStretch(1) # 這個伸縮空間會把下面的設定按鈕「推」到最底端

        self.btn_settings = QPushButton()
        self.btn_settings.setObjectName("SidebarRow1")
        self.btn_settings.setObjectName("Row1") # 共用 Hover 亮條樣式
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setFixedHeight(60)
        self.btn_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_settings.clicked.connect(self.settings_requested.emit)

        # [關鍵修正] 將表情符號畫成固定大小的圖示 (QIcon)，解決縮放問題
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(QFont("Segoe UI Emoji", 18))
        painter.setPen(QColor("#cccccc")) # 讓齒輪顏色與文字一致
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚙️")
        painter.end()

        self.btn_settings.setIcon(QIcon(pixmap))
        self.btn_settings.setIconSize(QSize(24, 24)) # 強制鎖定圖示大小

        self.layout.addWidget(self.btn_settings)

        # [新增] 連接重新整理訊號
        self.hover_menu.refresh_clicked.connect(self.refresh_requested.emit)

        self.update_ui_text()
        self.setFixedWidth(self.expanded_width)

    def update_folders(self, stats, config_folders):
        self.stats_cache = stats
        # [不變] 懸浮選單持續同步更新，收合模式依然可用
        self.hover_menu.update_menu(stats, config_folders)
        # [新增] 同步更新手風琴區塊中的按鈕
        self._rebuild_sub_folders(stats, config_folders)
        total = sum(c for _, c in stats)
        self.all_images_text = f"  All Images ({total})"
        self.update_ui_text()

    def _rebuild_sub_folders(self, stats, config_folders):
        """重建手風琴區塊內的實體資料夾按鈕。"""
        # 清空舊按鈕
        while self._sub_folders_layout.count():
            child = self._sub_folders_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        stats_dict = {os.path.normpath(p): c for p, c in stats}

        for i, f_obj in enumerate(config_folders, 1):
            path = f_obj["path"]
            # [防呆] icon 為空字串或 None 時強制給予預設圖示
            icon = f_obj.get("icon", "") or "📁"
            count = stats_dict.get(os.path.normpath(path), 0)

            btn = QPushButton()
            btn.setObjectName("Row1")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(54)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("expanded", True)  # 手風琴區塊永遠為展開狀態

            # 圖示
            if icon:
                px = QPixmap(28, 28)
                px.fill(Qt.GlobalColor.transparent)
                p = QPainter(px)
                p.setFont(QFont("Segoe UI Emoji", 16))
                p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, icon)
                p.end()
                btn.setIcon(QIcon(px))
                btn.setIconSize(QSize(22, 22))

            display_name = os.path.basename(path) or path
            btn.setText(f"  {display_name}  ({count})")
            btn.setToolTip(f"<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px;'>{path}<br>({count} 張圖片)</div>")
            btn.clicked.connect(lambda checked=False, p=path: self.folder_selected.emit(p))
            self._sub_folders_layout.addWidget(btn)

    def toggle_sidebar(self):
        self.is_expanded = not self.is_expanded
        self.setFixedWidth(self.expanded_width if self.is_expanded else self.collapsed_width)
        self.hide_hover_menu()
        self.hide_col_hover_menu()
        if not self.is_expanded:
            # 收合模式：隱藏所有展開態元件，讓各區塊只剩單一圖示按鈕
            self.btn_entity_header.setVisible(False)
            self.sub_folders_container.setVisible(False)
            self.btn_col_header.setVisible(False)
            self._col_container.setVisible(False)
            self._col_separator.hide()
        else:
            # 展開模式：收起 btn_col_icon，依照記錄的手風琴狀態還原各容器
            self.btn_col_icon.setVisible(False)
            has_folders = self._sub_folders_layout.count() > 0
            self.sub_folders_container.setVisible(has_folders and self._folders_accordion_open)
            has_collections = self._col_layout.count() > 0
            self._col_separator.setVisible(has_collections)
            self._col_container.setVisible(has_collections and self._collections_accordion_open)
        self.update_ui_text()
        self.toggled.emit(self.is_expanded)

    def update_ui_text(self):
        if self.is_expanded:
            self.btn_all_images.setText(getattr(self, 'all_images_text', "  All Images"))
            self.btn_settings.setText("  設定 (Settings)")
            has_folders = self._sub_folders_layout.count() > 0
            self.btn_entity_header.setVisible(has_folders)
            self.btn_col_icon.setVisible(False)
        else:
            self.btn_all_images.setText("")
            self.btn_settings.setText("")
            self.btn_entity_header.setVisible(False)
            # 收合模式：有 collections 才顯示圖示按鈕
            has_collections = self._col_layout.count() > 0
            self.btn_col_icon.setVisible(has_collections)

        # Collections header 隨展開狀態顯示/隱藏
        has_collections = self._col_layout.count() > 0
        self.btn_col_header.setVisible(self.is_expanded and has_collections)

        # 同步更新所有 collection 按鈕的文字與 expanded 屬性
        for i in range(self._col_layout.count()):
            btn = self._col_layout.itemAt(i).widget()
            if btn is None:
                continue
            # 按鈕 toolTip 存了名稱與 count，從 text 反推太脆，改用 userData (property)
            col_data = btn.property("col_data")
            if col_data and self.is_expanded:
                btn.setText(f"  {col_data[0]}  ({col_data[1]})")
            else:
                btn.setText("")
            btn.setProperty("expanded", self.is_expanded)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        #  終極重構：用屬性 (Property) 驅動 QSS，消滅硬寫的 StyleSheet
        # 通知這兩顆按鈕目前的狀態，QSS 檔裡的 [expanded="true"] 就會自動生效！
        for btn in [self.btn_all_images, self.btn_settings]:
            btn.setProperty("expanded", self.is_expanded)
            # 強制 Qt 重新讀取該元件的樣式
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

    def eventFilter(self, obj, event):
        if obj == self.btn_all_images:
            if event.type() == QEvent.Type.Enter:
                if not self.is_expanded:
                    self.hover_timer.stop()
                    self.show_hover_menu()
            elif event.type() == QEvent.Type.Leave:
                if not self.is_expanded:
                    self.hover_timer.start(150)
        elif obj == self.btn_col_icon:
            if event.type() == QEvent.Type.Enter:
                if not self.is_expanded:
                    self.col_hover_timer.stop()
                    self.show_col_hover_menu()
            elif event.type() == QEvent.Type.Leave:
                if not self.is_expanded:
                    self.col_hover_timer.start(150)
        return super().eventFilter(obj, event)

    #  顯示、隱藏與檢查邏輯
    def show_hover_menu(self):
        sidebar_global_pos = self.mapToGlobal(QPoint(0, 0))
        row1_y = self.btn_toggle.height()

        # 往左微調 5px 形成物理重疊，徹底避免滑鼠掉進縫隙
        target_x = sidebar_global_pos.x() + self.width() - 1
        target_y = sidebar_global_pos.y() + row1_y
        self.hover_menu.show_at(QPoint(target_x, target_y), 60)

    def hide_hover_menu(self):
        self.hover_menu.close()

    def show_col_hover_menu(self):
        sidebar_global_pos = self.mapToGlobal(QPoint(0, 0))
        btn_col_y = self.btn_col_icon.mapToParent(QPoint(0, 0)).y()
        target_x = sidebar_global_pos.x() + self.width() - 1
        target_y = sidebar_global_pos.y() + btn_col_y
        self.col_hover_menu.show_at(QPoint(target_x, target_y), 60)

    def hide_col_hover_menu(self):
        self.col_hover_menu.close()

    def check_and_hide_col_menu(self):
        cursor_pos = QCursor.pos()
        if self.col_hover_menu.isVisible() and self.col_hover_menu.geometry().contains(cursor_pos):
            return
        btn_rect = QRect(self.btn_col_icon.mapToGlobal(QPoint(0, 0)), self.btn_col_icon.size())
        if btn_rect.contains(cursor_pos):
            return
        self.hide_col_hover_menu()

    def _refresh_col_icon(self):
        """設定 btn_col_icon 的 emoji 圖示（固定用 🏷️ 代表 Collections）。"""
        px = QPixmap(28, 28)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setFont(QFont("Segoe UI Emoji", 16))
        p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "🏷️")
        p.end()
        self.btn_col_icon.setIcon(QIcon(px))
        self.btn_col_icon.setIconSize(QSize(22, 22))

    def check_and_hide_menu(self):
        """ 150ms 倒數結束後的絕對座標防呆檢查"""
        cursor_pos = QCursor.pos()

        # 1. 如果滑鼠還在選單上
        if self.hover_menu.isVisible() and self.hover_menu.geometry().contains(cursor_pos):
            return

        # 2. 如果滑鼠又回到了主按鈕上
        btn_rect = QRect(self.btn_all_images.mapToGlobal(QPoint(0, 0)), self.btn_all_images.size())
        if btn_rect.contains(cursor_pos):
            return

        # 3. 確定滑鼠離開了戰區，收起選單
        self.hide_hover_menu()

    def _toggle_sub_folders(self):
        """btn_entity_header 點擊事件：切換手風琴區塊的顯示/隱藏，並記錄狀態。"""
        self._folders_accordion_open = not self._folders_accordion_open
        self.sub_folders_container.setVisible(self._folders_accordion_open)
        self.folders_accordion_changed.emit(self._folders_accordion_open)

    def _toggle_col_container(self):
        """btn_col_header 點擊事件：切換 Collections 區塊的顯示/隱藏，並記錄狀態。"""
        self._collections_accordion_open = not self._collections_accordion_open
        self._col_container.setVisible(self._collections_accordion_open)
        self.collections_accordion_changed.emit(self._collections_accordion_open)

    def set_accordion_states(self, folders_open: bool, collections_open: bool):
        """從外部（config 還原）設定手風琴的展開狀態，只在展開模式下更新可見性。"""
        self._folders_accordion_open = folders_open
        self._collections_accordion_open = collections_open
        if self.is_expanded:
            has_folders = self._sub_folders_layout.count() > 0
            self.sub_folders_container.setVisible(has_folders and folders_open)
            has_collections = self._col_layout.count() > 0
            self._col_container.setVisible(has_collections and collections_open)

    def on_row1_clicked(self):
        # 只負責發出 ALL 訊號，手風琴切換由上方的分類標題負責
        self.folder_selected.emit("ALL")
        if not self.is_expanded:
            # 收合模式才需要關閉懸浮選單
            self.hide_hover_menu()

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

    def reload_collections(self, collections: list):
        while self._col_layout.count():
            child = self._col_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not collections:
            self._col_separator.hide()
            self.btn_col_header.hide()
            self._col_container.hide()
            self.btn_col_icon.hide()
            self.col_hover_menu.update_menu([])
            return

        # 根據展開/收合狀態分流：展開模式顯示完整清單，收合模式只顯示圖示按鈕
        self._col_separator.setVisible(self.is_expanded)
        self.btn_col_header.setVisible(self.is_expanded)
        self._col_container.setVisible(self.is_expanded)
        self.btn_col_icon.setVisible(not self.is_expanded)

        # 同步更新收合模式的懸浮選單與圖示按鈕
        self.col_hover_menu.update_menu(collections)
        self._refresh_col_icon()

        for col_id, name, icon, count in collections:
            btn = DroppableFolderButton(col_id)
            btn.setObjectName("Row1")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(54)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("expanded", self.is_expanded)

            # 渲染 emoji icon
            px = QPixmap(28, 28)
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            p.setFont(QFont("Segoe UI Emoji", 16))
            p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, icon)
            p.end()
            btn.setIcon(QIcon(px))
            btn.setIconSize(QSize(22, 22))

            if self.is_expanded:
                btn.setText(f"  {name}  ({count})")
            btn.setProperty("col_data", (name, count))
            btn.collection_selected.connect(self.folder_selected.emit)
            btn.files_dropped.connect(self.files_dropped_to_collection)
            self._col_layout.addWidget(btn)

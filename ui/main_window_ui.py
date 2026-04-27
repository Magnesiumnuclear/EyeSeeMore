# ==========================================
#  main_window_ui.py
#  EyeSeeMore - MainWindow 的純 UI 佈局定義層
#  本檔案只負責「建立元件」與「排版佈局」，不包含任何業務邏輯。
# ==========================================

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QFrame, QListView, QListWidget,
    QAbstractItemView, QSplitter
)
from PyQt6.QtCore import Qt, QSize

from ui.widgets.search_capsule import SearchCapsule


# 從 Blur-main.py 搬入的全域 UI 常數
THUMBNAIL_SIZE = (220, 180)
CARD_SIZE = (240, 290)
MIN_SPACING = 24
WINDOW_TITLE = "EyeSeeMore-(Alpha)"


class Ui_MainWindow:
    """
    純 UI 佈局類別。
    負責在 MainWindow (QMainWindow) 上建立所有視覺元件與排版。
    
    【外部依賴清單】
    呼叫 setup_ui() 之前，MainWindow 實例上必須存在以下屬性：
      - self.config          : ConfigManager 實例 (用於讀取 ui_state)
      - self.search_history  : list (搜尋歷史紀錄)
    
    setup_ui() 執行後，會在 MainWindow 上掛載所有 UI 元件屬性 (如 self.input, self.list_view 等)。
    信號連接 (.connect) 保留在此處，但 slot 函式的具體實作留在 MainWindow 中。
    """

    def setup_ui(self, MainWindow, *, GalleryListView, SearchResultsModel,
                 ImageDelegate, InspectorPanel, SidebarWidget, PreviewOverlay):
        """
        在 MainWindow 上建立完整的 UI 佈局。
        
        :param MainWindow: QMainWindow 的實例 (即 self，在 MainWindow.__init__ 中呼叫)
        :param GalleryListView, SearchResultsModel, ImageDelegate,
               InspectorPanel, SidebarWidget, PreviewOverlay:
               這些自訂元件類別需由呼叫端注入，避免循環引用。
        """

        MainWindow.setWindowTitle(WINDOW_TITLE)

        # ==========================================
        #  中央容器
        # ==========================================
        central = QWidget()
        MainWindow.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ==========================================
        #  左側：側邊欄
        # ==========================================
        MainWindow.sidebar = SidebarWidget()
        # --- 信號連接 (slot 實作在 MainWindow) ---
        MainWindow.sidebar.folder_selected.connect(MainWindow.on_folder_filter)
        MainWindow.sidebar.toggled.connect(MainWindow.on_sidebar_toggled)
        MainWindow.sidebar.add_folder_requested.connect(MainWindow.on_add_folder_clicked)
        MainWindow.sidebar.refresh_requested.connect(MainWindow.on_refresh_clicked)
        MainWindow.sidebar.settings_requested.connect(MainWindow.show_settings_dialog)
        MainWindow.sidebar.files_dropped_to_collection.connect(MainWindow._on_files_dropped_to_collection)
        main_layout.addWidget(MainWindow.sidebar)

        # ==========================================
        #  右側容器
        # ==========================================
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # ==========================================
        #  Top Bar：極簡搜尋樞紐
        # ==========================================
        top_bar = QFrame()
        top_bar.setFixedHeight(60)
        top_bar.setObjectName("TopBar")
        header_layout = QHBoxLayout(top_bar)
        header_layout.setContentsMargins(20, 0, 20, 0)
        header_layout.setSpacing(15)

        # --- 導覽按鈕 ---
        MainWindow.btn_back = QPushButton("←")
        MainWindow.btn_back.setObjectName("NavBtn")
        MainWindow.btn_back.setFixedSize(32, 32)
        MainWindow.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        MainWindow.btn_back.clicked.connect(MainWindow.navigate_back)
        MainWindow.btn_back.setEnabled(False)

        MainWindow.btn_forward = QPushButton("→")
        MainWindow.btn_forward.setObjectName("NavBtn")
        MainWindow.btn_forward.setFixedSize(32, 32)
        MainWindow.btn_forward.setCursor(Qt.CursorShape.PointingHandCursor)
        MainWindow.btn_forward.clicked.connect(MainWindow.navigate_forward)
        MainWindow.btn_forward.setEnabled(False)

        header_layout.addWidget(MainWindow.btn_back)
        header_layout.addWidget(MainWindow.btn_forward)

        # --- 麵包屑標題 ---
        MainWindow.breadcrumb_lbl = QLabel("Gallery")
        MainWindow.breadcrumb_lbl.setObjectName("Breadcrumb")
        header_layout.addWidget(MainWindow.breadcrumb_lbl)
        header_layout.addStretch(1)

        # --- 膠囊式搜尋樞紐 (SearchCapsule 組件) ---
        MainWindow.search_capsule = SearchCapsule()
        # 向後相容別名：讓現有程式碼中 self.input / self.btn_ocr_toggle 繼續運作
        MainWindow.input = MainWindow.search_capsule.input
        MainWindow.btn_ocr_toggle = MainWindow.search_capsule.btn_ocr_toggle

        header_layout.addWidget(MainWindow.search_capsule)
        header_layout.addStretch(1)

        # --- 右側動作列 ---
        right_actions_layout = QHBoxLayout()
        right_actions_layout.setSpacing(15)

        MainWindow.status = QLabel("Initializing...")
        MainWindow.status.setObjectName("StatusBarText")
        right_actions_layout.addWidget(MainWindow.status, alignment=Qt.AlignmentFlag.AlignVCenter)

        MainWindow.btn_toggle_inspector = QPushButton("📊")
        MainWindow.btn_toggle_inspector.setCheckable(True)
        MainWindow.btn_toggle_inspector.setFixedSize(36, 36)
        MainWindow.btn_toggle_inspector.setCursor(Qt.CursorShape.PointingHandCursor)
        MainWindow.btn_toggle_inspector.setObjectName("InspectorToggle")
        MainWindow.btn_toggle_inspector.clicked.connect(MainWindow.toggle_inspector)
        right_actions_layout.addWidget(MainWindow.btn_toggle_inspector)

        header_layout.addLayout(right_actions_layout)
        right_layout.addWidget(top_bar)

        # --- 進度條 ---
        MainWindow.progress = QProgressBar()
        MainWindow.progress.hide()
        right_layout.addWidget(MainWindow.progress)

        # ==========================================
        #  主內容：QSplitter (畫廊 + Inspector)
        # ==========================================
        MainWindow.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        MainWindow.main_splitter.setObjectName("MainSplitter")

        # --- 畫廊 (GalleryListView) ---
        MainWindow.list_view = GalleryListView()
        MainWindow.list_view.setViewMode(QListView.ViewMode.IconMode)
        MainWindow.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        MainWindow.list_view.setUniformItemSizes(True)
        MainWindow.list_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        MainWindow.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        MainWindow.list_view.setSpacing(MIN_SPACING)
        MainWindow.list_view.setMouseTracking(True)
        MainWindow.list_view.setObjectName("GalleryList")

        MainWindow.current_card_size = QSize(CARD_SIZE[0], CARD_SIZE[1])
        MainWindow.current_thumb_size = QSize(CARD_SIZE[0], THUMBNAIL_SIZE[1])
        MainWindow.current_view_mode = "large"

        MainWindow.model = SearchResultsModel(MainWindow.current_thumb_size)
        MainWindow.delegate = ImageDelegate(MainWindow.current_card_size, THUMBNAIL_SIZE[1], MainWindow)

        MainWindow.list_view.setModel(MainWindow.model)
        MainWindow.list_view.setItemDelegate(MainWindow.delegate)

        # --- InspectorPanel (右側分頁式面板) ---
        MainWindow.inspector_panel = InspectorPanel(MainWindow)
        # --- 信號連接 (slot 實作在 MainWindow) ---
        MainWindow.inspector_panel.sort_changed.connect(MainWindow.apply_gallery_sort)
        MainWindow.inspector_panel.time_filter_applied.connect(MainWindow.apply_time_filter_to_gallery)
        MainWindow.inspector_panel.time_search_requested.connect(MainWindow.search_by_time_range)
        MainWindow.inspector_panel.time_filter_cleared.connect(MainWindow.clear_time_filter)
        MainWindow.inspector_panel.aspect_changed.connect(MainWindow.apply_current_filters_and_show)
        MainWindow.inspector_panel.weights_changed.connect(MainWindow.on_weights_changed)

        # --- 組裝 Splitter ---
        MainWindow.main_splitter.addWidget(MainWindow.list_view)
        MainWindow.main_splitter.addWidget(MainWindow.inspector_panel)
        MainWindow.main_splitter.setStretchFactor(0, 1)  # 畫廊彈性佔據剩餘空間
        MainWindow.main_splitter.setStretchFactor(1, 0)  # 面板保持固定寬度
        right_layout.addWidget(MainWindow.main_splitter)

        # ==========================================
        #  狀態載入與事件綁定
        # ==========================================
        ui_state = MainWindow.config.get("ui_state", {})

        saved_mode = ui_state.get("view_mode", "large")
        if saved_mode != "large":
            MainWindow.change_view_mode(saved_mode)

        saved_expanded = ui_state.get("sidebar_expanded", True)
        if not saved_expanded:
            MainWindow.sidebar.toggle_sidebar()

        MainWindow.resize(ui_state.get("window_width", 1280), ui_state.get("window_height", 900))
        if ui_state.get("is_maximized", False):
            MainWindow.showMaximized()

        # --- ListView 事件綁定 ---
        MainWindow.list_view.clicked.connect(MainWindow.on_item_clicked)
        MainWindow.list_view.doubleClicked.connect(MainWindow.on_item_double_clicked)
        MainWindow.list_view.selectionModel().currentChanged.connect(MainWindow.on_selection_changed)
        MainWindow.list_view.customContextMenuRequested.connect(MainWindow.show_context_menu)
        MainWindow.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        main_layout.addWidget(right_container)

        # ==========================================
        #  浮動元件
        # ==========================================
        # 歷史清單由 SearchCapsule 內部管理，這裡建立別名供外部相容
        MainWindow.history_list = MainWindow.search_capsule.get_history_list_widget()

        MainWindow.preview_overlay = PreviewOverlay(MainWindow)

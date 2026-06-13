import sys

# ── 跨進程指令官：Jump List 次要實例的即時退出块（必須在任何大影 import 之前）───────
# Windows Shell 在跨跳躍清單項目被點擊時會以
#   python.exe "Blur-main.py" --esm-cmd=pause
# 啟動次要實例。這小段不引入任何內容，幾幾順時退出。
if __name__ == "__main__":
    _esm = next((a for a in sys.argv[1:] if a.startswith('--esm-cmd=')), None)
    if _esm is not None:
        import ctypes as _c
        _cmd = _esm.split('=', 1)[1].strip()
        _TITLE  = "EyeSeeMore-(Alpha)"
        _MAGIC  = 0x45534D43
        _WM_CD  = 0x004A
        _u32    = _c.windll.user32
        _u32.FindWindowW.restype  = _c.c_void_p
        _u32.FindWindowW.argtypes = [_c.c_wchar_p, _c.c_wchar_p]
        _u32.SendMessageW.argtypes = [_c.c_void_p, _c.c_uint, _c.c_size_t, _c.c_ssize_t]
        _u32.SendMessageW.restype  = _c.c_ssize_t
        _hwnd = _u32.FindWindowW(None, _TITLE)
        if _hwnd:
            class _CDS(_c.Structure):
                _fields_ = [('dwData', _c.c_size_t),
                             ('cbData', _c.c_ulong),
                             ('lpData', _c.c_void_p)]
            _d   = _cmd.encode('utf-16-le')
            _buf = _c.create_string_buffer(_d)
            _cds = _CDS(_MAGIC, len(_d), _c.cast(_buf, _c.c_void_p).value)
            _u32.SendMessageW(_hwnd, _WM_CD, 0, _c.addressof(_cds))
        sys.exit(0)
# ─────────────────────────────────────────────────────────────────────────

import os
import time
import threading
import re

# ⚠️ [DLL 載入順序保護] onnxruntime 必須在任何 PyQt6 模組之前 import，
# 否則其 pybind DLL 初始化會失敗（實測 PyQt6 → onnxruntime 必定
# ImportError: DLL load failed）。下方 core.* 模組會拉入 PyQt6，
# 所以這行必須保持在所有 core/ui import 之前，不可移除或下移。
import onnxruntime  # noqa: F401

# [Perf Phase 3-G] 頂層只保留真正用到的輕量模組。
# 曾經在這裡的 transformers（冷 import 實測 28 秒）、faiss、indexer
# （連帶 cv2 / onnx_ocr / shapely）在本檔皆未使用或已延後：
#   - transformers → ModelProvider._load_models_impl() 內 lazy import
#   - faiss / ImageSearchEngine → load_engine()（背景執行緒）內 import
#   - IndexerService → core/workers.py 的 IndexerWorker.run() 內 lazy 建立
# （faiss / cv2 / transformers / shapely 實測在 PyQt6 之後載入皆安全）

from core.search_orchestrator import SearchOrchestrator
from core.image_action_manager import ImageActionManager
from core.pin_manager import PinManager
from core.ocr_repository import OcrRepository
from core.collection_manager import CollectionManager
from core.search_history_manager import SearchHistoryManager
from core.eta_progress_controller import EtaProgressController
from core.indexing_lifecycle import IndexingLifecycleHandler
from core.model_provider import ModelProvider
from ui.gallery_view_controller import GalleryViewController
from ui.window_state_manager import WindowStateManager
from utils.translator import Translator

# [New] 引入設定管理器
from core.config_manager import ConfigManager
from ui.theme_manager import ThemeManager

# [修正] 確保所有 PyQt6 模組都已引入
from PyQt6.QtGui import QActionGroup
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox,
                             QGraphicsDropShadowEffect, QCheckBox, QInputDialog, QDialog,
                             QStyledItemDelegate, QStyle, QFileIconProvider, QAbstractItemView, QListView,
                             QRadioButton, QGroupBox, QStackedWidget, QTabWidget, QGridLayout, QSplitter
                             , QSlider)
from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QPoint, QPointF, QRect, QRectF, QSize, QEvent,
                          QFileInfo, QTimer, QAbstractListModel, QRunnable, QThreadPool, QObject, QModelIndex, QByteArray,
                          QAbstractNativeEventFilter, QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import (QPixmap, QImage, QCursor, QAction, QColor, QFont, QKeySequence, 
                         QShortcut, QFontMetrics, QPainter, QBrush, QPen, QIcon, QPainterPath, QPolygon, QImageReader
                         , QDrag, QRegion)


# ── 已提取的模組 import ──────────────────────────────────────────────
from core.taskbar_controller import (
    TaskbarController, TBPF_NOPROGRESS, TBPF_INDETERMINATE,
    TBPF_NORMAL, TBPF_ERROR, TBPF_PAUSED)
import ctypes
from core.win_event_filters import (
    WinMaxHoverFilter, WinScanCtrlFilter,
    _set_window_aumi, _install_sys_menu, _register_jump_list)
from core.workers import (
    WorkerSignals, PreviewSignals,
    IndexerWorker, SearchWorker, OCRImportWorker, ONNXExportWorker)
from ui.inspector_panel import InspectorPanel
from ui.gallery_model import SearchResultsModel, GalleryListView
from ui.preview_overlay import PreviewOverlay
from ui.settings_dialog import SettingsDialog, OnboardingDialog
from ui.sidebar_widget import (
    SidebarWidget, StatsMenuWidget, FolderHoverMenu,
    DroppableFolderButton, CollectionHoverMenu)
from ui.widgets.empty_state import EmptyStateOverlay
from ui.widgets.feature_widgets import (
    TextFeatureWidget, FeatureBucketWidget, ThumbnailSignals, ThumbnailWorker)
from ui.widgets.image_delegate import (
    ImageItem, FunnelCardItem, ImageDelegate, PreviewLoader, ThumbnailLoader)
from ui.widgets.ocr_widgets import (
    CropOCRWorker, FloatingWidget, OCRLabel, CropOCRSignals)  # CropOCRSignals canonical here

THUMBNAIL_SIZE = (220, 180)
CARD_SIZE = (240, 290) 
MIN_SPACING = 24       
WINDOW_TITLE = "EyeSeeMore-(Alpha)"

'''
EyeSeeMore 
的核心靈魂在於其諧音：「I see more (我看見更多)」。
它代表著即便圖片的檔名是毫無意義的亂碼，軟體依然能穿透表象，看見圖片真正的意涵與內含的文字。
核心設計哲學：回歸圖像本質
無視亂碼檔名：打破「檔名即搜尋關鍵字」的傳統限制，即便圖片檔名是隨機生成的字串，系統也能精準命中。
「看」而非「讀」：傳統軟體是在「讀」標籤，EyeSeeMore 則是透過視覺模型在「看」內容，提取抽象的語義特徵。
'''



# TODO: [UI 改造] 將「AI 引擎設定」頁面重構為「模型管理中心」
# TODO: [互動邏輯] 實作左側「收合選單資料夾」的點擊與右鍵行為
# TODO: 介面與顯示優化：在圖片卡片上顯示更多資訊（如修改日期、OCR 文字預覽等），並優化分數顯示的視覺效果
# TODO: Help -> About 內加入版本資訊、開發者聯繫方式、GitHub 頁面連結等GPL (General Public License) 協議要求的資訊
# TODO: 搜尋介面的ORC控制的分數控制
# TODO: 控制欄的UIUX優化
# TODO: OCR 紅框互動能直接在預覽端修改OCR辨識的結果
# TODO: 想要加上Satisfactory主題的UI樣式
# TODO: 想要加上BlueArchive主題的UI樣式
# TODO: 刪除 Unicode 符號 減少AI味

class MainWindow(QMainWindow):
    # 定義訊號
    random_data_ready = pyqtSignal(list)
    ai_ready = pyqtSignal()
    # [Refactor Phase 2-C] db_reloaded 訊號已移至 IndexingLifecycleHandler 內部

    def __init__(self, config: ConfigManager):
        # [關鍵修正] 這行一定要在第一行，且不能漏掉！
        super().__init__()
        
        self.config = config
        self.setWindowTitle(WINDOW_TITLE)

        # 自定義標題列：移除 Windows 原生 Non-Client Area
        # WndProc 掛鉤負責補回邊框縮放與 DWM 陰影（由 win_titlebar 模組處理）
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(540, 360)

        self.engine = None

        # [Refactor Phase 2-A] search_history 由 SearchHistoryManager 管理
        # 不再於 MainWindow 持有 list；history_mgr 於下方建立後自動載入
        self.current_selected_path = None

        self.current_folder_path = self.config.get("ui_state", {}).get("default_startup_folder", "ALL")

        self.is_ocr_locked = False
        self._ocr_hold_active = False  # hold 模式：Shift 按著時為 True

        # [Refactor Phase 2-D] 以下 4 個屬性已移至 GalleryViewController
        # (last_search_results / last_search_stats / is_in_search_mode /
        #  active_time_range) — 外部存取改走 self.gallery_ctrl.X

        self.current_image_search_path = None
        self.current_multi_vector_features = None  # (pos_features, neg_features)
        
        # 設定歷史紀錄檔路徑
        self.history_file_path = os.path.join(self.config.app_root, "search_history.json")

        # [Refactor Phase 2-A] 歷史紀錄交由 SearchHistoryManager 處理
        # 建構時自動從磁碟載入，後續所有 add/delete 都會自動寫回
        self.history_mgr = SearchHistoryManager(self.history_file_path)

        self.taskbar_ctrl = TaskbarController(self.winId())

        # ── ETA 顯示模式與 PID Clock Slewing ───────────────────────────────
        # [Refactor Phase 2-B] 所有 ETA 狀態與 PID 邏輯封裝在 EtaProgressController
        # 模式 1=真實跳動  2=PID假時間  3=計數  4=測試
        # 訊號連接需等 init_ui() 建立好 self.status / self.progress 後才做
        eta_mode = self.config.get("eta_display_mode", 1)
        self.eta_ctrl = EtaProgressController(mode=eta_mode, parent=self)

        # [Refactor Phase 2-A] history_mgr 已於建構時自動載入，
        # load_history() 仍保留為公開介面但不再於初始化時呼叫
        self.init_ui()

        # [Refactor Phase 2-B] init_ui 已建立 self.status / self.progress，
        # 此時才能將 EtaProgressController 的訊號連接到 UI 元件
        self.eta_ctrl.status_text_changed.connect(self.status.setText)
        self.eta_ctrl.progress_updated.connect(self._on_eta_progress)

        # [Refactor Phase 2-C] 索引生命週期管理器
        # engine 與 indexer_worker 採延遲注入（兩者於下方才建立）
        self.indexing_handler = IndexingLifecycleHandler(
            eta_ctrl=self.eta_ctrl,
            parent=self,
        )
        self.indexing_handler.scan_status_changed.connect(self.status.setText)
        self.indexing_handler.gallery_refresh_requested.connect(
            lambda: self._apply_folder_filter(self.current_folder_path)
        )
        self.indexing_handler.sidebar_refresh_requested.connect(self.refresh_sidebar)
        self.indexing_handler.taskbar_state_changed.connect(self.taskbar_ctrl.set_state)
        self.indexing_handler.pause_menu_state_changed.connect(self._on_pause_menu_state)
        self.indexing_handler.progress_completed.connect(self._on_progress_completed)

        # 空狀態診斷覆蓋層 (疊在 list_view 上方)
        self._empty_state_overlay = EmptyStateOverlay(self.list_view)
        # 讓狀態列 QLabel 支援 PointingHand 游標 (實際點擊邏輯在 eventFilter)
        self.status.setCursor(Qt.CursorShape.PointingHandCursor)

        # [Refactor Phase 2-E] 視窗狀態管理委派至 WindowStateManager
        # 按鈕訊號連接、初始狀態還原、Win32 TOPMOST 切換、NC hit-test 通知
        # 一律由 manager 處理；MainWindow 僅保留 Ctrl+T 全域捷徑
        self.window_state_mgr = WindowStateManager(
            self, self.config,
            btn_pin=self.btn_pin,
            btn_max=self.btn_win_max,
            btn_min=self.btn_win_min,
            btn_close=self.btn_win_close,
        )
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(
            lambda: self.btn_pin.setChecked(not self.btn_pin.isChecked())
        )

        # --- 安裝 Win32 WndProc 掛鉤（補回邊框縮放與 DWM 陰影）---
        from core import win_titlebar
        QTimer.singleShot(0, lambda: win_titlebar.install(
            int(self.winId()),
            titlebar_height=60,
            dpr=self.devicePixelRatioF(),
        ))
        QTimer.singleShot(50, self._update_button_rects)

        # --- NC hover filter（WinMaxBtn hover 補丁）---
        # DLL 回傳 HTMAXBUTTON 時 Windows 接管 NC 滑鼠事件，Qt :hover 不觸發。
        # 改用 WM_APP+1 訊息橋接：DLL → WinMaxHoverFilter → manager._on_max_btn_hover
        self._max_hover_filter = WinMaxHoverFilter(self.window_state_mgr._on_max_btn_hover)
        QApplication.instance().installNativeEventFilter(self._max_hover_filter)
        # 交由 manager 持有參照，uninstall 時統一回收
        self.window_state_mgr.attach_native_filter(self._max_hover_filter)

        # --- 掃描控制 Filter（WM_APP+2 / WM_APP+3 / WM_SYSCOMMAND IDM）---
        # ① DLL 已安裝：C++ HookWndProc 攔截 WM_SYSCOMMAND，PostMessage WM_APP+2/3
        # ② DLL 未安裝：_install_sys_menu() 直接注入系統選單；點擊觸發 WM_SYSCOMMAND，
        #    WinScanCtrlFilter 在 _WM_SYSCOMMAND 分支中攔截。
        self._scan_ctrl_filter = WinScanCtrlFilter(
            self.toggle_scan_pause,
            self.cancel_indexing,
        )
        QApplication.instance().installNativeEventFilter(self._scan_ctrl_filter)

        # --- 視窗 AUMI + 系統選單注入（150 ms 確保 DLL install 已完成）---
        # _set_window_aumi 讓工作列把此視窗歸類為 EyeSeeMore 而非 python.exe，
        # 是跳躍清單任務能正確出現在工作列右鍵選單的前提。
        def _after_show_init():
            _hwnd = int(self.winId())
            _set_window_aumi(_hwnd)
            _install_sys_menu(_hwnd)
        QTimer.singleShot(150, _after_show_init)

        # --- 工作列右鍵跳躍清單（Jump List）注冊 ---
        # singleShot(400) 確保 _set_window_aumi（150 ms）已完成設定視窗 AUMI。
        QTimer.singleShot(400, _register_jump_list)

        # 視窗 show() 後 TopBar 才有正確寬度，呼叫一次重新定位視窗控制按鈕
        QTimer.singleShot(0, lambda: self._reposition_win_buttons())

        # TopBar 空白區拖曳：安裝 event filter，讓點擊 TopBar 背景（非子控件）時觸發原生視窗拖曳
        _top_bar = self.findChild(QFrame, "TopBar")
        if _top_bar:
            self._drag_top_bar = _top_bar
            _top_bar.installEventFilter(self)

        # NavigationManager 需要在 init_ui() 之後建立 (因為依賴 UI 元件)
        from ui.navigation_manager import NavigationManager
        self.nav = NavigationManager(
            state_snapshot_fn=self._nav_snapshot,
            apply_state_fn=self._nav_apply,
            update_buttons_fn=lambda b, f: (
                self.btn_back.setEnabled(b),
                self.btn_forward.setEnabled(f),
            ),
        )

        # [Refactor Phase 2-D] 畫廊視圖控制器（過濾 / 排序 / 視圖模式 / 佈局）
        # 初始尺寸由 main_window_ui.py 在 init_ui() 階段已賦值到 MainWindow，
        # 透過建構子顯式傳入避免雙向耦合
        self.gallery_ctrl = GalleryViewController(
            list_view=self.list_view,
            model=self.model,
            delegate=self.delegate,
            inspector_panel=self.inspector_panel,
            config=self.config,
            empty_state_overlay=self._empty_state_overlay,
            nav=self.nav,
            initial_view_mode=self.current_view_mode,
            initial_card_size=self.current_card_size,
            initial_thumb_size=self.current_thumb_size,
            parent=self,
        )
        self.gallery_ctrl.status_text_changed.connect(self.status.setText)
        self.gallery_ctrl.status_highlight_changed.connect(self._on_status_highlight)
        self.gallery_ctrl.search_input_cleared.connect(lambda: self.input.setText(""))

        # 還原儲存的視圖模式（從 main_window_ui.py 搬過來，因為現在需要 gallery_ctrl）
        saved_view_mode = self.config.get("ui_state", {}).get("view_mode", "large")
        if saved_view_mode != "large":
            self.gallery_ctrl.change_view_mode(saved_view_mode)

        self.indexer_worker = IndexerWorker(self.config, self)  # 加入 self 參數
        self.indexer_worker.status_update.connect(self.update_status) # 稍微改一下 status label 的用法
        self.indexer_worker.progress_update.connect(self.update_progress)
        self.indexer_worker.scan_finished.connect(self.on_scan_finished)
        self.indexer_worker.all_finished.connect(self.on_indexing_finished)
        self.indexer_worker.eta_updated.connect(self._on_eta_updated)
        # [Refactor Phase 2-C] indexer_worker 注入給 handler 以支援 pause/cancel
        self.indexing_handler.indexer_worker = self.indexer_worker

        self.search_orch = SearchOrchestrator(SearchWorker, parent=self)
        self.search_orch.results_ready.connect(self.set_base_results)
        self.search_orch.search_finished.connect(self.on_finished)

        self.img_actions = ImageActionManager(self, toast_fn=self._show_toast)

        # [修改 2] 連接訊號：當 AI 準備好時，執行 on_ai_loaded
        # 初始資料就緒走 _on_initial_data_ready，依 default_startup_folder
        # 立即顯示正確資料夾（不必等模型；資料夾過濾只用 data_store）
        self.random_data_ready.connect(self._on_initial_data_ready)
        self.ai_ready.connect(self.on_ai_loaded)
        # [Refactor Phase 2-C] db_reloaded 訊號移至 IndexingLifecycleHandler 內部處理

        from ui.action_handler import ActionHandler
        self.action_handler = ActionHandler(self)

        # [Signal Relay] ActionHandler 訊號接線
        ah = self.action_handler
        ah.requestEscapeClear.connect(self._on_escape_clear)
        ah.requestOCRShow.connect(self._on_ocr_show)
        ah.requestOCRToggleLock.connect(self._on_ocr_toggle_lock)
        ah.requestNavigate.connect(self._on_navigate)
        ah.requestClosePreview.connect(self._on_close_preview)
        ah.requestPreview.connect(self.toggle_preview)
        ah.requestCopy.connect(self._on_copy_toast)
        ah.requestHistoryToggle.connect(self._on_history_toggle)
        ah.requestFocusGallery.connect(lambda: self.list_view.setFocus())

        # [Signal Relay] SearchCapsule 訊號接線
        self.search_capsule.searchRequested.connect(self._on_search_requested)
        self.search_capsule.errorOccurred.connect(self.status.setText)
        self.search_capsule.set_history(self.history_mgr.get_all())

        QApplication.instance().installEventFilter(self)
        
        # 啟動背景載入 (這裡才會去建立 ImageSearchEngine)
        threading.Thread(target=self.load_engine, daemon=True).start()

        # [Refactor Phase 2-E] 原生視窗記憶委派至 WindowStateManager
        self.window_state_mgr.restore_geometry()
        ui_state = self.config.get("ui_state", {})

        # Splitter 比例還原：在 restoreGeometry() 確立視窗寬度後執行，
        # 且只有 Inspector 可見時才有意義
        if ui_state.get("inspector_visible", True) and "splitter_sizes" in ui_state:
            try:
                self.main_splitter.setSizes(ui_state["splitter_sizes"])
            except Exception as e:
                print(f"[UI] splitter 大小還原失敗: {e}")

        if ui_state.get("auto_scan_on_startup", True):
            self.indexer_worker.start()
        else:
            self.status.setText("自動掃描已停用。點擊左側 ⟳ 可手動更新。")

        # 將新的樣式表附加到現有的樣式表後
        current_stylesheet = self.styleSheet()

    def show_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.clip_model_changed.connect(self._on_clip_model_switched)

        # Phase 13: Collections 訊號 Lambda 接線
        fp = dialog._folders_page
        fp.addCollectionRequested.connect(
            lambda name, icon: self._on_add_collection_requested(fp, name, icon)
        )
        fp.removeCollectionRequested.connect(
            lambda col_id: self._on_remove_collection_requested(fp, col_id)
        )
        fp.updateCollectionIconRequested.connect(
            lambda col_id, icon: self._on_update_collection_icon_requested(fp, col_id, icon)
        )

        dialog.exec()

    def _on_add_collection_requested(self, folders_page, name: str, icon: str):
        if not self.engine:
            return
        ok = self.engine.add_collection(name, icon)
        if ok:
            folders_page.refresh_collections()
            self.sidebar.reload_collections(self.engine.get_collections())
        else:
            QMessageBox.warning(self, "新增失敗", f"「{name}」可能名稱重複或資料庫發生錯誤。")

    def _on_remove_collection_requested(self, folders_page, col_id: int):
        if not self.engine:
            return
        self.engine.remove_collection(col_id)
        folders_page.refresh_collections()
        self.sidebar.reload_collections(self.engine.get_collections())

    def _on_update_collection_icon_requested(self, folders_page, col_id: int, icon: str):
        if not self.engine:
            return
        self.engine.update_collection_icon(col_id, icon)
        folders_page.refresh_collections()
        self.sidebar.reload_collections(self.engine.get_collections())

    def _on_clip_model_switched(self, model_id: str):
        """接收 SettingsDialog.clip_model_changed 訊號，顯示友善提示後安全關閉。"""
        reply = QMessageBox.information(
            self,
            "模型切換成功",
            f"已切換至 {model_id}。\n\n為確保記憶體安全釋放，程式即將關閉，請手動重新啟動。",
            QMessageBox.StandardButton.Ok,
        )
        if reply == QMessageBox.StandardButton.Ok:
            QApplication.quit()

    def init_ui(self):
        from ui.main_window_ui import Ui_MainWindow
        ui = Ui_MainWindow()
        ui.setup_ui(
            self,
            GalleryListView=GalleryListView,
            SearchResultsModel=SearchResultsModel,
            ImageDelegate=ImageDelegate,
            InspectorPanel=InspectorPanel,
            SidebarWidget=SidebarWidget,
            PreviewOverlay=PreviewOverlay,
        )

    # ==========================================
    # init_ui() 結束，接下來是 MainWindow 的其他獨立函式
    # ==========================================

    def on_weights_changed(self, weight_config):
        q = self.input.text().strip()
        if q:
            #  [新增] 如果目前是「以圖搜圖」狀態，切換 Limit 時就重跑以圖搜圖
            if q.startswith("[Image]") and getattr(self, "current_image_search_path", None):
                self.start_image_search(self.current_image_search_path)
            else:
                self.start_search(triggered_by_slider=True)

    # ------------------------------------------------------------------
    #  ActionHandler 訊號接收器 (Signal Relay)
    # ------------------------------------------------------------------
    def _on_escape_clear(self):
        self.input.clearFocus()
        self.list_view.clearSelection()

    def _on_ocr_show(self, visible):
        # hold 模式：按下顯示、放開隱藏（不改變 is_ocr_locked）
        self._ocr_hold_active = visible
        self.preview_overlay.set_ocr_visible(visible)

    def _on_ocr_toggle_lock(self):
        # toggle 模式：按一下切換
        self.is_ocr_locked = not self.is_ocr_locked
        self.preview_overlay.set_ocr_visible(self.is_ocr_locked)

    def _on_navigate(self, key_code):
        from ui.action_handler import ActionHandler
        ActionHandler.send_nav_key(self.list_view, key_code)

    def _on_close_preview(self):
        self.preview_overlay.hide()
        # 關閉預覽時保留 is_ocr_locked，下次重新開啟可還原紅框狀態

    def _on_copy_toast(self, count):
        if count == 1:
            self._show_toast("已複製 1 個檔案到剪貼簿")
        else:
            self._show_toast(f"已複製 {count} 個檔案到剪貼簿")

    def _on_files_dropped_to_collection(self, collection_id: int, file_paths: list):
        """接收 SidebarWidget.files_dropped_to_collection，將圖片寫入虛擬資料夾。"""
        if not self.engine:
            return
        ok = self.engine.add_to_virtual_folder(collection_id, file_paths)
        if ok:
            count = len(file_paths)
            self.sidebar.reload_collections(self.engine.get_collections())
            self._show_toast(f"已加入 {count} 張圖片至虛擬資料夾")
        else:
            self._show_toast("加入失敗，請稍後再試")

    def _on_history_toggle(self, show):
        if show:
            self.search_capsule.show_history_popup()
        else:
            self.history_list.hide()

    # ------------------------------------------------------------------
    #  SearchCapsule 訊號接收器 (Signal Relay)
    # ------------------------------------------------------------------
    def _on_search_requested(self, payload: dict):
        """接收 SearchCapsule.searchRequested 訊號並轉發至 start_search"""
        q = payload.get("query", "").strip()
        if not q:
            return
        # 將 payload 中的 use_ocr 暫存，供 start_search 使用
        self._pending_use_ocr = payload.get("use_ocr", True)
        self.start_search()

    # ------------------------------------------------------------------
    #  導航回呼 (供 NavigationManager 呼叫)
    # ------------------------------------------------------------------
    def _nav_snapshot(self):
        """擷取當前頁面的完整快照 (包含滾輪位置)"""
        return {
            "query": self.input.text().strip(),
            "folder_path": self.current_folder_path,
            "breadcrumb": self.breadcrumb_lbl.fullText(),
            "scroll_pos": self.list_view.verticalScrollBar().value(),
            "image_path": getattr(self, "current_image_search_path", None),
            "multi_vector_features": getattr(self, "current_multi_vector_features", None),
        }

    def _nav_apply(self, state):
        """套用紀錄中的狀態並執行對應的載入"""
        self.current_folder_path = state["folder_path"]
        self.breadcrumb_lbl.setText(state["breadcrumb"])

        mv = state.get("multi_vector_features")
        if mv:
            pos_features, neg_features = mv
            self.start_multi_vector_search(pos_features, neg_features)
        elif state["image_path"]:
            self.start_image_search(state["image_path"])
        elif state["query"]:
            self.input.setText(state["query"])
            self.start_search(triggered_by_slider=False)
        else:
            self.input.setText("")
            self._apply_folder_filter(state["folder_path"])

    def navigate_back(self):
        self.nav.go_back()

    def navigate_forward(self):
        self.nav.go_forward()

    def refresh_sidebar(self):
        """通知側邊欄更新資料夾狀態與排序"""
        if self.engine:
            stats = self.engine.get_folder_stats()
            config_folders = self.config.get("source_folders")
            self.sidebar.update_folders(stats, config_folders)

    # [修復] 加回此函式，讓側邊欄的 + 號能運作，並正確更新畫面
    def on_add_folder_clicked(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            if self.config.add_source_folder(folder):
                # 1. 立即更新側邊欄
                self.refresh_sidebar()
                # 2. 自動觸發一次重新掃描，讓使用者不用再點「⟳」按鈕
                self.on_refresh_clicked() 
            else:
                QMessageBox.warning(self, "重複", "此資料夾已經存在。")

    # [新增] 處理重新整理點擊事件
    def on_refresh_clicked(self):
        # 1. 檢查是否已經在執行中
        if self.indexer_worker.isRunning():
            QMessageBox.warning(self, "Busy", "Indexing is already in progress.")
            return

        raw_folders = self.config.get("source_folders")
        if not raw_folders:
            QMessageBox.information(self, "No Folders", "No source folders configured.")
            return

        # 直接將完整的設定字典交給 Worker
        self.indexer_worker.folders = raw_folders
        
        self.status.setText("Rescanning folders...")
        self.indexer_worker.start()

    def on_sidebar_toggled(self, is_expanded):
        """
        當側邊欄收合/展開時，強制 QListView 重新計算 Grid 佈局。
        """
        QTimer.singleShot(0, self.adjust_layout)

    # [修正] 實作資料夾篩選邏輯
    def on_folder_filter(self, path):
        """用戶主動點擊側邊欄時觸發：記錄導航歷史並顯示"""
        if not self.engine: return
        self.nav.push()
        self._apply_folder_filter(path)

    def _apply_folder_filter(self, path):
        """純顯示邏輯，不操作導航堆疊，供 nav_apply 與 on_folder_filter 共用"""
        if not self.engine: return

        self.current_folder_path = path
        self.gallery_ctrl.is_in_search_mode = False  # 資料夾瀏覽模式，停用診斷覆蓋層
        
        #  [修改] 根據側邊欄自動切換下拉選單預設值
        self.inspector_panel.combo_search_scope.blockSignals(True)
        if path == "ALL":
            self.inspector_panel.combo_search_scope.setCurrentIndex(1) # 側邊欄點ALL，右邊自動切到「全域」
        else:
            self.inspector_panel.combo_search_scope.setCurrentIndex(0) # 側邊欄點特定資料夾，右邊自動切到「目前資料夾」
        self.inspector_panel.combo_search_scope.blockSignals(False)
        
        print(f"Filtering by: {path}")

        self.inspector_panel.combo_sort.blockSignals(True)
        self.inspector_panel.combo_sort.setCurrentText("日期")
        self.inspector_panel.btn_sort_order.setText("↓")
        self.inspector_panel.combo_sort.blockSignals(False)
        
        # ==========================================
        # [修改] 還原麵包屑標題，並清空搜尋框的殘留文字
        # ==========================================
        self.input.setText("") 
        
        # 1. 如果是 "ALL"，顯示全部 (依時間排序)
        if path == "ALL":
            self.breadcrumb_lbl.setText("Gallery")
            all_imgs = self.engine.get_all_images_sorted()
            self.set_base_results(all_imgs)
            self.status.setText(f"Showing all {len(all_imgs)} images")
            return

        # 2. 如果是虛擬資料夾 (格式: "col:{id}")
        if path.startswith("col:"):
            try:
                col_id = int(path.split(":", 1)[1])
            except (IndexError, ValueError):
                return
            results = self.engine.get_virtual_folder_images(col_id)
            # 從 collections 取得名稱作為麵包屑
            collections = self.engine.get_collections()
            col_name = next((name for cid, name, *_ in collections if cid == col_id), f"Collection {col_id}")
            self.breadcrumb_lbl.setText(f"Collection: {col_name}")
            self.set_base_results(results)
            self.status.setText(f"Collection: {col_name} ({len(results)} 張圖片)")
            return

        # 3. 篩選特定資料夾
        self.breadcrumb_lbl.setText(f"Folder: {os.path.basename(path)}")
        
        # 這邊簡單用 Python list comprehension 過濾 (高效能做法建議在 Engine 寫 SQL)
        if self.engine.data_store:
            # 正規化路徑並加上分隔符，防止 D:\img 誤匹配 D:\img-backup
            norm_path = os.path.normpath(path)
            prefix = norm_path + os.sep
            filtered = [
                item for item in self.engine.data_store
                if item["norm_path"].startswith(prefix)
            ]
            
            # 轉換格式給 Model
            results = []
            for item in filtered:
                results.append({
                    "score": 0.0,
                    "path": item["path"],
                    "filename": item["filename"],
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),   #  補上
                    "height": item.get("height", 0)  #  補上
                })
            
            # 按時間排序
            results.sort(key=lambda x: x["mtime"], reverse=True)
            
            # 釘選圖無視資料夾範圍：合併至頂端
            results = self.engine._merge_pinned(results)

            self.set_base_results(results)
            self.status.setText(f"Folder: {os.path.basename(path)} ({len(results)} items)")

    def eventFilter(self, obj, event):
        # ── TopBar 空白區拖曳 ────────────────────────────────
        # installEventFilter 只對「直接送往 top_bar 本身」的事件觸發，
        # 點擊子控件（按鈕、搜尋欄）的事件不會路由到此，因此不需 widgetAt() 判斷。
        if hasattr(self, '_drag_top_bar') and obj is self._drag_top_bar:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    ctypes.windll.user32.ReleaseCapture()
                    ctypes.windll.user32.PostMessageW(int(self.winId()), 0x00A1, 2, 0)
                    return True
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if event.button() == Qt.MouseButton.LeftButton:
                    if self.isMaximized():
                        self.showNormal()
                    else:
                        self.showMaximized()
                    return True
        # ─────────────────────────────────────────────────────
        ah = self.action_handler
        cfg = ah.get_config()

        # 1. 鍵盤按下 (KeyPress) — 純分流
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()

            if key == Qt.Key.Key_Escape:
                if ah.handle_escape():
                    return True

            if key == Qt.Key.Key_Shift:
                return ah.handle_shift_press(cfg["ocr_mode"])

            focused_widget = QApplication.focusWidget()
            is_typing = isinstance(focused_widget, QLineEdit)

            if not is_typing and QApplication.activeWindow() == self:
                if key in (Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D):
                    return ah.handle_wasd(key, cfg["nav_mode"])
                elif key == Qt.Key.Key_Space:
                    return ah.handle_space()

            if key == Qt.Key.Key_C and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                result = ah.handle_copy()
                if result:
                    return True

        # 2. 鍵盤放開 (KeyRelease)
        if event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Shift:
                return ah.handle_shift_release(cfg["ocr_mode"])

        # 3. 滑鼠點擊 (MouseButtonPress)
        if event.type() == QEvent.Type.MouseButtonPress:
            # 狀態列點擊：顯示漏斗統計預覽 (搜尋模式，或有任何過濾器啟用時皆有效)
            _has_filters = self.inspector_panel.btn_clear_all.isVisible()
            if obj is self.status and (self.gallery_ctrl.is_in_search_mode or _has_filters):
                stats = self.gallery_ctrl.last_search_stats
                if stats:
                    fi = FunnelCardItem(
                        raw_count=stats.get('raw_count', 0),
                        after_date=stats.get('after_date', 0),
                        after_aspect=stats.get('after_aspect', 0),
                        final_count=stats.get('final_count', 0),
                    )
                    self.preview_overlay.show_funnel_card(fi)
                return True
            ah.handle_mouse_press(obj, event)

        return super().eventFilter(obj, event)

# ==========================================
# 請找到 MainWindow 類別中的 toggle_preview 與 on_selection_changed 函式並替換
# ==========================================

    def toggle_preview(self):
        if self.preview_overlay.isVisible():
            self.preview_overlay.hide()
            # 關閉預覽時保留 is_ocr_locked，下次重新開啟可還原紅框狀態
        else:
            index = self.list_view.currentIndex()
            if index.isValid():
                item = index.data(Qt.ItemDataRole.UserRole)
                if item:
                    # 漏斗卡片：顯示全屏放大版漏斗統計
                    if getattr(item, 'is_funnel_card', False):
                        self.preview_overlay.show_funnel_card(item)
                        return

                    # 保留目前的 is_ocr_locked 狀態（不強制重置）
                    # show_image() 內部會讀取 is_ocr_locked 並呼叫 set_ocr_visible
                    current_query = self.input.text().strip()
                    is_precise = self.config.get("ui_state", {}).get("precise_ocr_highlight", False)

                    #  從 Model 取出 L1 快取小圖
                    l1_pixmap = self.model._thumbnail_cache.get(item.path)

                    #  傳遞給顯示層
                    self.preview_overlay.show_image(item, current_query, is_precise, l1_pixmap)

    def toggle_inspector(self):
        """控制右側面板的展開與收合"""
        if self.inspector_panel.isVisible():
            self.inspector_panel.hide()
            self.btn_toggle_inspector.setChecked(False)
        else:
            self.inspector_panel.show()
            self.btn_toggle_inspector.setChecked(True)
            
        # 開關面板會改變畫廊寬度，必須通知 QListView 重新計算網格排版
        QTimer.singleShot(0, self.adjust_layout)

    # ==========================================
    # 視窗狀態 — 已委派至 self.window_state_mgr (WindowStateManager)
    # 4 個原方法簽章保留作為 Thin Delegation Layer (Phase 2-E)
    # ==========================================
    def _on_pin_toggled(self, checked: bool):
        """[委派] 切換視窗置頂狀態（Win32 SetWindowPos TOPMOST）。"""
        self.window_state_mgr._on_pin_toggled(checked)

    def _on_win_max_toggled(self, checked: bool):
        """[委派] 最大化 / 還原視窗。"""
        self.window_state_mgr._on_win_max_toggled(checked)

    def _on_max_btn_hover(self, hovered: bool):
        """[委派] 刷新 WinMaxBtn NC hover 外觀（DLL WM_APP+1 → 此處）。"""
        self.window_state_mgr._on_max_btn_hover(hovered)

    def _update_button_rects(self):
        """[委派] 通知 WndProc Hook 四個視窗控制按鈕的命中座標。"""
        self.window_state_mgr.update_button_rects()

    def on_selection_changed(self, current, previous):
        # 1. 更新右側面板資訊 (如果面板存在且有選取項目)
        if hasattr(self, 'inspector_panel') and current.isValid():
            item = current.data(Qt.ItemDataRole.UserRole)
            if item:
                self.inspector_panel.update_info(item)

        # 2. 預覽畫面同步邏輯 (沉浸模式 WASD 切換)
        nav_mode = self.config.get("ui_state", {}).get("preview_wasd_mode", "nav")
        if self.preview_overlay.isVisible() and nav_mode == "sync":
            if current.isValid():
                item = current.data(Qt.ItemDataRole.UserRole)
                if item:
                    # 抓出目前的搜尋字與精確模式狀態
                    current_query = self.input.text().strip()
                    is_precise = self.config.get("ui_state", {}).get("precise_ocr_highlight", False)
                    
                    #  核心修改 1：從 Model 取出 L1 快取小圖
                    l1_pixmap = self.model._thumbnail_cache.get(item.path)
                    
                    #  核心修改 2：完整傳遞給顯示層，實現光速預覽！
                    self.preview_overlay.show_image(item, current_query, is_precise, l1_pixmap)
                    
                    #  [加碼優化] 保持 OCR 鎖定狀態（toggle 模式 or hold 模式 Shift 按著）
                    self.preview_overlay.set_ocr_visible(self.is_ocr_locked or self._ocr_hold_active)

    

    


    # ==========================================
    # 畫廊視圖 — 已委派至 self.gallery_ctrl (GalleryViewController)
    # 8 個原方法簽章保留作為 Thin Delegation Layer (Phase 2-D)
    # ==========================================
    def apply_gallery_sort(self):
        """[委派] 對目前 Gallery 圖片進行排序（釘選永遠置頂）。"""
        self.gallery_ctrl.apply_gallery_sort()

    def set_base_results(self, results):
        """[委派] 所有搜尋或載入資料的統一入口，自動套用過濾器。"""
        self.gallery_ctrl.set_base_results(results)

    def apply_current_filters_and_show(self, test_mode=False):
        """[委派] 套用時間/長寬比/Limit 過濾器並顯示。"""
        return self.gallery_ctrl.apply_current_filters_and_show(test_mode)

    def apply_time_filter_to_gallery(self, start_ts, end_ts):
        """[委派] 套用日期區間過濾器（含防呆退回）。"""
        self.gallery_ctrl.apply_time_filter_to_gallery(start_ts, end_ts)

    def clear_time_filter(self):
        """[委派] 清除日期區間過濾器。"""
        self.gallery_ctrl.clear_time_filter()

    def _update_search_diagnostics(self):
        """[委派] 根據漏斗統計更新空狀態覆蓋層與狀態列高亮。"""
        self.gallery_ctrl._update_search_diagnostics()

    def update_status_highlight(self, alert_level: str):
        """[委派] 設定狀態列邊框高亮 ('alert' / 'none')。"""
        self.gallery_ctrl.update_status_highlight(alert_level)

    def search_by_time_range(self, start_ts, end_ts):
        """[委派] 直接時間區間搜尋（忽略關鍵字，全域抓取）。"""
        self.gallery_ctrl.search_by_time_range(start_ts, end_ts)

    def _on_status_highlight(self, alert_level: str):
        """接收 gallery_ctrl.status_highlight_changed → 設定狀態列 stylesheet。"""
        if alert_level == 'alert':
            self.status.setStyleSheet(
                'border: 1px solid #F5A623; border-radius: 4px; '
                'padding: 2px 6px; color: #F5A623;'
            )
        else:
            self.status.setStyleSheet('')

    def on_ai_loaded(self):
        """
        [委派] 當 AI 模型載入完成後被呼叫 (會在主執行緒執行)

        [Refactor Phase 3-A] 此方法已改為空實現，
        所有邏輯已移至 _on_models_loaded()（由 model_provider.models_loaded 訊號觸發）

        此方法保留以維持向後相容性（由 ai_ready.connect 調用）。
        """
        pass
    
    def update_status(self, text):
        # [Refactor Phase 2-B] 委派至 eta_ctrl：回傳 True 表示模式允許
        # 直接更新狀態列，False 表示 PID timer 控制中應交由 tick 訊號處理
        if self.eta_ctrl.set_stage_message(text):
            self.status.setText(text)

    # ==========================================
    # ETA 進度 — 已委派至 self.eta_ctrl (EtaProgressController)
    # 6 個原方法簽章保留作為 Thin Delegation Layer (Phase 2-B)
    # ==========================================
    def apply_eta_mode(self, mode: int):
        """[委派] 設定頁即時切換模式；模式切離 2 時自動停止 PID timer。"""
        self.eta_ctrl.apply_mode(mode)

    def pause_eta_timer(self):
        """[委派] 暫停 ETA 計時（預留給未來 Pause/Resume 功能）。"""
        self.eta_ctrl.pause_timer()

    def resume_eta_timer(self):
        """[委派] 繼續 ETA 計時（預留給未來 Pause/Resume 功能）。"""
        self.eta_ctrl.resume_timer()

    def _eta_total_elapsed(self) -> float:
        """[委派] 回傳累計運行秒數（暫停期間不包含）。"""
        return self.eta_ctrl.total_elapsed()

    def _on_eta_updated(self, t_real: float):
        """[委派] 收到 IndexerWorker 計算出的真實剩餘時間 (T_real)。"""
        self.eta_ctrl.on_real_eta(t_real)

    def _on_eta_progress(self, current: int, total: int):
        """接收 eta_ctrl.progress_updated 訊號，更新進度條 value（不動 range）。
        range 已在 update_progress 進入 mode 2 時設為 (0, PROGRESS_SCALE)。
        """
        self.progress.setValue(current)

    def update_progress(self, current, total):
        self.progress.show()

        if self.eta_ctrl.mode == 2:
            # ── 模式 2：只負責確保進度條可見與刻度正確，數值由 eta_ctrl tick 訊號寫入 ──
            if hasattr(self, '_progress_anim'):
                self._progress_anim.stop()
            if self.progress.maximum() != self.eta_ctrl.PROGRESS_SCALE:
                self.progress.setRange(0, self.eta_ctrl.PROGRESS_SCALE)
                self.progress.setValue(0)
        else:
            # ── 其他模式：直接設定，不做動畫 ──
            if hasattr(self, '_progress_anim'):
                self._progress_anim.stop()
            if self.progress.maximum() != total:
                self.progress.setRange(0, total)
            self.progress.setValue(current)

        # [修改] 暫停中維持黃色進度條，正常執行才更新為綠色
        if not getattr(self.indexer_worker, '_paused', False):
            self.taskbar_ctrl.set_state(TBPF_NORMAL)
        self.taskbar_ctrl.set_progress(current, total)

    # ==========================================
    # 索引生命週期 — 已委派至 self.indexing_handler (IndexingLifecycleHandler)
    # 6 個原方法簽章保留作為 Thin Delegation Layer (Phase 2-C)
    # ==========================================
    def on_scan_finished(self, added, deleted):
        """[委派] IndexerWorker.scan_finished 接收端。"""
        self.indexing_handler.on_scan_finished(added, deleted)

    def on_indexing_finished(self):
        """[委派] IndexerWorker.all_finished 接收端（觸發雙緩衝 reload）。"""
        self.indexing_handler.on_indexing_finished()

    def toggle_scan_pause(self):
        """[委派] 切換掃描暫停／繼續。"""
        self.indexing_handler.toggle_scan_pause()

    def cancel_indexing(self):
        """[委派] 強制中止索引任務。"""
        self.indexing_handler.cancel_indexing()

    def trigger_background_db_reload(self):
        """[委派] 觸發雙緩衝背景資料庫重載。"""
        self.indexing_handler.trigger_background_db_reload()

    def on_db_reloaded(self):
        """[委派] 背景重載完畢回呼（透過 handler 內部訊號路由）。"""
        self.indexing_handler.on_db_reloaded()

    # ── IndexingLifecycleHandler 訊號接收 slot ─────────────────────────
    def _on_pause_menu_state(self, checked: bool):
        """接收 handler.pause_menu_state_changed → 更新 Win32 系統選單勾選。"""
        from core import win_titlebar
        win_titlebar.set_menu_state(win_titlebar.IDM_PAUSE_SCAN, checked)

    def _on_progress_completed(self):
        """接收 handler.progress_completed → 進度條收尾動作。"""
        # 停止平滑動畫，再帶到滿格後隱藏
        if hasattr(self, '_progress_anim'):
            self._progress_anim.stop()
        self.progress.setValue(self.progress.maximum())
        self.progress.hide()

    # 右鍵選單邏輯
    def show_context_menu(self, pos):
        index = self.list_view.indexAt(pos)
        if index.isValid():
            item = index.data(Qt.ItemDataRole.UserRole)
            if not item: return
            engine = self.engine
            is_pinned = engine.is_pinned(item.path) if engine else False
            menu = self.img_actions.build_item_menu(
                index, item,
                on_search_similar=self.start_image_search,
                on_toggle_pin=self._on_toggle_pin if engine else None,
                is_pinned=is_pinned,
            )
        else:
            menu = self.img_actions.build_view_menu(
                self, self.gallery_ctrl.current_view_mode, on_change_mode=self.change_view_mode)
        menu.exec(self.list_view.mapToGlobal(pos))

    def _on_toggle_pin(self, file_path: str):
        """切換釘選狀態：僅更新該卡片的 is_pinned 旗標並局部重繪，不重建列表亦不跳頂。"""
        if not self.engine:
            return
        new_state = self.engine.toggle_pin(file_path)
        # 在 model 中找到對應 row，就地更新旗標並發射局部 dataChanged
        row = self.model.path_to_row.get(file_path)
        if row is not None and 0 <= row < len(self.model.all_items):
            self.model.all_items[row].is_pinned = new_state
            idx = self.model.index(row, 0)
            self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.UserRole])
        # 同步更新 gallery_ctrl.last_search_results，維持後續過濾/合併操作的一致性
        for r in self.gallery_ctrl.last_search_results:
            if r.get('path') == file_path:
                r['is_pinned'] = new_state
                break

    def change_view_mode(self, mode):
        """[委派] 切換視圖模式 (xl / large / medium)。"""
        # 防呆：早期 resizeEvent 可能在 gallery_ctrl 建立前觸發
        if hasattr(self, 'gallery_ctrl'):
            self.gallery_ctrl.change_view_mode(mode)

    def adjust_layout(self):
        """[委派] 動態均分佈局計算（resize / sidebar 切換時觸發）。"""
        # 防呆：早期 resizeEvent 可能在 gallery_ctrl 建立前觸發
        if hasattr(self, 'gallery_ctrl'):
            self.gallery_ctrl.adjust_layout()

    def on_item_clicked(self, index):
        if not index.isValid(): return
        item = index.data(Qt.ItemDataRole.UserRole)
        if item: self.current_selected_path = item.path

    def on_item_double_clicked(self, index):
        if not index.isValid(): return
        item = index.data(Qt.ItemDataRole.UserRole)
        if item:
            self.img_actions.open_file(item.path)

    # ------------------------------------------------------------------
    #  Toast 回饋（供 ImageActionManager callback 使用）
    # ------------------------------------------------------------------
    def _show_toast(self, message: str, duration_ms: int = 1500) -> None:
        if not getattr(self, '_is_toast_active', False):
            self._previous_status_text = self.status.fullText()
        self._is_toast_active = True
        self.status.setText(message)

        def _restore():
            self.status.setText(getattr(self, '_previous_status_text', 'System Ready'))
            self._is_toast_active = False

        QTimer.singleShot(duration_ms, _restore)

    # ==========================================
    # 搜尋歷史紀錄 — 已委派至 self.history_mgr (SearchHistoryManager)
    # 純資料邏輯交由 manager，MainWindow 僅保留 UI 同步（Phase 2-A）。
    # ==========================================
    def load_history(self):
        """[委派] 從 search_history.json 重新載入歷史紀錄到記憶體。"""
        self.history_mgr.load()

    def save_history_to_file(self):
        """[委派] 將目前的歷史紀錄寫回 search_history.json。"""
        self.history_mgr.save()

    def add_to_history(self, query):
        """新增查詢至歷史紀錄並同步更新 SearchCapsule UI。"""
        history = self.history_mgr.add(query)
        # 同步更新 SearchCapsule 內部歷史快取
        self.search_capsule.set_history(history)

    def delete_history_item(self, text):
        """從歷史紀錄中刪除指定項目並同步刷新 SearchCapsule UI 與彈窗。"""
        history = self.history_mgr.delete(text)
        self.search_capsule.set_history(history)
        self.search_capsule.show_history_popup()
    
    def trigger_history_search(self, text): 
        self.input.setText(text); self.start_search()

    def show_history_popup(self):
        """委派給 SearchCapsule 元件處理"""
        self.search_capsule.show_history_popup()
    
    def load_engine(self):
        try:
            # [新增] 載入模型時，工作列顯示綠色流光 (跑動條)
            self.taskbar_ctrl.set_state(TBPF_INDETERMINATE)

            # [Perf Phase 3-G] 在背景執行緒才 import：
            # image_search_engine 頂層會拉入 faiss / onnxruntime / numpy，
            # 移到這裡讓主視窗不必等這些重模組載入完成
            from core.image_search_engine import ImageSearchEngine

            # 正確建立 Engine 實例
            self.engine = ImageSearchEngine(self.config)
            self.search_orch.engine = self.engine   # 將引擎注入 Orchestrator
            self.img_actions.engine = self.engine   # 將引擎注入 ActionManager
            # [Refactor Phase 2-C] 將引擎注入 IndexingLifecycleHandler
            self.indexing_handler.engine = self.engine
            # [Refactor Phase 2-D] 將引擎注入 GalleryViewController（search_by_time_range 用）
            self.gallery_ctrl.engine = self.engine

            # 呼叫排序方法
            all_images = self.engine.get_all_images_sorted()

            if all_images:
                self.random_data_ready.emit(all_images)
                self.status.setText(f"Loaded {len(all_images)} images. Loading AI in background...")

            time.sleep(0.05)

            # [Refactor Phase 3-A] 改為非阻塞啟動模型加載
            # 訊號連接：model_provider.models_loaded → _on_models_loaded
            self.engine.model_provider.models_loaded.connect(self._on_models_loaded)
            self.engine.model_provider.models_load_failed.connect(self._on_models_load_failed)

            # 立刻啟動非阻塞模型加載（在背景執行緒）
            self.engine.load_ai_models()

            QApplication.processEvents()

        except Exception as e:
            print(f"Engine Load Error: {e}")
            import traceback
            traceback.print_exc()

    def _on_initial_data_ready(self, all_images):
        """[Callback] 引擎資料就緒時的初始顯示（主執行緒，由 random_data_ready 觸發）。

        依 config 的 default_startup_folder 決定初始畫面：
        - "ALL"：顯示全部圖片
        - 特定資料夾 / "col:{id}" 虛擬資料夾：套用對應過濾

        關鍵：資料夾過濾只依賴 engine.data_store，與模型載入無關，
        所以這裡就先顯示正確資料夾，不必等到 _on_models_loaded
        （否則使用者會先看到全部圖片，等模型載入後才跳轉，造成
         「初始顯示忽略設定」與「彷彿要互動才生效」的錯覺）。
        """
        folder = self.current_folder_path
        if folder and folder != "ALL":
            self._apply_folder_filter(folder)
        else:
            self.set_base_results(all_images)

    def _on_models_loaded(self):
        """
        [Callback] 模型加載完成

        由 ModelProvider.models_loaded 訊號觸發（在主執行緒）
        """
        count = len(self.engine.data_store) if self.engine else 0
        self.status.setText(f"System Ready ({count} images)")
        self.progress.hide()

        # [新增] AI 準備好後，關閉工作列的進度條狀態
        self.taskbar_ctrl.set_state(TBPF_NOPROGRESS)

        # 這裡會去抓取資料夾統計，並建立二級選單的按鈕
        if self.engine:
            self.refresh_sidebar()
            self.sidebar.reload_collections(self.engine.get_collections())

            # 還原手風琴展開狀態（在資料填充完成後套用）
            ui_state = self.config.get("ui_state", {})
            self.sidebar.set_accordion_states(
                folders_open=ui_state.get("folders_accordion_open", False),
                collections_open=ui_state.get("collections_accordion_open", False),
            )

            # [Phase 3-G] 初始資料夾過濾已在 _on_initial_data_ready（資料就緒時）
            # 套用，這裡不再重複過濾——否則模型載入完成後會再 reset 一次畫廊，
            # 造成捲動位置跳回頂端與縮圖重載的可見閃動。

        # 發射 ai_ready 訊號（供舊程式碼相容）
        self.ai_ready.emit()

    def _on_models_load_failed(self, error_msg: str):
        """
        [Callback] 模型加載失敗

        由 ModelProvider.models_load_failed 訊號觸發（在主執行緒）
        """
        print(f"[Error] 模型加載失敗: {error_msg}")
        self.status.setText(f"❌ 模型加載失敗: {error_msg}")
        self.progress.hide()
        self.taskbar_ctrl.set_state(TBPF_ERROR)

    # ------------------------------------------------------------------
    #  搜尋 UI 前置：重設進度條 / 狀態列 / 排序下拉
    # ------------------------------------------------------------------
    def _prepare_search_ui(self, status_text: str, breadcrumb_text: str) -> None:
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status.setText(status_text)
        self.breadcrumb_lbl.setText(breadcrumb_text)
        self.inspector_panel.combo_sort.blockSignals(True)
        self.inspector_panel.combo_sort.setCurrentText("搜尋相關度")
        self.inspector_panel.btn_sort_order.setText("↓")
        self.inspector_panel.combo_sort.blockSignals(False)

    def start_search(self, *args, triggered_by_slider=False):
        #  新增：如果是使用者手動按 Enter 搜尋，立刻交出焦點釋放 WASD 快捷鍵
        if not triggered_by_slider:
            self.input.clearFocus()
            
        q = self.input.text().strip()
        if not q or not self.engine: return
        
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', q))
        if has_chinese and not getattr(self.engine, 'is_hf_tokenizer', True):
            if not triggered_by_slider:
                QMessageBox.warning(self, "不支援的語言", "您目前使用的 AI 模型僅支援「英文」搜尋...")
            return
        
        if not triggered_by_slider:

            if not self.nav.is_navigating:
                self.nav.push()

            self.current_image_search_path = None
            self.current_multi_vector_features = None
            self.add_to_history(q)
            self.search_capsule.hide_history()
            self._prepare_search_ui("Searching...", "Search Results")

        # 從 SearchCapsule payload 或按鈕狀態取得 use_ocr
        use_ocr = getattr(self, '_pending_use_ocr', self.btn_ocr_toggle.isChecked())
        self._pending_use_ocr = None  # 消費後清除

        self.gallery_ctrl.is_in_search_mode = True  # 進入搜尋結果模式
        fetch_k, target_folder = self.search_orch.resolve_search_params(
            self.inspector_panel.combo_limit_panel.currentText(),
            self.inspector_panel.combo_search_scope.currentIndex(),
            self.current_folder_path)

        self.search_orch.submit(
            q, search_mode="text",
            use_ocr=use_ocr,
            weight_config=self.inspector_panel.get_weight_config(),
            folder_path=target_folder, fetch_k=fetch_k,
        )

    def start_image_search(self, image_path):
        if not self.engine: return

        if not self.nav.is_navigating:
            self.nav.push()
        self.current_image_search_path = image_path
        self.current_multi_vector_features = None

        self.history_list.hide()
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        self._prepare_search_ui("Searching by Image...", "Similar Images")

        self.gallery_ctrl.is_in_search_mode = True  # 進入搜尋結果模式
        fetch_k, target_folder = self.search_orch.resolve_search_params(
            self.inspector_panel.combo_limit_panel.currentText(),
            self.inspector_panel.combo_search_scope.currentIndex(),
            self.current_folder_path)

        self.search_orch.submit(
            image_path, search_mode="image",
            folder_path=target_folder, fetch_k=fetch_k,
        )

    def start_multi_vector_search(self, pos_features, neg_features):
        if not self.engine: return
        if not self.nav.is_navigating: self.nav.push()

        self.current_image_search_path = None
        self.current_multi_vector_features = (pos_features, neg_features)

        self.history_list.hide()
        self.input.setText(f"[Multi-Vector] Pos:{len(pos_features)} Neg:{len(neg_features)}")
        self._prepare_search_ui("Calculating Vector Math...", "Vector Arithmetic Results")

        self.gallery_ctrl.is_in_search_mode = True  # 進入搜尋結果模式
        fetch_k, target_folder = self.search_orch.resolve_search_params(
            self.inspector_panel.combo_limit_panel.currentText(),
            self.inspector_panel.combo_search_scope.currentIndex(),
            self.current_folder_path)

        self.search_orch.submit(
            {'pos': pos_features, 'neg': neg_features},
            search_mode="multi_vector",
            folder_path=target_folder, fetch_k=fetch_k,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # 隱藏浮動視窗 (加上 hasattr 防呆檢查，避免初始化時崩潰)
        if hasattr(self, 'history_list'):
            self.history_list.hide()

        if hasattr(self, 'preview_overlay') and self.preview_overlay.isVisible():
            self.preview_overlay.resize(self.size())

        if hasattr(self, '_empty_state_overlay') and self._empty_state_overlay.isVisible():
            self._empty_state_overlay.resize(self.list_view.size())

        # [關鍵] 視窗大小改變時，Viewport 寬度也會變，必須重算
        QTimer.singleShot(0, self.adjust_layout)

        # 同步 WndProc 按鈕感應座標
        QTimer.singleShot(0, self._update_button_rects)

        # [Refactor Phase 2-E] 最大化 / 還原時同步按鈕圖示，委派至 manager
        if hasattr(self, 'window_state_mgr'):
            self.window_state_mgr.sync_max_button_state()

    def showEvent(self, event):
        super().showEvent(event)
        # 延遲觸發，確保 Qt 的幾何運算已經完成
        QTimer.singleShot(10, self.adjust_layout)

    def closeEvent(self, event):
        ui_state = self.config.get("ui_state", {})

        # [Refactor Phase 2-E] 視窗幾何寫入委派至 WindowStateManager
        # (in-place 修改 ui_state，包含 geometry / window_state 與舊欄位清理)
        self.window_state_mgr.save_geometry_into(ui_state)

        # 其餘 UI 狀態
        ui_state["sidebar_expanded"] = self.sidebar.is_expanded
        ui_state["folders_accordion_open"] = self.sidebar._folders_accordion_open
        ui_state["collections_accordion_open"] = self.sidebar._collections_accordion_open
        ui_state["view_mode"] = getattr(self.gallery_ctrl, 'current_view_mode', 'large')
        ui_state["inspector_visible"] = self.inspector_panel.isVisible()

        # Inspector 寬度：只在 Inspector 可見時儲存 splitter 比例
        # 若 Inspector 隱藏，sizes()[1] 為 0，儲存無意義
        if self.inspector_panel.isVisible():
            _sizes = self.main_splitter.sizes()
            if len(_sizes) >= 2 and _sizes[1] > 0:
                ui_state["splitter_sizes"] = list(_sizes)

        # 一次性原子寫入，避免兩次 set 之間的狀態不一致
        self.config.set("ui_state", ui_state)

        # [Refactor Phase 2-E] Win32 資源回收（NC filter + WndProc Hook）委派至 manager
        self.window_state_mgr.uninstall()

        super().closeEvent(event)


    def on_finished(self, elapsed, total): self.progress.hide(); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

if __name__ == "__main__":
    # 注意：--esm-cmd 快速退出已移至檔案最頂端（import 之前），此處不再重複。
    # ── 主實例正常啟動 ────────────────────────────────────────────────────

    app_config = ConfigManager()

    current_lang = app_config.get("ui_state", {}).get("language", "zh_TW")
    app_config.translator = Translator(current_lang)

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        
    app = QApplication(sys.argv)
    
    #  [修改] 棄用寫死的 WIN11_STYLESHEET，改用 ThemeManager
    theme_manager = ThemeManager(app_config)
    theme_manager.apply_theme(app, theme_manager.current_theme_id)

    is_first_run = not app_config.get("source_folders")
    if is_first_run:
        onboarding = OnboardingDialog(app_config)
        onboarding.exec() 

    w = MainWindow(app_config) 
    # 把 theme_manager 存進 main window，方便設定頁面呼叫
    w.theme_manager = theme_manager 
    w.show()
    sys.exit(app.exec())
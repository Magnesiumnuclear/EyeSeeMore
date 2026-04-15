# ==========================================
#  action_handler.py
#  EyeSeeMore - 事件處理與熱鍵動作層 (Signal Relay 版)
#  所有 handle_xxx 方法在邏輯成立時發射訊號，
#  由 MainWindow 負責最終調度與 UI 副作用。
# ==========================================

from PyQt6.QtWidgets import QApplication, QLineEdit
from PyQt6.QtCore import Qt, QObject, QEvent, QPoint, QRect, QUrl, QMimeData, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent


class ActionHandler(QObject):
    """
    MainWindow 的熱鍵與事件動作執行器 (訊號中繼版)。

    【發射訊號】
    - requestEscapeClear()        : Esc 鍵且搜尋框有焦點時
    - requestOCRShow(bool)        : Shift 按下/放開，True=顯示 False=隱藏
    - requestOCRToggleLock()      : Shift 按下 (toggle 模式) 切換鎖定
    - requestNavigate(int)        : WASD 鍵，傳入對應的 Qt.Key (Up/Down/Left/Right)
    - requestClosePreview()       : WASD close 模式下關閉預覽
    - requestPreview()            : Space 鍵
    - requestCopy(int)            : Ctrl+C 且已完成剪貼簿寫入，傳入複製的檔案數量
    - requestHistoryToggle(bool)  : True=顯示歷史 False=隱藏歷史
    - requestFocusGallery()       : WASD 後需要讓畫廊取得焦點

    【外部依賴 (唯讀)】
    初始化時需傳入 MainWindow 實例 (self.w)，用於：
      - self.w.config            : 讀取設定 (唯讀)
      - self.w.input             : 判斷焦點狀態 (唯讀)
      - self.w.list_view         : 發送模擬按鍵 + 讀取選取狀態 (唯讀)
      - self.w.preview_overlay   : 判斷是否可見 (唯讀)
      - self.w.history_list      : 判斷是否可見 + 幾何碰撞測試 (唯讀)
    """

    # --- 請求訊號 ---
    requestEscapeClear = pyqtSignal()
    requestOCRShow = pyqtSignal(bool)
    requestOCRToggleLock = pyqtSignal()
    requestNavigate = pyqtSignal(int)
    requestClosePreview = pyqtSignal()
    requestPreview = pyqtSignal()
    requestCopy = pyqtSignal(int)
    requestHistoryToggle = pyqtSignal(bool)
    requestFocusGallery = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(main_window)
        self.w = main_window

    # ------------------------------------------------------------------
    #  讀取設定：每次事件觸發時由 eventFilter 呼叫一次即可
    # ------------------------------------------------------------------
    def get_config(self):
        ui_state = self.w.config.get("ui_state", {})
        return {
            "ocr_mode": ui_state.get("ocr_shift_mode", "hold"),
            "nav_mode": ui_state.get("preview_wasd_mode", "nav"),
        }

    # ------------------------------------------------------------------
    #  ESC：清除焦點與選取
    # ------------------------------------------------------------------
    def handle_escape(self):
        """回傳 True 表示已攔截事件"""
        if self.w.input.hasFocus():
            self.requestEscapeClear.emit()
            return True
        return False

    # ------------------------------------------------------------------
    #  Shift 按下：OCR 紅框顯示
    # ------------------------------------------------------------------
    def handle_shift_press(self, ocr_mode):
        if self.w.preview_overlay.isVisible():
            if ocr_mode == "toggle":
                self.requestOCRToggleLock.emit()
            else:
                self.requestOCRShow.emit(True)
        return True

    # ------------------------------------------------------------------
    #  Shift 放開：OCR 紅框隱藏 (僅 hold 模式)
    # ------------------------------------------------------------------
    def handle_shift_release(self, ocr_mode):
        if self.w.preview_overlay.isVisible():
            if ocr_mode != "toggle":
                self.requestOCRShow.emit(False)
        return True

    # ------------------------------------------------------------------
    #  WASD：畫廊導航
    # ------------------------------------------------------------------
    def handle_wasd(self, key, nav_mode):
        is_preview_active = self.w.preview_overlay.isVisible()

        # 模式 1：按 WASD 時關閉預覽
        if is_preview_active and nav_mode == "close":
            self.requestClosePreview.emit()

        self.requestFocusGallery.emit()

        key_map = {
            Qt.Key.Key_W: Qt.Key.Key_Up,
            Qt.Key.Key_S: Qt.Key.Key_Down,
            Qt.Key.Key_A: Qt.Key.Key_Left,
            Qt.Key.Key_D: Qt.Key.Key_Right,
        }
        nav_key = key_map.get(key)
        if nav_key is not None:
            self.requestNavigate.emit(nav_key)
        return True

    # ------------------------------------------------------------------
    #  Space：切換預覽
    # ------------------------------------------------------------------
    def handle_space(self):
        self.requestPreview.emit()
        return True

    # ------------------------------------------------------------------
    #  Ctrl+C：智慧檔案路徑複製 + Toast 訊號
    # ------------------------------------------------------------------
    def handle_copy(self):
        if self.w.input.hasFocus():
            return False  # 搜尋框內的 Ctrl+C 交給系統處理
        if QApplication.activeWindow() != self.w:
            return False

        selected_indexes = self.w.list_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            return False

        # 打包成實體檔案路徑 (剪貼簿操作由 ActionHandler 負責)
        mime_data = QMimeData()
        urls = []
        for idx in selected_indexes:
            item = idx.data(Qt.ItemDataRole.UserRole)
            if item and item.path:
                urls.append(QUrl.fromLocalFile(item.path))

        mime_data.setUrls(urls)
        QApplication.clipboard().setMimeData(mime_data)

        # 發射訊號，由 MainWindow 負責 Toast 顯示
        self.requestCopy.emit(len(urls))
        return True

    # ------------------------------------------------------------------
    #  滑鼠點擊：歷史紀錄面板開關
    # ------------------------------------------------------------------
    def handle_mouse_press(self, obj, event):
        click_pos = event.globalPosition().toPoint()

        # 點擊外部 → 關閉歷史紀錄
        if self.w.history_list.isVisible():
            input_rect = QRect(self.w.input.mapToGlobal(QPoint(0, 0)), self.w.input.size())
            list_rect = QRect(self.w.history_list.mapToGlobal(QPoint(0, 0)), self.w.history_list.size())
            if not input_rect.contains(click_pos) and not list_rect.contains(click_pos):
                self.requestHistoryToggle.emit(False)

        # 點擊搜尋框 → 彈出歷史紀錄
        if obj == self.w.input:
            self.requestHistoryToggle.emit(True)

    # ------------------------------------------------------------------
    #  內部輔助：發送模擬按鍵給 ListView
    # ------------------------------------------------------------------
    @staticmethod
    def send_nav_key(list_view, key_code):
        """對指定的 QListView 發送模擬方向鍵"""
        press = QKeyEvent(QEvent.Type.KeyPress, key_code, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, key_code, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(list_view, press)
        QApplication.sendEvent(list_view, release)

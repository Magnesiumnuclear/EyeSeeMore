# ==========================================
#  action_handler.py
#  EyeSeeMore - 事件處理與熱鍵動作層
#  從 MainWindow.eventFilter 中提取的所有具體動作邏輯。
#  MainWindow 的 eventFilter 僅負責分流，此處負責執行。
# ==========================================

from PyQt6.QtWidgets import QApplication, QLineEdit
from PyQt6.QtCore import Qt, QEvent, QPoint, QRect, QUrl, QMimeData, QTimer
from PyQt6.QtGui import QKeyEvent


class ActionHandler:
    """
    MainWindow 的熱鍵與事件動作執行器。

    【外部依賴】
    初始化時需傳入 MainWindow 實例 (self.w)，以存取下列屬性：
      - self.w.config            : ConfigManager
      - self.w.input             : QLineEdit (搜尋框)
      - self.w.list_view         : GalleryListView (畫廊)
      - self.w.preview_overlay   : PreviewOverlay
      - self.w.inspector_panel   : InspectorPanel
      - self.w.history_list      : QListWidget (歷史浮動面板)
      - self.w.status            : QLabel (狀態列)
      - self.w.model             : SearchResultsModel
      - self.w.is_ocr_locked     : bool
      - self.w.toggle_preview()  : method
      - self.w.show_history_popup() : method
    """

    def __init__(self, main_window):
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
            self.w.input.clearFocus()
            self.w.list_view.clearSelection()
            return True
        return False

    # ------------------------------------------------------------------
    #  Shift 按下：OCR 紅框顯示
    # ------------------------------------------------------------------
    def handle_shift_press(self, ocr_mode):
        if self.w.preview_overlay.isVisible():
            if ocr_mode == "toggle":
                self.w.is_ocr_locked = not self.w.is_ocr_locked
                self.w.preview_overlay.set_ocr_visible(self.w.is_ocr_locked)
            else:
                self.w.preview_overlay.set_ocr_visible(True)
        return True

    # ------------------------------------------------------------------
    #  Shift 放開：OCR 紅框隱藏 (僅 hold 模式)
    # ------------------------------------------------------------------
    def handle_shift_release(self, ocr_mode):
        if self.w.preview_overlay.isVisible():
            if ocr_mode != "toggle":
                self.w.preview_overlay.set_ocr_visible(False)
        return True

    # ------------------------------------------------------------------
    #  WASD：畫廊導航
    # ------------------------------------------------------------------
    def handle_wasd(self, key, nav_mode):
        is_preview_active = self.w.preview_overlay.isVisible()

        # 模式 1：按 WASD 時關閉預覽
        if is_preview_active and nav_mode == "close":
            self.w.preview_overlay.hide()
            self.w.is_ocr_locked = False

        self.w.list_view.setFocus()

        key_map = {
            Qt.Key.Key_W: Qt.Key.Key_Up,
            Qt.Key.Key_S: Qt.Key.Key_Down,
            Qt.Key.Key_A: Qt.Key.Key_Left,
            Qt.Key.Key_D: Qt.Key.Key_Right,
        }
        nav_key = key_map.get(key)
        if nav_key is not None:
            self._send_nav_key(nav_key)
        return True

    # ------------------------------------------------------------------
    #  Space：切換預覽
    # ------------------------------------------------------------------
    def handle_space(self):
        self.w.toggle_preview()
        return True

    # ------------------------------------------------------------------
    #  Ctrl+C：智慧檔案路徑複製 + Toast
    # ------------------------------------------------------------------
    def handle_copy(self):
        if self.w.input.hasFocus():
            return False  # 搜尋框內的 Ctrl+C 交給系統處理
        if QApplication.activeWindow() != self.w:
            return False

        selected_indexes = self.w.list_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            return False

        # 記住狀態文字 (用於 Toast 還原)
        current_status = self.w.status.text()
        if not getattr(self.w, '_is_toast_active', False):
            self.w._previous_status_text = current_status
        self.w._is_toast_active = True

        # 打包成實體檔案路徑
        mime_data = QMimeData()
        urls = []
        for idx in selected_indexes:
            item = idx.data(Qt.ItemDataRole.UserRole)
            if item and item.path:
                urls.append(QUrl.fromLocalFile(item.path))

        mime_data.setUrls(urls)
        QApplication.clipboard().setMimeData(mime_data)

        # Toast 提示
        count = len(urls)
        if count == 1:
            self.w.status.setText("已複製 1 個檔案到剪貼簿")
        else:
            self.w.status.setText(f"已複製 {count} 個檔案到剪貼簿")

        def restore_status():
            self.w.status.setText(getattr(self.w, '_previous_status_text', "System Ready"))
            self.w._is_toast_active = False

        QTimer.singleShot(1500, restore_status)
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
                self.w.history_list.hide()

        # 點擊搜尋框 → 彈出歷史紀錄
        if obj == self.w.input:
            self.w.show_history_popup()

    # ------------------------------------------------------------------
    #  內部輔助：發送模擬按鍵給 ListView
    # ------------------------------------------------------------------
    def _send_nav_key(self, key_code):
        press = QKeyEvent(QEvent.Type.KeyPress, key_code, Qt.KeyboardModifier.NoModifier)
        release = QKeyEvent(QEvent.Type.KeyRelease, key_code, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.w.list_view, press)
        QApplication.sendEvent(self.w.list_view, release)

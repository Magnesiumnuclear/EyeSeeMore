# ==========================================
#  search_capsule.py
#  EyeSeeMore - 頂部膠囊式搜尋組件
#  從 main_window_ui.py 中提取的搜尋列 + OCR 切換 + 歷史清單。
#
#  【訊號中繼模式 (Signal Relay)】
#  本組件不直接執行搜尋邏輯，僅在使用者操作時發射訊號，
#  由 MainWindow 負責接線與最終調度。
# ==========================================

from PyQt6.QtWidgets import (
    QHBoxLayout, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QLabel, QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt6.QtGui import QColor, QCursor

from ui.widgets.base import BaseToggleWidget


class _HistoryItemWidget(BaseToggleWidget):
    """搜尋歷史清單中的單一項目 (內部組件，不對外公開)"""

    def __init__(self, text, search_callback, delete_callback):
        super().__init__()
        self.text = text
        self.search_callback = search_callback
        self.delete_callback = delete_callback

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 5, 0)

        self.label = QLabel(text)
        self.label.setStyleSheet("background: transparent;")
        self.label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.label.mousePressEvent = self._on_label_clicked
        layout.addWidget(self.label, stretch=1)

        self.del_btn = QPushButton("x")
        self.del_btn.setObjectName("HistoryDelBtn")
        self.del_btn.setFixedSize(28, 28)
        self.del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.del_btn.clicked.connect(self._on_delete_clicked)
        layout.addWidget(self.del_btn)

    def _on_label_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.search_callback(self.text)

    def _on_delete_clicked(self):
        self.delete_callback(self.text)


class SearchCapsule(BaseToggleWidget):
    """
    膠囊式搜尋元件：包含搜尋框、OCR 切換按鈕與歷史下拉清單。

    【發射訊號】
    - searchRequested(dict)
        Payload: {
            "query":   str,      # 使用者輸入的搜尋字串
            "use_ocr": bool,     # OCR 開關目前狀態
        }
        觸發條件：Enter 鍵 或 歷史項目點擊

    - modeChanged(str)
        Payload: "ocr_on" | "ocr_off"
        觸發條件：btn_ocr_toggle 狀態切換

    - errorOccurred(str)   ← 繼承自 BaseToggleWidget
    """

    searchRequested = pyqtSignal(dict)
    modeChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.search_history: list[str] = []

        # ----- 膠囊外框 -----
        self.setMaximumWidth(550)
        self.setMinimumWidth(300)
        self.setFixedHeight(38)
        self.setObjectName("SearchCapsule")

        capsule_layout = QHBoxLayout(self)
        capsule_layout.setContentsMargins(15, 0, 5, 0)
        capsule_layout.setSpacing(5)

        # ----- 搜尋框 -----
        self.input = QLineEdit()
        self.input.setPlaceholderText("Search images...")
        self.input.setStyleSheet(
            "QLineEdit { background: transparent; border: none; font-size: 14px; }"
        )
        self.input.returnPressed.connect(self._on_return_pressed)
        capsule_layout.addWidget(self.input, stretch=1)

        # ----- OCR 開關按鈕 -----
        self.btn_ocr_toggle = QPushButton("[T]")
        self.btn_ocr_toggle.setCheckable(True)
        self.btn_ocr_toggle.setChecked(True)
        self.btn_ocr_toggle.setFixedSize(30, 30)
        self.btn_ocr_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ocr_toggle.setToolTip("啟用/停用 OCR 文字檢索")
        self.btn_ocr_toggle.setObjectName("OcrToggle")
        self.btn_ocr_toggle.toggled.connect(self._on_ocr_toggled)
        capsule_layout.addWidget(self.btn_ocr_toggle)

        # ----- 歷史清單 (浮動，懶初始化) -----
        self._history_list: QListWidget | None = None

    # ==================================================================
    #  公開介面  (供 MainWindow 呼叫)
    # ==================================================================
    def text(self) -> str:
        """取得目前搜尋框的文字 (去頭尾空白)"""
        return self.input.text().strip()

    def setText(self, value: str):
        """設定搜尋框文字"""
        self.input.setText(value)

    def clearFocus(self):
        """清除搜尋框焦點"""
        self.input.clearFocus()

    def set_history(self, history: list[str]):
        """從外部注入歷史紀錄 (MainWindow 載入後呼叫)"""
        self.search_history = history

    def get_history_list_widget(self) -> QListWidget:
        """取得歷史下拉清單 Widget (供外部定位用)"""
        return self._ensure_history_list()

    # ==================================================================
    #  歷史下拉清單
    # ==================================================================
    def _ensure_history_list(self) -> QListWidget:
        """懶初始化歷史清單 Widget，掛載在最頂層 MainWindow 上"""
        if self._history_list is None:
            top = self.window()
            self._history_list = QListWidget(top)
            self._history_list.setObjectName("HistoryList")
            self._history_list.hide()
            self._history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(20)
            shadow.setColor(QColor(0, 0, 0, 100))
            shadow.setOffset(0, 4)
            self._history_list.setGraphicsEffect(shadow)
        return self._history_list

    def show_history_popup(self):
        """顯示搜尋歷史下拉清單"""
        if not self.search_history:
            hl = self._ensure_history_list()
            hl.hide()
            return

        hl = self._ensure_history_list()
        hl.clear()

        # 標題
        title_item = QListWidgetItem()
        title_widget = QLabel(" Recent Searches")
        title_widget.setStyleSheet(
            "color: #888888; font-size: 13px; font-weight: bold; background: transparent;"
        )
        title_item.setFlags(Qt.ItemFlag.NoItemFlags)
        title_item.setSizeHint(QSize(0, 36))
        hl.addItem(title_item)
        hl.setItemWidget(title_item, title_widget)

        for text in self.search_history:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 44))
            widget = _HistoryItemWidget(
                text,
                search_callback=self._on_history_search,
                delete_callback=self._on_history_delete,
            )
            hl.addItem(item)
            hl.setItemWidget(item, widget)

        # 定位
        top = self.window()
        input_pos = self.input.mapTo(top, QPoint(0, 0))
        list_height = min(320, 36 + (len(self.search_history) * 44) + 10)
        hl.setGeometry(
            input_pos.x(),
            input_pos.y() + self.input.height() + 8,
            self.input.width(),
            list_height,
        )
        hl.show()
        hl.raise_()

    def hide_history(self):
        """隱藏歷史下拉清單"""
        if self._history_list is not None:
            self._history_list.hide()

    # ==================================================================
    #  內部 Slot
    # ==================================================================
    def _on_return_pressed(self):
        """Enter 鍵觸發：組裝 payload 並發射 searchRequested"""
        q = self.input.text().strip()
        if q:
            self.searchRequested.emit({
                "query": q,
                "use_ocr": self.btn_ocr_toggle.isChecked(),
            })

    def _on_ocr_toggled(self, checked: bool):
        self.modeChanged.emit("ocr_on" if checked else "ocr_off")

    def _on_history_search(self, text: str):
        """歷史項目被點擊：填入搜尋框並發射 searchRequested"""
        self.input.setText(text)
        self.hide_history()
        self.searchRequested.emit({
            "query": text,
            "use_ocr": self.btn_ocr_toggle.isChecked(),
        })

    def _on_history_delete(self, text: str):
        """歷史項目刪除鈕點擊"""
        if text in self.search_history:
            self.search_history.remove(text)
        self.show_history_popup()

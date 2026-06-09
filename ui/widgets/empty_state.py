from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QFont


class EmptyStateOverlay(QWidget):
    """畫廊空狀態診斷覆蓋層 — 浮動顯示於 list_view 正上方"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyStateOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QWidget()
        card.setObjectName("EmptyStateCard")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_lbl = QLabel()
        self._icon_lbl.setObjectName("EmptyStateIcon")
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_font = QFont()
        icon_font.setPointSize(36)
        self._icon_lbl.setFont(icon_font)

        self._msg_lbl = QLabel()
        self._msg_lbl.setObjectName("EmptyStateMsg")
        self._msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setMaximumWidth(360)

        card_layout.addWidget(self._icon_lbl)
        card_layout.addWidget(self._msg_lbl)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def show_message(self, icon: str, message: str):
        self._icon_lbl.setText(icon)
        self._msg_lbl.setText(message)
        if self.parent():
            self.resize(self.parent().size())
        self.raise_()
        self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            self.resize(self.parent().size())

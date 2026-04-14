"""Performance / WIP settings page (placeholder)."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QPushButton
from PyQt6.QtCore import Qt


class PerformancePage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("performance", "page_title", "⚡ 效能調整 (Performance)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        layout.addWidget(sep)

        btn_wip = QPushButton(trans.t("performance", "wip_text", "🚧 施工中：動畫效果與系統資源控制"))
        btn_wip.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_wip.setObjectName("WipButton")
        layout.addWidget(btn_wip)
        layout.addStretch(1)

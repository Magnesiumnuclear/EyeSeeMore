# ==========================================
#  elided_label.py
#  EyeSeeMore - 自動省略文字的 QLabel
#
#  當可用寬度不足時以省略號截斷，並透過 ToolTip 顯示完整內容。
#  覆寫 minimumSizeHint() 讓佈局可以將此 Label 縮到 0 寬，
#  同時保留 Preferred policy，有多餘空間時仍會索取完整文字寬度。
# ==========================================

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt, QSize


class ElidedLabel(QLabel):
    """
    自動省略文字的 QLabel。

    與標準 QLabel 相比的差異：
    - minimumSizeHint() 水平寬度固定回傳 0，讓佈局在空間不足時可將此
      Label 縮到任意寬度，而不會撐大視窗最小寬度。
    - SizePolicy 維持預設 Preferred，有多餘空間時仍會要求完整文字寬度。
    - resizeEvent 時重算省略文字，縮短到實際可用寬度。
    - 自動設定 ToolTip 為完整文字（有省略時才顯示）。
    - 支援 ElideLeft / ElideMiddle / ElideRight（預設 ElideRight）。
    """

    def __init__(self, text: str = "", elide: Qt.TextElideMode = Qt.TextElideMode.ElideRight, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._elide = elide
        if text:
            self._refresh()

    # ------------------------------------------------------------------
    #  覆寫：讓佈局可以把此 Label 縮到寬度 0（不再撐大視窗最小值）
    # ------------------------------------------------------------------
    def minimumSizeHint(self) -> QSize:
        base = super().minimumSizeHint()
        h = base.height() if base.isValid() else 0
        return QSize(0, h)

    # ------------------------------------------------------------------
    #  公開介面
    # ------------------------------------------------------------------
    def setText(self, text: str) -> None:  # type: ignore[override]
        self._full_text = text
        self._refresh()

    def fullText(self) -> str:
        """取得完整（未省略）文字"""
        return self._full_text

    # ------------------------------------------------------------------
    #  內部
    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        w = self.width()
        if w <= 0:
            # 尚未佈局完成，先暫存原始文字；resizeEvent 後再更新
            super().setText(self._full_text)
            return
        fm = self.fontMetrics()
        elided = fm.elidedText(self._full_text, self._elide, w)
        super().setText(elided)
        # 只在實際有省略時顯示 tooltip
        self.setToolTip(self._full_text if elided != self._full_text else "")

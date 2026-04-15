# ==========================================
#  base.py
#  EyeSeeMore - UI 組件基類
#  所有可切換的自訂 Widget 皆繼承此類，統一持有 errorOccurred 訊號。
# ==========================================

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import pyqtSignal


class BaseToggleWidget(QWidget):
    """
    所有 EyeSeeMore 自訂 UI 組件的基類。

    【全域錯誤協議】
    子類別在發生非致命錯誤時，應發射 errorOccurred(str)，
    由 MainWindow 統一轉發至 status bar 顯示。

    接線範例 (MainWindow.__init__)：
        child.errorOccurred.connect(self.status.setText)
    """

    errorOccurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

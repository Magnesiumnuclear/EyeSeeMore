import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, 
    QFileIconProvider, QStyle, QHBoxLayout, QFrame
)
from PyQt6.QtCore import QFileInfo, Qt, QSize

class IconTestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("System Icon Test")
        self.resize(500, 300)
        self.setStyleSheet("background-color: #1e1e1e; color: white; font-size: 16px;")

        layout = QHBoxLayout(self)

        # --- 1. 左邊：顯示 Qt 內建的通用圖示 (你原本遇到的狀況) ---
        layout.addWidget(self.create_icon_panel(
            "Qt Default (SP_FileIcon)", 
            self.get_qt_default_icon()
        ))

        # --- 2. 右邊：顯示系統對 .jpg 的定義 (你要的藍色圖片) ---
        layout.addWidget(self.create_icon_panel(
            "System .jpg Icon", 
            self.get_system_jpg_icon()
        ))

    def get_qt_default_icon(self):
        """取得 Qt 內建的灰色文件圖示"""
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def get_system_jpg_icon(self):
        """
        核心邏輯：
        使用 QFileIconProvider 詢問系統 'test.jpg' 該用什麼圖示。
        即便檔案不存在，Windows 仍會根據副檔名回傳關聯圖示。
        """
        provider = QFileIconProvider()
        # 建立一個虛擬的檔案路徑資訊
        info = QFileInfo("dummy_template.jpg") 
        return provider.icon(info)

    def create_icon_panel(self, title, icon):
        """建立一個包含標題與大圖示的面板"""
        panel = QFrame()
        panel.setStyleSheet("background-color: #2d2d2d; border-radius: 10px;")
        v_layout = QVBoxLayout(panel)
        
        # 標題
        lbl_title = QLabel(title)
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("font-weight: bold; color: #cccccc; margin-bottom: 10px;")
        
        # 圖示 (設定為 128x128 大圖以便觀察)
        lbl_icon = QLabel()
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = icon.pixmap(128, 128) # 繪製大尺寸
        lbl_icon.setPixmap(pixmap)

        v_layout.addWidget(lbl_title)
        v_layout.addWidget(lbl_icon)
        return panel

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IconTestWindow()
    window.show()
    sys.exit(app.exec())
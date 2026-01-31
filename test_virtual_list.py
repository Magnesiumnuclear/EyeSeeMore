import sys
import os
import random
from pathlib import Path
from collections import OrderedDict

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QRect, 
    QRunnable, QThreadPool, pyqtSignal, QObject, QFileInfo # [新增] QFileInfo
)
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QPixmap, QImageReader, 
    QFont, QBrush, QPen, QFontMetrics, QIcon
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListView, QVBoxLayout, 
    QWidget, QPushButton, QStyledItemDelegate, QLabel, 
    QStyle, QFileIconProvider # [新增] QFileIconProvider
)

# --- 設定參數 ---
IMAGE_FOLDER = r"D:\software\image\TO"  # 指定資料夾路徑
ITEM_WIDTH = 200
ITEM_HEIGHT = 240
THUMBNAIL_HEIGHT = 160
CACHE_SIZE = 50  # 記憶體中最多保留多少張縮圖
BACKGROUND_COLOR = "#1e1e1e"
SCORE_COLOR_HIGH = "#60cdff"  # > 0.3
SCORE_COLOR_LOW = "#999999"   # <= 0.3
HOVER_COLOR = "#333333"       # 懸停背景色

# --- 輔助類別：非同步載入訊號 ---
class WorkerSignals(QObject):
    """定義 Worker 執行後的訊號"""
    result = pyqtSignal(str, QPixmap)  # filePath, pixmap

# --- 修正後的 ThumbnailLoader ---
class ThumbnailLoader(QRunnable):
    def __init__(self, file_path, target_size):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.signals = WorkerSignals()

    def run(self):
        try:
            reader = QImageReader(self.file_path)
            
            # 1. 讀取原始圖片的尺寸 (這步很快，不會讀取像素資料)
            orig_size = reader.size()
            
            if not orig_size.isValid():
                # 防止讀到損壞的標頭
                self.signals.result.emit(self.file_path, QPixmap())
                return

            # 2. 智慧計算縮放尺寸
            # 使用 KeepAspectRatioByExpanding：確保圖片縮小後"至少"能填滿 target_size
            # 例如：目標 200x160，原圖 1000x1000 -> 會算出 200x200 (寬度對齊，高度超出)
            # 例如：目標 200x160，原圖 1000x500  -> 會算出 320x160 (高度對齊，寬度超出)
            scaled_size = orig_size.scaled(
                self.target_size, 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding
            )
            
            # 3. 設定讀取尺寸 (這樣讀出來的圖片不會變形，且解析度剛好夠用)
            reader.setScaledSize(scaled_size)
            
            # 4. 針對部分含有旋轉資訊的 JPG (如手機直拍)，設定自動轉換
            reader.setAutoTransform(True)

            image = reader.read()
            
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self.signals.result.emit(self.file_path, pixmap)
            else:
                self.signals.result.emit(self.file_path, QPixmap())
                
        except Exception as e:
            print(f"Error loading {self.file_path}: {e}")

# --- 資料結構 ---
class ImageItem:
    def __init__(self, path: str, name: str, score: float):
        self.path = path
        self.name = name
        self.score = score

# --- Model (核心資料邏輯) ---
class AsyncImageModel(QAbstractListModel):
    # 新增訊號：用來通知 UI 更新載入進度 (已載入數量, 總數量)
    progress_updated = pyqtSignal(int, int)

    def __init__(self, image_folder):
        super().__init__()
        self.items = []
        self._thumbnail_cache = OrderedDict() # LRU Cache
        self._loading_set = set() 
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4) 
        
        self.load_data(image_folder)

    def load_data(self, folder_path):
        path = Path(folder_path)
        if not path.exists():
            print(f"錯誤: 資料夾 {folder_path} 不存在。")
            return

        extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        new_items = []
        
        for file in path.iterdir():
            if file.suffix.lower() in extensions:
                score = random.random()
                new_items.append(ImageItem(str(file), file.name, score))
        
        self.beginResetModel()
        self.items = new_items
        self.endResetModel()
        print(f"已載入 {len(self.items)} 張圖片資料。")

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.items)):
            return None

        item = self.items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.name
        
        elif role == Qt.ItemDataRole.UserRole:
            return item.score

        elif role == Qt.ItemDataRole.DecorationRole:
            # 檢查快取
            if item.path in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(item.path)
                return self._thumbnail_cache[item.path]
            
            # 觸發載入
            if item.path not in self._loading_set:
                self.request_thumbnail(item.path)
            
            # 回傳 None 代表尚未載入，Delegate 會處理預設圖
            return None

        return None

    def request_thumbnail(self, file_path):
        self._loading_set.add(file_path)
        target_size = QSize(ITEM_WIDTH, THUMBNAIL_HEIGHT)
        loader = ThumbnailLoader(file_path, target_size)
        loader.signals.result.connect(self.on_thumbnail_loaded)
        self.thread_pool.start(loader)

    def on_thumbnail_loaded(self, file_path, pixmap):
        if file_path in self._loading_set:
            self._loading_set.remove(file_path)

        if not pixmap.isNull():
            self._thumbnail_cache[file_path] = pixmap
            if len(self._thumbnail_cache) > CACHE_SIZE:
                self._thumbnail_cache.popitem(last=False)

            # 更新 UI 進度條
            self.progress_updated.emit(len(self._thumbnail_cache), len(self.items))

            # 通知 View 更新特定列
            for row, item in enumerate(self.items):
                if item.path == file_path:
                    idx = self.index(row, 0)
                    self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                    break

    def sort_by_score(self):
        self.layoutAboutToBeChanged.emit()
        self.items.sort(key=lambda x: x.score, reverse=True)
        self.layoutChanged.emit()

# --- Delegate (視覺繪製核心) ---
class ImageDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.padding = 10
        self.radius = 12
        self.font_name = QFont("Segoe UI", 10)
        self.font_score = QFont("Segoe UI", 9, QFont.Weight.Bold)
        
        # 改用 QFileIconProvider 抓取系統對 .jpg 的預設圖示
        provider = QFileIconProvider()
        info = QFileInfo("template.jpg")
        icon = provider.icon(info)
        
        # 設定預設圖示大小 (128x128 確保高解析度下清晰)
        self.placeholder_pixmap = icon.pixmap(128, 128)

    def sizeHint(self, option, index):
        return QSize(ITEM_WIDTH, ITEM_HEIGHT)

    def paint(self, painter: QPainter, option, index):
        if not index.isValid():
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        name = index.data(Qt.ItemDataRole.DisplayRole)
        score = index.data(Qt.ItemDataRole.UserRole)
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)

        # --- 1. 繪製背景 (Hover 效果) ---
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setBrush(QBrush(QColor(HOVER_COLOR)))
            painter.setPen(Qt.PenStyle.NoPen)
            bg_rect = QRect(option.rect)
            bg_rect.adjust(4, 4, -4, -4)
            painter.drawRoundedRect(bg_rect, 8, 8)
        
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor(SCORE_COLOR_HIGH), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sel_rect = QRect(option.rect)
            sel_rect.adjust(2, 2, -2, -2)
            painter.drawRoundedRect(sel_rect, 8, 8)

        # --- 2. 繪製圖片區 ---
        img_rect = QRect(
            option.rect.left() + self.padding,
            option.rect.top() + self.padding,
            ITEM_WIDTH - 2 * self.padding,
            THUMBNAIL_HEIGHT
        )

        # 底色
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#2d2d2d")))
        painter.drawRoundedRect(img_rect, self.radius, self.radius)

        # 建立圓角路徑
        path = QPainterPath()
        path.addRoundedRect(img_rect.x(), img_rect.y(), img_rect.width(), img_rect.height(), self.radius, self.radius)
        painter.setClipPath(path)

        if pixmap:
            # A. 圖片已載入：繪製圖片 (縮放並填滿)
            scaled_pixmap = pixmap.scaled(
                img_rect.size(), 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
                Qt.TransformationMode.SmoothTransformation
            )
            x_offset = (scaled_pixmap.width() - img_rect.width()) / 2
            y_offset = (scaled_pixmap.height() - img_rect.height()) / 2
            painter.drawPixmap(
                img_rect.left(), img_rect.top(), 
                scaled_pixmap, 
                int(x_offset), int(y_offset), 
                img_rect.width(), img_rect.height()
            )
        else:
            # B. 圖片未載入：繪製 Windows 系統 .jpg 圖示 (Placeholder)
            painter.setOpacity(0.5)
            
            # [修正重點] 使用 QStyle.alignedRect 計算完美置中的座標
            # 這會根據 img_rect 的大小，自動算出 placeholder 應該放在哪裡才能置中
            centered_rect = QStyle.alignedRect(
                Qt.LayoutDirection.LeftToRight, # 由左至右佈局
                Qt.AlignmentFlag.AlignCenter,   # 置中對齊
                self.placeholder_pixmap.size(), # 內容物大小
                img_rect                        # 容器範圍
            )
            
            # 確保不會畫出界 (雖然 128px 小於 160px 通常沒問題，但為了安全可加上這行)
            # 如果圖示比框框大，這裡可以再加 scaled 邏輯，但在這裡我們假設 icon 固定 128
            painter.drawPixmap(centered_rect, self.placeholder_pixmap)
            
            painter.setOpacity(1.0) # 還原

        painter.setClipping(False)

        # --- 3. 繪製文字 ---
        text_rect = QRect(
            option.rect.left() + self.padding,
            img_rect.bottom() + 4,
            ITEM_WIDTH - 2 * self.padding,
            20
        )
        
        painter.setFont(self.font_name)
        painter.setPen(QColor("white"))
        
        name_str = str(name) if name is not None else ""
        elided_text = fm = QFontMetrics(self.font_name).elidedText(name_str, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_text)

        # --- 4. 繪製分數 ---
        score_rect = QRect(
            option.rect.left() + self.padding,
            text_rect.bottom() + 2,
            ITEM_WIDTH - 2 * self.padding,
            20
        )
        
        painter.setFont(self.font_score)
        current_score = float(score) if score is not None else 0.0
        
        if current_score > 0.3:
            painter.setPen(QColor(SCORE_COLOR_HIGH))
        else:
            painter.setPen(QColor(SCORE_COLOR_LOW))
            
        score_text = f"Score: {current_score:.4f}"
        painter.drawText(score_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, score_text)

        painter.restore()

# --- 主視窗 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Search Virtual List Test")
        self.resize(1000, 800)
        
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {BACKGROUND_COLOR}; }}
            QListView {{ 
                background-color: {BACKGROUND_COLOR}; 
                border: none;
                outline: none;
            }}
            QPushButton {{
                background-color: #333333;
                color: white;
                border: 1px solid #555555;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: #444444; }}
            QLabel {{ color: #cccccc; font-size: 14px; padding-left: 10px; }}
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Top Bar
        top_bar = QWidget()
        top_layout = QVBoxLayout(top_bar)
        
        self.btn_sort = QPushButton("Sort by Score (Descending)")
        self.btn_sort.clicked.connect(self.sort_data)
        
        self.lbl_status = QLabel("Loaded: 0 / Total: 0")
        
        top_layout.addWidget(self.btn_sort)
        top_layout.addWidget(self.lbl_status)
        
        layout.addWidget(top_bar)

        # List View
        self.list_view = QListView()
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSpacing(10)
        self.list_view.setMouseTracking(True)

        self.model = AsyncImageModel(IMAGE_FOLDER)
        self.model.progress_updated.connect(self.update_status)
        
        self.delegate = ImageDelegate()
        
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)

        layout.addWidget(self.list_view)
        
        self.lbl_status.setText(f"Loaded: 0 / Total: {self.model.rowCount()}")

    def sort_data(self):
        self.model.sort_by_score()

    def update_status(self, loaded_count, total_count):
        self.lbl_status.setText(f"Loaded (Cached): {loaded_count} / Total: {total_count}")

# --- Entry Point ---
if __name__ == "__main__":
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    app = QApplication(sys.argv)
    QImageReader.setAllocationLimit(256) 
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
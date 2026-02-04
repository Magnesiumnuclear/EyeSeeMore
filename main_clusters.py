import sys
import os
import sqlite3
import random
from collections import OrderedDict, deque
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QRect, 
    QRunnable, QThreadPool, pyqtSignal, QObject, QFileInfo,
    QTimer, QPoint
)
from PyQt6.QtGui import (
    QColor, QPainter, QPainterPath, QPixmap, QImageReader, 
    QFont, QBrush, QPen, QFontMetrics, QIcon, QImage
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListView, QVBoxLayout, 
    QWidget, QPushButton, QStyledItemDelegate, QLabel, 
    QStyle, QFileIconProvider
)

# --- 設定參數 ---
DB_PATH = "images.db"
ITEM_WIDTH = 240   # 卡片總寬
ITEM_HEIGHT = 200  # 卡片總高
THUMB_WIDTH = 220  # 縮圖顯示寬度
THUMB_HEIGHT = 160 # 縮圖顯示高度
CACHE_SIZE = 200   # L1 Cache (加大以應付滾動)
BATCH_INTERVAL = 30 # 批次更新間隔 (ms)

# 顏色設定
COLOR_BG = "#1e1e1e"
COLOR_CARD_BG = "#2d2d2d"
COLOR_TEXT = "#eeeeee"
COLOR_BBOX = QColor("#00ff00") # YOLO 框顏色 (綠色)
COLOR_LABEL_BG = QColor(0, 0, 0, 150) # 標籤背景半透明黑

# --- 資料結構 ---
class ImageItem:
    """
    輕量化資料物件，預先計算好所有顯示所需的字串，
    避免在 paint 或 data 中做 Python 運算 (Boundary Tax 優化)。
    """
    __slots__ = ('path', 'name', 'detections', 'display_name', 'has_detections')

    def __init__(self, path: str, name: str, detections: list):
        self.path = path
        self.name = name
        self.detections = detections # List of (label, confidence, [x1, y1, x2, y2])
        self.has_detections = len(detections) > 0
        
        # Pre-calculation: 預先處理好顯示文字
        self.display_name = name
        if len(self.display_name) > 20:
            self.display_name = self.display_name[:17] + "..."

# --- Worker Signals ---
class WorkerSignals(QObject):
    result = pyqtSignal(str, QImage) # 傳回 QImage 而非 QPixmap，避免在 Thread 中操作 GPU 資源

# --- 高效能圖片載入器 ---
class ThumbnailLoader(QRunnable):
    """
    負責：
    1. 讀取圖片
    2. 縮放到目標尺寸 (Pre-scaling)
    3. 畫上 YOLO BBox (Pre-drawing)
    4. 轉為 GPU 友善格式
    """
    def __init__(self, item: ImageItem, target_size: QSize):
        super().__init__()
        self.item = item
        self.target_size = target_size
        self.signals = WorkerSignals()
        self.is_cancelled = False # Task Cancellation flag

    def run(self):
        if self.is_cancelled: return

        try:
            reader = QImageReader(self.item.path)
            
            # 1. 讀取原始尺寸 (為了計算 BBox 的縮放比例)
            orig_size = reader.size()
            if not orig_size.isValid(): return

            # 2. 計算縮放後的尺寸 (KeepAspectRatio)
            # 我們縮放到剛好能塞進 target_size
            scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio)
            
            # 設定 Reader 直接讀取縮放後的圖片 (極大節省 IO 與記憶體)
            reader.setScaledSize(scaled_size)
            reader.setAutoTransform(True) # 處理 EXIF 旋轉

            if self.is_cancelled: return
            image = reader.read()
            
            if image.isNull(): return

            # 3. 格式優化：轉為 Format_ARGB32_Premultiplied
            # 這是 Qt 繪圖引擎最快的格式，避免主執行緒繪製時發生隱式轉換
            if image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

            # 4. 如果有 YOLO 偵測資料，直接畫在圖片上 (Pre-drawing)
            # 這樣主執行緒的 paint 就只需要畫一張圖，不用畫一堆框和字
            if self.item.has_detections:
                self._draw_detections(image, orig_size, scaled_size)

            if not self.is_cancelled:
                self.signals.result.emit(self.item.path, image)

        except Exception as e:
            # print(f"Error: {e}") 
            pass

    def _draw_detections(self, image: QImage, orig_size: QSize, scaled_size: QSize):
        """在 Worker Thread 裡直接把框畫死在圖上"""
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 計算縮放比例
        scale_x = scaled_size.width() / orig_size.width()
        scale_y = scaled_size.height() / orig_size.height()

        pen = QPen(COLOR_BBOX)
        pen.setWidth(2)
        painter.setPen(pen)
        
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)

        for label, conf, bbox in self.item.detections:
            if not bbox: continue
            
            # 解析 bbox (x1, y1, x2, y2)
            try:
                x1, y1, x2, y2 = map(int, bbox.split(','))
            except: continue

            # 轉換座標到縮圖尺寸
            sx1 = int(x1 * scale_x)
            sy1 = int(y1 * scale_y)
            sx2 = int(x2 * scale_x)
            sy2 = int(y2 * scale_y)
            
            rect = QRect(QPoint(sx1, sy1), QPoint(sx2, sy2))
            
            # 畫框
            painter.drawRect(rect)
            
            # 畫標籤背景與文字
            label_text = f"{label} {conf:.2f}"
            fm = QFontMetrics(font)
            text_w = fm.horizontalAdvance(label_text)
            text_h = fm.height()
            
            # 標籤位置 (框的左上角)
            label_rect = QRect(sx1, sy1 - text_h, text_w + 4, text_h)
            
            # 防止標籤畫出圖片上緣
            if label_rect.top() < 0:
                label_rect.moveTop(sy1)
            
            painter.fillRect(label_rect, COLOR_LABEL_BG)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label_text)
            
            # 還原筆刷顏色給下一個框
            painter.setPen(pen)

        painter.end()

# --- Model ---
class AsyncYoloModel(QAbstractListModel):
    def __init__(self, db_path):
        super().__init__()
        self.items = []
        self.db_path = db_path
        
        # 效能優化：雙層 Cache
        # key: file_path, value: QPixmap
        self._thumbnail_cache = OrderedDict() 
        
        # 任務管理
        self._active_tasks = {} # path -> ThumbnailLoader
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(os.cpu_count() or 4)
        
        # 批次更新 (Signal Storm Prevention)
        self._batch_queue = deque()
        self._batch_timer = QTimer()
        self._batch_timer.setInterval(BATCH_INTERVAL)
        self._batch_timer.timeout.connect(self._process_batch)
        self._batch_timer.start()

        # 預設圖示 (Placeholder)
        self.placeholder_pixmap = self._create_placeholder()

        self.load_data_from_db()

    def _create_placeholder(self):
        """預先生成好 Placeholder，避免 paint 重複生成"""
        pix = QPixmap(THUMB_WIDTH, THUMB_HEIGHT)
        pix.fill(QColor(COLOR_CARD_BG))
        painter = QPainter(pix)
        painter.setPen(QColor("#555"))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "Loading...")
        painter.end()
        return pix

    def load_data_from_db(self):
        """從 SQLite 讀取所有資料 (Metadata)"""
        if not os.path.exists(self.db_path):
            print(f"Database not found: {self.db_path}")
            return

        print("Loading metadata from DB...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. 讀取 YOLO 物件資料
        # 結構: {parent_path: [(label, conf, bbox), ...]}
        detections_map = {}
        try:
            cursor.execute("SELECT parent_path, label, confidence, bbox FROM sub_objects")
            for row in cursor.fetchall():
                p_path, label, conf, bbox = row
                if p_path not in detections_map:
                    detections_map[p_path] = []
                detections_map[p_path].append((label, conf, bbox))
        except sqlite3.OperationalError:
            print("Warning: sub_objects table not found or empty.")

        # 2. 讀取圖片資料
        new_items = []
        cursor.execute("SELECT file_path, filename FROM images")
        rows = cursor.fetchall()
        
        for p_path, fname in rows:
            dets = detections_map.get(p_path, [])
            new_items.append(ImageItem(p_path, fname, dets))
        
        conn.close()
        
        self.beginResetModel()
        self.items = new_items
        self.endResetModel()
        print(f"Loaded {len(self.items)} items.")

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        
        # 直接存取 List，不做任何運算 (Boundary Tax Optimization)
        item = self.items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.display_name # 預先計算好的字串
        
        elif role == Qt.ItemDataRole.DecorationRole:
            # L1 Cache Check
            if item.path in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(item.path) # LRU update
                return self._thumbnail_cache[item.path]
            
            # Request Loading
            self._request_thumbnail(item)
            return self.placeholder_pixmap # 立即返回佔位圖

        return None

    def _request_thumbnail(self, item):
        """啟動載入任務"""
        if item.path in self._active_tasks:
            return # 已經在載入了
        
        # 建立任務
        task = ThumbnailLoader(item, QSize(THUMB_WIDTH, THUMB_HEIGHT))
        task.signals.result.connect(self._on_thumbnail_loaded)
        
        self._active_tasks[item.path] = task
        self.thread_pool.start(task)

    def _on_thumbnail_loaded(self, path, image):
        """Worker 完成後的回呼，將結果放入佇列"""
        self._batch_queue.append((path, image))

    def _process_batch(self):
        """批次將 Queue 中的圖片轉為 Pixmap 並更新 UI"""
        if not self._batch_queue:
            return

        # 一次處理最多 20 張，避免畫面凍結
        count = 0
        limit = 20
        
        while self._batch_queue and count < limit:
            path, image = self._batch_queue.popleft()
            
            # 從 Active Tasks 移除
            if path in self._active_tasks:
                del self._active_tasks[path]
            
            # Texture Upload (QImage -> QPixmap) 發生在這裡
            pixmap = QPixmap.fromImage(image)
            
            # Update Cache
            self._thumbnail_cache[path] = pixmap
            if len(self._thumbnail_cache) > CACHE_SIZE:
                self._thumbnail_cache.popitem(last=False)
            
            # 找到對應的 Row 進行更新
            # 這裡簡單掃描，若有效能問題可建立 path->row 的索引
            # 但因為只有 visible items 會觸發 data()，這裡只更新 cache 其實就夠了
            # View 會在下次 paint 時自動拿到 cache 裡的圖
            # 為了強制重繪，我們還是發個訊號比較保險
            
            # 優化：我們不 iterate 全部，我們只通知 Layout 更新
            # 實際上，Qt View 如果正在顯示該 item，會定期呼叫 data
            # 為了即時性，我們還是發出 dataChanged
            for row, item in enumerate(self.items):
                if item.path == path:
                    idx = self.index(row, 0)
                    self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                    break
            
            count += 1

# --- Delegate ---
class OptimizedDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.font = QFont("Segoe UI", 10)
        self.bg_brush = QBrush(QColor(COLOR_CARD_BG))
        self.text_color = QColor(COLOR_TEXT)

    def sizeHint(self, option, index):
        # 配合 setGridSize，這裡其實不太會被呼叫，但還是回傳固定值
        return QSize(ITEM_WIDTH, ITEM_HEIGHT)

    def paint(self, painter: QPainter, option, index):
        """
        極致優化的 Paint：
        1. 只做 blit (drawPixmap)
        2. 不做縮放運算 (Worker 已做)
        3. 不做文字佈局計算 (Model 已做)
        """
        if not index.isValid(): return

        # 1. 取得資料
        # 注意：這裡拿到的 Pixmap 已經是加上 YOLO 框 且 縮放好的
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)
        name = index.data(Qt.ItemDataRole.DisplayRole)

        rect = option.rect
        
        # 2. 畫背景卡片 (簡單填色，不做圓角或複雜漸層以求速度)
        # 內縮一點點做間距
        card_rect = rect.adjusted(5, 5, -5, -5)
        painter.fillRect(card_rect, self.bg_brush)
        
        # 3. 畫圖 (Texture Blit - 最快操作)
        if pixmap:
            # 計算置中位置 (雖然 Worker 已經縮放好，但可能長寬比不同)
            # 這裡只做位移運算，不做 scale
            x = card_rect.x() + (card_rect.width() - pixmap.width()) // 2
            y = card_rect.y() + 10 # 上方留白
            painter.drawPixmap(x, y, pixmap)

        # 4. 畫文字
        text_rect = QRect(card_rect.left(), card_rect.bottom() - 30, card_rect.width(), 25)
        painter.setPen(self.text_color)
        painter.setFont(self.font)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, name)
        
        # 5. 處理選取狀態 (簡單畫個框)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(QColor("#60cdff"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(card_rect)

# --- Main Window ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YOLO DB Viewer - Ultra Optimized")
        self.resize(1200, 800)
        
        self.setStyleSheet(f"QMainWindow {{ background-color: {COLOR_BG}; }}")

        # Setup List View
        self.list_view = QListView()
        self.list_view.setStyleSheet(f"""
            QListView {{ 
                background-color: {COLOR_BG}; 
                border: none; 
            }}
        """)
        
        # 關鍵佈局優化：固定 Grid 大小
        # 這讓 Qt 不用去計算每個 Item 的大小，滾動效能提升 10 倍
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setGridSize(QSize(ITEM_WIDTH, ITEM_HEIGHT))
        self.list_view.setUniformItemSizes(True)
        
        # 增加滾動平滑度
        self.list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)

        # Model & Delegate
        self.model = AsyncYoloModel(DB_PATH)
        self.delegate = OptimizedDelegate()
        
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)

        self.setCentralWidget(self.list_view)
        
        # 狀態列
        self.status_label = QLabel(f"Total: {self.model.rowCount()}")
        self.status_label.setStyleSheet("color: #888; padding: 5px;")
        self.statusBar().addWidget(self.status_label)

if __name__ == "__main__":
    # 高 DPI 設定
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    
    app = QApplication(sys.argv)
    
    # 增加圖片讀取記憶體限制 (避免讀取超大圖時崩潰)
    QImageReader.setAllocationLimit(512)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
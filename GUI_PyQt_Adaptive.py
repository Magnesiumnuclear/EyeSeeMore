import sys
import os
import time
import pickle
import threading
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize
from PyQt6.QtGui import QPixmap, QImage, QCursor

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
THUMBNAIL_SIZE = (220, 220)
CARD_SIZE = (230, 270) # 卡片固定大小
MIN_SPACING = 20       # 最小間距 (低於這個值就會強制換行)
WINDOW_TITLE = "Local AI Search (Adaptive Grid Edition)"
# ----------------

DARK_STYLESHEET = """
QMainWindow { background-color: #202020; }
QWidget { color: #e0e0e0; font-family: "Segoe UI", Arial; font-size: 14px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; padding: 8px; color: white; }
QPushButton { background-color: #0078d7; color: white; border-radius: 6px; padding: 8px; border: none; }
QPushButton:hover { background-color: #1e8feb; }
QPushButton:disabled { background-color: #333; color: #777; }
QComboBox { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; padding: 5px; }
QScrollArea { border: none; background-color: #202020; }
QProgressBar { border: none; background-color: #2d2d2d; height: 4px; }
QProgressBar::chunk { background-color: #00e676; }
"""

# ==========================================
#  🔥 核心修改：自適應網格佈局 (Adaptive Grid)
#  這會自動計算間距，讓圖片永遠「平均分佈」
# ==========================================
class AdaptiveGridLayout(QLayout):
    def __init__(self, parent=None, min_spacing=20):
        super(AdaptiveGridLayout, self).__init__(parent)
        self._items = []
        self._min_spacing = min_spacing
        self.setContentsMargins(min_spacing, min_spacing, min_spacing, min_spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super(AdaptiveGridLayout, self).setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        # 簡單估算最小尺寸
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _doLayout(self, rect, testOnly):
        # 1. 取得可用寬度
        effective_width = rect.width()
        
        # 2. 假設所有卡片大小一致 (取第一張卡片的大小，或用預設值)
        item_w = CARD_SIZE[0]
        item_h = CARD_SIZE[1]
        
        # 3. 計算一行能放幾個 (N)
        # 公式： N * item_w + (N+1) * min_spacing <= effective_width
        # 簡化估算：
        if self._items:
            # 嘗試計算最大列數
            n_cols = 1
            while True:
                required_w = (n_cols * item_w) + ((n_cols + 1) * self._min_spacing)
                if required_w > effective_width:
                    n_cols -= 1
                    break
                n_cols += 1
            
            # 至少要有一列
            if n_cols < 1: n_cols = 1
        else:
            n_cols = 1

        # 4. 🔥 關鍵：計算動態間距 (Dynamic Spacing)
        # 剩餘空間 = 總寬 - (卡片總寬)
        # 間距 = 剩餘空間 / (列數 + 1)
        total_item_w = n_cols * item_w
        remaining_space = effective_width - total_item_w
        dynamic_spacing = remaining_space / (n_cols + 1)
        
        # 如果計算出的間距小於最小間距 (通常發生在 n_cols=1 但視窗極小時)，使用最小間距
        if dynamic_spacing < self._min_spacing:
            dynamic_spacing = self._min_spacing

        # 5. 開始排版
        x = rect.x() + dynamic_spacing
        y = rect.y() + self._min_spacing # 垂直間距維持固定或也動態皆可，這裡用 min_spacing
        
        current_col = 0
        
        for item in self._items:
            if not testOnly:
                # 設定位置
                item.setGeometry(QRect(QPoint(int(x), int(y)), QSize(item_w, item_h)))
            
            current_col += 1
            
            if current_col >= n_cols:
                # 換行
                current_col = 0
                x = rect.x() + dynamic_spacing
                y += item_h + self._min_spacing # 垂直間距
            else:
                # 移動到下一個位置
                x += item_w + dynamic_spacing

        # 回傳總高度
        total_height = y + item_h + self._min_spacing if current_col > 0 else y
        return total_height - rect.y()

# ==========================================
#  1. 數據層 (Data Layer)
# ==========================================
class ImageSearchEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        print(f"🚀 [Engine] Initializing on {self.device.upper()}...")
        try:
            self.model = CLIPModel.from_pretrained(MODEL_NAME).to(self.device)
            self.processor = CLIPProcessor.from_pretrained(MODEL_NAME)
            self.model.eval()
            if os.path.exists(INDEX_FILE):
                with open(INDEX_FILE, 'rb') as f:
                    data = pickle.load(f)
                self.stored_embeddings = data['embeddings'].to(self.device)
                self.stored_paths = data['paths']
                self.is_ready = True
                print(f"✅ [Engine] Loaded {len(self.stored_paths)} images.")
            else:
                print(f"❌ Index not found.")
        except Exception as e:
            print(f"❌ Error: {e}")

    def search(self, query, top_k=20):
        if not self.is_ready: return []
        with torch.no_grad():
            inputs = self.processor(text=[query], return_tensors="pt", padding=True).to(self.device)
            text_outputs = self.model.text_model(**inputs)
            text_features = self.model.text_projection(text_outputs.pooler_output)
            text_features /= text_features.norm(p=2, dim=-1, keepdim=True)
        similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
        k = min(top_k, len(self.stored_paths))
        values, indices = similarity.topk(k)
        results = []
        for i in range(k):
            idx = indices[i].item()
            results.append({
                "score": values[i].item(),
                "path": self.stored_paths[idx],
                "filename": os.path.basename(self.stored_paths[idx])
            })
        return results

# ==========================================
#  2. 邏輯層 (Worker)
# ==========================================
class SearchWorker(QThread):
    batch_ready = pyqtSignal(list) 
    finished_search = pyqtSignal(float, int)

    def __init__(self, engine, query, top_k, img_cache):
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.img_cache = img_cache

    def run(self):
        start_time = time.time()
        raw_results = self.engine.search(self.query, self.top_k)
        
        count = 0
        batch_buffer = []
        BATCH_SIZE = 5

        for res in raw_results:
            path = res['path']
            q_image = None
            if path in self.img_cache:
                q_image = self.img_cache[path]
            else:
                try:
                    with Image.open(path) as img:
                        img.load()
                        img = img.convert("RGBA")
                        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                        data = img.tobytes("raw", "RGBA")
                        q_image = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy()
                        self.img_cache[path] = q_image
                except Exception:
                    continue

            if q_image:
                batch_buffer.append((res, q_image))
                count += 1
                if len(batch_buffer) >= BATCH_SIZE:
                    self.batch_ready.emit(batch_buffer)
                    batch_buffer = []
                    time.sleep(0.001)

        if batch_buffer:
            self.batch_ready.emit(batch_buffer)

        elapsed = time.time() - start_time
        self.finished_search.emit(elapsed, count)

# ==========================================
#  3. 表現層 (View) - 使用 AdaptiveGridLayout
# ==========================================
class ResultCard(QFrame):
    def __init__(self, result_data, q_image):
        super().__init__()
        self.path = result_data['path']
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1]) # 固定大小
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("QFrame { background-color: #2d2d2d; border-radius: 10px; border: 1px solid #3e3e3e; } QFrame:hover { background-color: #383838; border: 1px solid #555; }")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QVBoxLayout()
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet("border: none; background: transparent;")
        self.img_label.setPixmap(QPixmap.fromImage(q_image))
        layout.addWidget(self.img_label)

        score_color = "#00e676" if result_data['score'] > 0.3 else "#aaaaaa"
        name = result_data['filename']
        if len(name) > 20: name = name[:18] + "..."
        self.text_label = QLabel(f"<span style='color:{score_color}; font-weight:bold;'>{result_data['score']:.4f}</span><br><span style='color:#ddd; font-size:11px;'>{name}</span>")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.text_label)
        self.setLayout(layout)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try: os.startfile(self.path)
            except: pass

class AdaptiveResultView(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        
        self.container = QWidget()
        # 🔥 使用新的自適應佈局
        self.adaptive_layout = AdaptiveGridLayout(self.container, min_spacing=MIN_SPACING)
        
        self.setWidget(self.container)

    def clear(self):
        # Pythonic way to clear layout
        while self.adaptive_layout.count():
            item = self.adaptive_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_items(self, batch_data):
        self.container.setUpdatesEnabled(False)
        try:
            for res, q_image in batch_data:
                card = ResultCard(res, q_image)
                self.adaptive_layout.addWidget(card)
        finally:
            self.container.setUpdatesEnabled(True)

# ==========================================
#  4. 主視窗 (Controller)
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1200, 850)
        self.engine = None
        self.img_cache = {}

        self.init_ui()
        threading.Thread(target=self.load_engine, daemon=True).start()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # 頂部列
        top_bar = QFrame()
        top_bar.setFixedHeight(80)
        top_bar.setStyleSheet("background-color: #252525; border-bottom: 1px solid #333;")
        top = QHBoxLayout(top_bar)
        
        self.combo_limit = QComboBox()
        self.combo_limit.addItems(["20", "50", "100", "全部"])
        self.combo_limit.setCurrentText("50")
        top.addWidget(QLabel("Limit:"))
        top.addWidget(self.combo_limit)
        
        self.input = QLineEdit()
        self.input.setPlaceholderText("Search...")
        self.input.returnPressed.connect(self.start_search)
        top.addWidget(self.input)
        
        self.btn = QPushButton("Search")
        self.btn.clicked.connect(self.start_search)
        self.btn.setEnabled(False)
        top.addWidget(self.btn)
        
        self.status = QLabel("Init...")
        self.status.setStyleSheet("color: orange; font-weight: bold;")
        top.addWidget(self.status)
        layout.addWidget(top_bar)

        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        # ---------------------------------------------------------
        # 使用自適應視圖
        # ---------------------------------------------------------
        self.view_component = AdaptiveResultView() 
        layout.addWidget(self.view_component)

    def load_engine(self):
        try:
            self.engine = ImageSearchEngine()
            self.status.setText("✅ Ready")
            self.status.setStyleSheet("color: #00e676; font-weight: bold;")
            self.btn.setEnabled(True)
        except Exception as e:
            print(e)

    def start_search(self):
        q = self.input.text().strip()
        if not q or not self.engine: return

        self.btn.setEnabled(False)
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status.setText("Searching...")
        
        limit = self.combo_limit.currentText()
        k = 100000 if limit == "全部" else int(limit)

        self.view_component.clear()

        self.worker = SearchWorker(self.engine, q, k, self.img_cache)
        self.worker.batch_ready.connect(self.view_component.add_items)
        self.worker.finished_search.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def on_finished(self, elapsed, total):
        self.progress.hide()
        self.btn.setEnabled(True)
        self.status.setText(f"✅ Found {total} ({elapsed:.2f}s)")

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
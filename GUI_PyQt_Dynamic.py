import sys
import os
import time
import pickle
import threading
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLayout, QSizePolicy,
                             QLineEdit, QPushButton, QLabel, QScrollArea, 
                             QComboBox, QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize
from PyQt6.QtGui import QPixmap, QImage, QCursor

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
THUMBNAIL_SIZE = (220, 220)
# GRID_COLUMNS 被移除了，因為現在是動態的！
WINDOW_TITLE = "Local AI Search (Dynamic Layout Edition)"
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
#  0. 新增：流式佈局 (FlowLayout)
#  這段程式碼負責自動計算位置，讓卡片自動換行
# ==========================================
class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, hSpacing=15, vSpacing=15):
        super(FlowLayout, self).__init__(parent)
        self._hSpacing = hSpacing
        self._vSpacing = vSpacing
        self._items = []
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        item = self.takeAt(0)
        while item:
            item = self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        return self._hSpacing

    def verticalSpacing(self):
        return self._vSpacing

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
        super(FlowLayout, self).setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        spacingX = self.horizontalSpacing()
        spacingY = self.verticalSpacing()

        for item in self._items:
            # 取得每個元件的大小
            wid = item.widget()
            spaceX = spacingX
            spaceY = spacingY
            
            # 決定下一個元件的位置
            nextX = x + item.sizeHint().width() + spaceX
            
            # 如果超過邊界，就換行！
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()

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
#  3. 表現層 (View) - 使用 FlowLayout
# ==========================================
class ResultCard(QFrame):
    def __init__(self, result_data, q_image):
        super().__init__()
        self.path = result_data['path']
        # 設定固定大小，這樣 FlowLayout 才知道何時要換行
        self.setFixedSize(230, 270) 
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

class DynamicResultView(QScrollArea):
    """
    修改過的視圖：使用 FlowLayout
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True) # 關鍵：讓內容隨視窗縮放
        
        self.container = QWidget()
        # 🔥 換掉原本的 QGridLayout，改用 FlowLayout
        self.flow_layout = FlowLayout(self.container, margin=20, hSpacing=15, vSpacing=15)
        
        self.setWidget(self.container)

    def clear(self):
        # 清除 Layout 內所有元件 (Python 需要手動管理一下參考)
        while self.flow_layout.count():
            item = self.flow_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_items(self, batch_data):
        self.container.setUpdatesEnabled(False)
        try:
            for res, q_image in batch_data:
                card = ResultCard(res, q_image)
                # 🔥 直接 Add，不需要指定 row/col
                self.flow_layout.addWidget(card)
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
        # 使用新的動態視圖
        # ---------------------------------------------------------
        self.view_component = DynamicResultView() 
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
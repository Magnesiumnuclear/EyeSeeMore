import sys
import os
import time
import pickle
import threading
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QCursor

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
THUMBNAIL_SIZE = (220, 220)
GRID_COLUMNS = 5
WINDOW_TITLE = "Local AI Search (Modular Architecture)"
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
#  1. 數據層 (Data Layer) - 保持不變
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
#  2. 邏輯層 (Worker) - 加入微批次處理 (Micro-Batching)
# ==========================================
class SearchWorker(QThread):
    # 修改信號：現在回傳的是一個 list (批次)，而不是單張
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
        batch_buffer = [] # 緩衝區
        BATCH_SIZE = 5    # 每 5 張更新一次 UI，解決抖動的關鍵！

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
                # 加入緩衝區
                batch_buffer.append((res, q_image))
                count += 1

                # 緩衝區滿了，發送並清空
                if len(batch_buffer) >= BATCH_SIZE:
                    self.batch_ready.emit(batch_buffer)
                    batch_buffer = [] # 重置
                    # ⚡ 關鍵：讓 UI 執行緒有 1ms 的時間去完成佈局計算，防止塞車
                    time.sleep(0.001)

        # 迴圈結束，發送剩餘的
        if batch_buffer:
            self.batch_ready.emit(batch_buffer)

        elapsed = time.time() - start_time
        self.finished_search.emit(elapsed, count)

# ==========================================
#  3. 表現層 (Presentation Layer) - 接口化設計
# ==========================================
class ResultCard(QFrame):
    """ 單張卡片元件 (這是 Grid 模式專用的) """
    def __init__(self, result_data, q_image):
        super().__init__()
        self.path = result_data['path']
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

class GridResultView(QScrollArea):
    """
    [關鍵類別] 這是目前的顯示實作。
    未來如果你要升級成虛擬化列表，只需要寫一個 'VirtualResultView(QListView)'
    並實作同樣的介面 (add_items, clear)，主程式完全不用改。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.grid_layout = QGridLayout(self.container)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(20, 20, 20, 20)
        self.setWidget(self.container)
        self.current_count = 0

    def clear(self):
        """ 清空視圖接口 """
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.current_count = 0

    def add_items(self, batch_data):
        """ 
        新增項目接口 (批次) 
        batch_data: list of (result_dict, q_image)
        """
        # 優化：暫時鎖定更新，一次把這 5 張貼上去再重繪，減少抖動
        self.container.setUpdatesEnabled(False)
        
        try:
            for res, q_image in batch_data:
                row = self.current_count // GRID_COLUMNS
                col = self.current_count % GRID_COLUMNS
                card = ResultCard(res, q_image)
                self.grid_layout.addWidget(card, row, col)
                self.current_count += 1
        finally:
            self.container.setUpdatesEnabled(True) # 恢復更新

    def get_count(self):
        return self.current_count

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
        # [未來接口] 這裡實例化視圖。
        # 未來改成: self.view_component = VirtualResultView() 即可
        # ---------------------------------------------------------
        self.view_component = GridResultView() 
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

        # 呼叫視圖接口：清空
        self.view_component.clear()

        self.worker = SearchWorker(self.engine, q, k, self.img_cache)
        # 連接信號：注意這裡是接收 batch (list)
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
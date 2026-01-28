import sys
import os
import time
import pickle
import threading
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

# PyQt6 核心模組
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QCursor, QIcon

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
THUMBNAIL_SIZE = (220, 220)  # 縮圖大小
GRID_COLUMNS = 5             # 一行顯示幾張
WINDOW_TITLE = "Local AI Search (RTX 4080 Streaming Edition)"
# ----------------

# 深色主題樣式表 (Dark Mode QSS)
DARK_STYLESHEET = """
QMainWindow { background-color: #202020; }
QWidget { color: #e0e0e0; font-family: "Segoe UI", Arial; font-size: 14px; }
QLineEdit { 
    background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; 
    padding: 8px; color: white; font-size: 16px; selection-background-color: #0078d7;
}
QPushButton { 
    background-color: #0078d7; color: white; border-radius: 6px; padding: 8px 16px; font-weight: bold; border: none;
}
QPushButton:hover { background-color: #1e8feb; }
QPushButton:disabled { background-color: #333333; color: #777777; }
QComboBox { 
    background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; padding: 5px; 
}
QComboBox::drop-down { border: none; }
QScrollArea { border: none; background-color: #202020; }
QProgressBar { 
    border: none; background-color: #2d2d2d; height: 4px; text-align: center; 
}
QProgressBar::chunk { background-color: #00e676; border-radius: 2px; }
"""

# --- 1. 後端搜尋引擎 (AI 邏輯) ---
class ImageSearchEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        print(f"🚀 [Engine] Initializing on {self.device.upper()}...")
        
        try:
            # 載入 Transformers 模型 (手動模式以確保相容性)
            self.model = CLIPModel.from_pretrained(MODEL_NAME).to(self.device)
            self.processor = CLIPProcessor.from_pretrained(MODEL_NAME)
            self.model.eval()

            # 載入索引
            if os.path.exists(INDEX_FILE):
                with open(INDEX_FILE, 'rb') as f:
                    data = pickle.load(f)
                self.stored_embeddings = data['embeddings'].to(self.device)
                self.stored_paths = data['paths']
                self.is_ready = True
                print(f"✅ [Engine] Loaded {len(self.stored_paths)} images into VRAM.")
            else:
                print(f"❌ [Engine] Index file not found: {INDEX_FILE}")
        except Exception as e:
            print(f"❌ [Engine] Error: {e}")

    def search(self, query, top_k=20):
        if not self.is_ready: return []
        
        # 手動執行文字編碼與投影，避開版本相容性問題
        with torch.no_grad():
            inputs = self.processor(text=[query], return_tensors="pt", padding=True).to(self.device)
            text_outputs = self.model.text_model(**inputs)
            text_features = self.model.text_projection(text_outputs.pooler_output)
            text_features /= text_features.norm(p=2, dim=-1, keepdim=True)

        # 計算相似度
        similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
        
        # 確保不超過總數
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

# --- 2. 背景工作者 (增量渲染核心) ---
class SearchWorker(QThread):
    # 定義信號：每處理好一張圖，就發送一次 (單張模式)
    item_ready = pyqtSignal(dict, QImage)
    # 全部完成信號
    finished_search = pyqtSignal(float, int)

    def __init__(self, engine, query, top_k, img_cache):
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.img_cache = img_cache # 共享主視窗的快取

    def run(self):
        start_time = time.time()
        
        # 1. 先進行向量搜索 (極快)
        raw_results = self.engine.search(self.query, self.top_k)
        
        count = 0
        # 2. 逐張處理圖片並即時回傳
        for res in raw_results:
            path = res['path']
            q_image = None
            
            # A. 檢查快取 (Cache Hit)
            if path in self.img_cache:
                q_image = self.img_cache[path]
            
            # B. 讀取硬碟 (Cache Miss)
            else:
                try:
                    with Image.open(path) as img:
                        img.load() # 強制載入記憶體
                        img = img.convert("RGBA")
                        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                        
                        # 轉換為 Qt 格式
                        data = img.tobytes("raw", "RGBA")
                        q_image = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
                        q_image = q_image.copy() # 深拷貝防止釋放
                        
                        # 寫入快取 (利用 64GB RAM)
                        self.img_cache[path] = q_image
                except Exception:
                    continue # 略過壞圖

            # 🔥 關鍵：處理好一張，馬上發送給 UI 顯示
            if q_image:
                self.item_ready.emit(res, q_image)
                count += 1
                
        elapsed = time.time() - start_time
        self.finished_search.emit(elapsed, count)

# --- 3. 單張結果卡片 (UI 元件) ---
class ResultCard(QFrame):
    def __init__(self, result_data, q_image):
        super().__init__()
        self.path = result_data['path']
        
        # 卡片樣式
        self.setFixedSize(230, 270)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame { 
                background-color: #2d2d2d; 
                border-radius: 10px; 
                border: 1px solid #3e3e3e;
            }
            QFrame:hover { 
                background-color: #383838; 
                border: 1px solid #555;
            }
        """)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 圖片區域
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet("border: none; background: transparent;")
        pixmap = QPixmap.fromImage(q_image)
        self.img_label.setPixmap(pixmap)
        layout.addWidget(self.img_label)

        # 文字區域
        score = result_data['score']
        # 分數顏色邏輯
        score_color = "#00e676" if score > 0.3 else "#aaaaaa"
        
        name_text = result_data['filename']
        if len(name_text) > 20: name_text = name_text[:18] + "..."

        self.text_label = QLabel(f"<span style='color:{score_color}; font-size:12px; font-weight:bold;'>{score:.4f}</span><br><span style='color:#ddd; font-size:11px;'>{name_text}</span>")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.text_label)
        
        self.setLayout(layout)

    def mousePressEvent(self, event):
        """ 左鍵點擊開啟圖片 """
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                print(f"Opening: {self.path}")
                os.startfile(self.path)
            except Exception as e:
                print(f"Error: {e}")

# --- 4. 主視窗程式 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1200, 850)
        
        self.engine = None
        self.worker = None
        self.img_cache = {} # 全域圖片快取
        self.current_count = 0 # 用於計算增量渲染的位置

        self.init_ui()
        
        # 啟動背景執行緒載入模型
        threading.Thread(target=self.load_engine, daemon=True).start()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # [A] 頂部控制區
        top_container = QFrame()
        top_container.setFixedHeight(80)
        top_container.setStyleSheet("background-color: #252525; border-bottom: 1px solid #333;")
        top_layout = QHBoxLayout(top_container)
        top_layout.setContentsMargins(20, 10, 20, 10)

        # 數量選擇
        top_layout.addWidget(QLabel("Limit:"))
        self.combo_limit = QComboBox()
        self.combo_limit.addItems(["20", "50", "100", "全部"])
        self.combo_limit.setCurrentText("50")
        self.combo_limit.setFixedWidth(80)
        top_layout.addWidget(self.combo_limit)

        top_layout.addSpacing(15)

        # 搜尋框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("輸入關鍵字 (例如: sorasaki hina, halo)...")
        self.search_input.setFixedHeight(40)
        self.search_input.returnPressed.connect(self.start_search)
        top_layout.addWidget(self.search_input)

        top_layout.addSpacing(10)

        # 搜尋按鈕
        self.btn_search = QPushButton("搜尋")
        self.btn_search.setFixedWidth(100)
        self.btn_search.setFixedHeight(40)
        self.btn_search.clicked.connect(self.start_search)
        self.btn_search.setEnabled(False) 
        top_layout.addWidget(self.btn_search)

        # 狀態顯示
        top_layout.addSpacing(20)
        self.status_label = QLabel("正在初始化模型...")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")
        self.status_label.setFixedWidth(200)
        top_layout.addWidget(self.status_label)

        main_layout.addWidget(top_container)

        # [B] 進度條 (細條)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        main_layout.addWidget(self.progress_bar)

        # [C] 內容滾動區
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        self.results_container = QWidget()
        # 使用 Grid Layout
        self.grid_layout = QGridLayout(self.results_container)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(20, 20, 20, 20)
        
        self.scroll_area.setWidget(self.results_container)
        main_layout.addWidget(self.scroll_area)

    def load_engine(self):
        """ 背景載入模型 """
        try:
            self.engine = ImageSearchEngine()
            # 簡單使用 QTimer 非同步更新 UI (模擬 Signal)
            # 在 PyQt 中，文字設定通常是 Thread-safe 的，但嚴謹做法應使用 Signal
            self.status_label.setText("✅ 系統就緒")
            self.status_label.setStyleSheet("color: #00e676; font-weight: bold;")
            self.btn_search.setEnabled(True)
        except Exception as e:
            print(e)

    def start_search(self):
        query = self.search_input.text().strip()
        if not query or not self.engine: return

        # UI 重置
        self.btn_search.setEnabled(False)
        self.progress_bar.show()
        self.progress_bar.setRange(0, 0) # 跑馬燈模式
        self.status_label.setText("搜尋運算中...")
        self.status_label.setStyleSheet("color: #29b6f6;")
        
        # 取得數量限制
        limit_txt = self.combo_limit.currentText()
        top_k = 100000 if limit_txt == "全部" else int(limit_txt)

        # 清除舊結果 (必須手動刪除 Widget 以釋放記憶體)
        self.clear_grid()
        self.current_count = 0

        # 啟動工作執行緒
        self.worker = SearchWorker(self.engine, query, top_k, self.img_cache)
        # 連接信號：一張一張收，全部收完再通知
        self.worker.item_ready.connect(self.add_single_card)
        self.worker.finished_search.connect(self.on_search_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def clear_grid(self):
        """ 清空網格中的所有卡片 """
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_single_card(self, res, q_image):
        """ 增量渲染：收到一張圖，馬上貼上去 """
        # 計算座標
        row = self.current_count // GRID_COLUMNS
        col = self.current_count % GRID_COLUMNS
        
        card = ResultCard(res, q_image)
        self.grid_layout.addWidget(card, row, col)
        
        self.current_count += 1
        
        # 即時更新狀態
        self.status_label.setText(f"載入中... ({self.current_count})")

    def on_search_finished(self, elapsed, total):
        self.progress_bar.hide()
        self.btn_search.setEnabled(True)
        
        if total == 0:
            self.status_label.setText("❌ 找不到結果")
            self.status_label.setStyleSheet("color: #ff5252;")
        else:
            self.status_label.setText(f"✅ 完成 ({total} 張 / {elapsed:.2f}秒)")
            self.status_label.setStyleSheet("color: #00e676;")

if __name__ == "__main__":
    # 啟用高解析度螢幕支援 (High DPI Scaling)
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())
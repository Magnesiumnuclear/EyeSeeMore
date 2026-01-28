import sys
import os
import time
import pickle
import threading
import json  # 新增：用於存檔
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QMenu) # 新增 QMenu 用於右鍵選單
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize
from PyQt6.QtGui import QPixmap, QImage, QCursor, QAction

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
HISTORY_FILE = "search_history.json" # 歷史紀錄存檔
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
THUMBNAIL_SIZE = (220, 220)
CARD_SIZE = (230, 270)
MIN_SPACING = 20
WINDOW_TITLE = "Local AI Search (History Edition)"
# ----------------

DARK_STYLESHEET = """
QMainWindow { background-color: #202020; }
QWidget { color: #e0e0e0; font-family: "Segoe UI", Arial; font-size: 14px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; padding: 8px; color: white; }
/* QComboBox 樣式優化 */
QComboBox { 
    background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 6px; padding: 5px; color: white; font-size: 16px;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { image: none; border-left: 2px solid #555; width: 0; height: 0; }
QComboBox QAbstractItemView {
    background-color: #2d2d2d; color: white; selection-background-color: #0078d7;
}
QPushButton { background-color: #0078d7; color: white; border-radius: 6px; padding: 8px; border: none; }
QPushButton:hover { background-color: #1e8feb; }
QPushButton:disabled { background-color: #333; color: #777; }
QScrollArea { border: none; background-color: #202020; }
QProgressBar { border: none; background-color: #2d2d2d; height: 4px; }
QProgressBar::chunk { background-color: #00e676; }
"""

# ==========================================
#  🔥 新增：具備歷史紀錄功能的 ComboBox
# ==========================================
class HistoryComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True) # 允許輸入文字
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert) # 手動管理插入，避免重複
        self.setMaxCount(50) # 最多紀錄 50 筆
        
        # 載入歷史
        self.load_history()

        # 啟用右鍵選單 (個別刪除功能)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def load_history(self):
        """ 從 JSON 載入紀錄 """
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    self.addItems(history)
                    self.setCurrentIndex(-1) # 預設不選中任何項目
            except Exception as e:
                print(f"Error loading history: {e}")

    def save_history(self):
        """ 儲存紀錄到 JSON """
        history = [self.itemText(i) for i in range(self.count())]
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving history: {e}")

    def add_current_text(self):
        """ 將當前輸入的文字加入歷史 (自動去重、移到最前) """
        text = self.currentText().strip()
        if not text: return

        # 如果已經存在，先移除舊的 (為了移到最上面)
        index = self.findText(text)
        if index != -1:
            self.removeItem(index)
        
        # 插入到第一項
        self.insertItem(0, text)
        self.setCurrentIndex(0)
        self.save_history()

    def clear_all_history(self):
        """ 清空所有歷史 """
        self.clear()
        self.save_history()
        self.setCurrentText("") # 清空輸入框

    def remove_current_item(self):
        """ 刪除當前選中的項目 (個別清除) """
        idx = self.currentIndex()
        if idx != -1:
            self.removeItem(idx)
            self.save_history()
            self.setCurrentText("") # 清空輸入框文字

    def show_context_menu(self, pos):
        """ 右鍵選單邏輯 """
        menu = QMenu(self)
        
        # 只有在有文字或有選中項目時才顯示刪除選項
        current_text = self.currentText()
        
        if current_text and self.findText(current_text) != -1:
            action_del_one = QAction(f"🗑️ 從歷史移除 '{current_text}'", self)
            action_del_one.triggered.connect(self.remove_current_item)
            menu.addAction(action_del_one)

        action_clear_all = QAction("💥 清空所有歷史紀錄", self)
        action_clear_all.triggered.connect(self.clear_all_history)
        menu.addAction(action_clear_all)
        
        menu.exec(self.mapToGlobal(pos))

# ==========================================
#  佈局與核心邏輯 (Adaptive Layout + Engine)
# ==========================================
class AdaptiveGridLayout(QLayout):
    def __init__(self, parent=None, min_spacing=20):
        super(AdaptiveGridLayout, self).__init__(parent)
        self._items = []
        self._min_spacing = min_spacing
        self.setContentsMargins(min_spacing, min_spacing, min_spacing, min_spacing)

    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def itemAt(self, index): return self._items[index] if 0 <= index < len(self._items) else None
    def takeAt(self, index): return self._items.pop(index) if 0 <= index < len(self._items) else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._doLayout(QRect(0, 0, width, 0), True)
    def setGeometry(self, rect): super(AdaptiveGridLayout, self).setGeometry(rect); self._doLayout(rect, False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self): 
        size = QSize()
        for item in self._items: size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _doLayout(self, rect, testOnly):
        effective_width = rect.width()
        item_w, item_h = CARD_SIZE
        
        if self._items:
            n_cols = 1
            while True:
                required_w = (n_cols * item_w) + ((n_cols + 1) * self._min_spacing)
                if required_w > effective_width:
                    n_cols -= 1
                    break
                n_cols += 1
            if n_cols < 1: n_cols = 1
        else:
            n_cols = 1

        total_item_w = n_cols * item_w
        remaining_space = effective_width - total_item_w
        dynamic_spacing = remaining_space / (n_cols + 1)
        if dynamic_spacing < self._min_spacing: dynamic_spacing = self._min_spacing

        x = rect.x() + dynamic_spacing
        y = rect.y() + self._min_spacing
        current_col = 0
        
        for item in self._items:
            if not testOnly: item.setGeometry(QRect(QPoint(int(x), int(y)), QSize(item_w, item_h)))
            current_col += 1
            if current_col >= n_cols:
                current_col = 0
                x = rect.x() + dynamic_spacing
                y += item_h + self._min_spacing
            else:
                x += item_w + dynamic_spacing
        
        total_height = y + item_h + self._min_spacing if current_col > 0 else y
        return total_height - rect.y()

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
        self.finished_search.emit(time.time() - start_time, count)

class ResultCard(QFrame):
    def __init__(self, result_data, q_image):
        super().__init__()
        self.path = result_data['path']
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1])
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
        self.adaptive_layout = AdaptiveGridLayout(self.container, min_spacing=MIN_SPACING)
        self.setWidget(self.container)

    def clear(self):
        while self.adaptive_layout.count():
            item = self.adaptive_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def add_items(self, batch_data):
        self.container.setUpdatesEnabled(False)
        try:
            for res, q_image in batch_data:
                self.adaptive_layout.addItem(ResultCard(res, q_image)) # Direct add to layout class
        finally:
            self.container.setUpdatesEnabled(True)

# ==========================================
#  主視窗 (Controller)
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
        
        # 1. 數量限制
        self.combo_limit = QComboBox()
        self.combo_limit.addItems(["20", "50", "100", "全部"])
        self.combo_limit.setCurrentText("50")
        top.addWidget(QLabel("Limit:"))
        top.addWidget(self.combo_limit)
        
        top.addSpacing(15)

        # 2. 🔥 搜尋框 (換成 HistoryComboBox)
        # 用 setSizePolicy 讓它盡量伸展
        self.search_combo = HistoryComboBox()
        self.search_combo.setPlaceholderText("Search...")
        self.search_combo.setMinimumWidth(400)
        # 捕捉 Enter 鍵：QComboBox 內部的 QLineEdit 發出 returnPressed 信號
        self.search_combo.lineEdit().returnPressed.connect(self.start_search)
        top.addWidget(self.search_combo, 1) # stretch=1
        
        # 3. 🔥 清除歷史按鈕 (垃圾桶)
        self.btn_clear_hist = QPushButton("🗑️")
        self.btn_clear_hist.setToolTip("清空所有搜尋紀錄")
        self.btn_clear_hist.setFixedWidth(40)
        self.btn_clear_hist.clicked.connect(self.search_combo.clear_all_history)
        self.btn_clear_hist.setStyleSheet("QPushButton { background-color: #444; } QPushButton:hover { background-color: #d32f2f; }")
        top.addWidget(self.btn_clear_hist)

        top.addSpacing(10)

        # 4. 搜尋按鈕
        self.btn_search = QPushButton("Search")
        self.btn_search.clicked.connect(self.start_search)
        self.btn_search.setEnabled(False)
        top.addWidget(self.btn_search)
        
        # 5. 狀態
        self.status = QLabel("Init...")
        self.status.setStyleSheet("color: orange; font-weight: bold;")
        top.addWidget(self.status)
        
        layout.addWidget(top_bar)

        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        self.view_component = AdaptiveResultView() 
        layout.addWidget(self.view_component)

    def load_engine(self):
        try:
            self.engine = ImageSearchEngine()
            self.status.setText("✅ Ready")
            self.status.setStyleSheet("color: #00e676; font-weight: bold;")
            self.btn_search.setEnabled(True)
        except Exception as e:
            print(e)

    def start_search(self):
        # 🔥 從 ComboBox 取得文字
        q = self.search_combo.currentText().strip()
        if not q or not self.engine: return

        # 🔥 自動儲存關鍵字到歷史
        self.search_combo.add_current_text()

        self.btn_search.setEnabled(False)
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
        self.btn_search.setEnabled(True)
        self.status.setText(f"✅ Found {total} ({elapsed:.2f}s)")

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
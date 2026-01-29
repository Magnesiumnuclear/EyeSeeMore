import sys
import os
import time
import pickle
import threading
import json
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent
from PyQt6.QtGui import QPixmap, QImage, QCursor

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion-1.pkl"
HISTORY_FILE = "search_history.json"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
THUMBNAIL_SIZE = (220, 220)
CARD_SIZE = (230, 270)
MIN_SPACING = 20
WINDOW_TITLE = "Local AI Search (History Actions Edition)"
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

/* 歷史紀錄清單容器樣式 */
QListWidget {
    background-color: #2d2d2d;
    border: 1px solid #3e3e3e;
    border-radius: 6px;
    outline: 0;
}
QListWidget::item {
    /* 因為我們用了 setItemWidget，這裡的樣式主要影響選取狀態，簡單設定即可 */
    border-bottom: 1px solid #333;
}
QListWidget::item:hover {
    background-color: transparent; /* 讓自訂 Widget 處理 hover */
}
"""

# ==========================================
#  自適應網格佈局 (維持原樣)
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
        size += QSize(2 * self.contentsMargins().top(), 2 * self.contentsMargins().top())
        return size

    def _doLayout(self, rect, testOnly):
        effective_width = rect.width()
        item_w = CARD_SIZE[0]
        item_h = CARD_SIZE[1]
        
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
        if dynamic_spacing < self._min_spacing:
            dynamic_spacing = self._min_spacing

        x = rect.x() + dynamic_spacing
        y = rect.y() + self._min_spacing
        current_col = 0
        
        for item in self._items:
            if not testOnly:
                item.setGeometry(QRect(QPoint(int(x), int(y)), QSize(item_w, item_h)))
            current_col += 1
            if current_col >= n_cols:
                current_col = 0
                x = rect.x() + dynamic_spacing
                y += item_h + self._min_spacing
            else:
                x += item_w + dynamic_spacing

        total_height = y + item_h + self._min_spacing if current_col > 0 else y
        return total_height - rect.y()

# ==========================================
#  引擎與 Worker (維持原樣)
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

# ==========================================
#  🔥 新增：歷史紀錄項目 Widget (文字 + 刪除按鈕)
# ==========================================
class HistoryItemWidget(QWidget):
    def __init__(self, text, search_callback, delete_callback):
        super().__init__()
        self.text = text
        self.search_callback = search_callback
        self.delete_callback = delete_callback
        
        # 主要 Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)
        
        # 文字標籤
        self.label = QLabel(f"🕒 {text}")
        self.label.setStyleSheet("color: #ccc; background: transparent;")
        self.label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        # 讓文字標籤能響應點擊 (觸發搜尋)
        # 這裡我們覆寫 mousePressEvent 的方式
        self.label.mousePressEvent = self.on_label_clicked
        
        layout.addWidget(self.label, stretch=1) # stretch=1 讓文字佔據剩餘空間

        # 刪除按鈕
        self.del_btn = QPushButton("✕")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        # 按鈕樣式：平常透明灰字，滑入變紅
        self.del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #666;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: #442020;
                color: #ff5252;
            }
        """)
        self.del_btn.clicked.connect(self.on_delete_clicked)
        layout.addWidget(self.del_btn)

        # 整個 Widget 的 hover 效果 (透過 stylesheet 改變背景)
        self.setStyleSheet(".HistoryItemWidget:hover { background-color: #383838; border-radius: 4px; }")

    def on_label_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.search_callback(self.text)

    def on_delete_clicked(self):
        self.delete_callback(self.text)
    
    # 讓 hover 效果生效
    def paintEvent(self, event):
        from PyQt6.QtWidgets import QStyle, QStyleOption
        from PyQt6.QtGui import QPainter
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, p, self)

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
        self.search_history = [] 

        self.load_history()
        self.init_ui()
        
        QApplication.instance().installEventFilter(self)
        
        threading.Thread(target=self.load_engine, daemon=True).start()

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.search_history = json.load(f)
            except Exception as e:
                print(f"Error loading history: {e}")
                self.search_history = []

    def save_history_to_file(self):
        """將目前的記憶體歷史寫入檔案"""
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.search_history, f, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving history: {e}")

    def add_to_history(self, query):
        if not query: return
        if query in self.search_history:
            self.search_history.remove(query)
        self.search_history.insert(0, query)
        if len(self.search_history) > 20:
            self.search_history = self.search_history[:20]
        self.save_history_to_file()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Top Bar
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

        self.view_component = AdaptiveResultView() 
        layout.addWidget(self.view_component)

        # History List
        self.history_list = QListWidget(self)
        self.history_list.hide()
        self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            
            if self.history_list.isVisible():
                click_pos = event.globalPosition().toPoint()
                
                input_global_pos = self.input.mapToGlobal(QPoint(0, 0))
                input_rect = QRect(input_global_pos, self.input.size())
                
                list_global_pos = self.history_list.mapToGlobal(QPoint(0, 0))
                list_rect = QRect(list_global_pos, self.history_list.size())
                
                # 如果點擊位置不在輸入框且不在清單內 -> 隱藏
                if not input_rect.contains(click_pos) and not list_rect.contains(click_pos):
                    self.history_list.hide()

            if obj == self.input:
                self.show_history_popup()

        return super().eventFilter(obj, event)

    def show_history_popup(self):
        if not self.search_history:
            self.history_list.hide()
            return

        self.history_list.clear()
        
        # 🔥 替換成自訂的 HistoryItemWidget
        for text in self.search_history:
            item = QListWidgetItem()
            # 必須設定 item 大小提示，否則自訂 widget 可能被壓扁
            item.setSizeHint(QSize(0, 40)) 
            
            # 建立自訂 Widget，傳入搜尋與刪除的 callback
            widget = HistoryItemWidget(
                text, 
                search_callback=self.trigger_history_search,
                delete_callback=self.delete_history_item
            )
            
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, widget)

        # 重新計算位置與大小
        input_pos = self.input.mapTo(self, QPoint(0, 0))
        input_h = self.input.height()
        input_w = self.input.width()
        list_height = min(300, len(self.search_history) * 40 + 10)
        self.history_list.setGeometry(input_pos.x(), input_pos.y() + input_h + 5, input_w, list_height)
        
        self.history_list.show()
        self.history_list.raise_()

    def resizeEvent(self, event):
        self.history_list.hide()
        super().resizeEvent(event)

    # --- 歷史紀錄的操作 callback ---

    def delete_history_item(self, text):
        """刪除指定的歷史紀錄"""
        if text in self.search_history:
            self.search_history.remove(text)
            self.save_history_to_file()
            # 刪除後重新繪製清單，如果空了會自動隱藏
            self.show_history_popup()

    def trigger_history_search(self, text):
        """點擊歷史紀錄直接搜尋"""
        self.input.setText(text)
        self.start_search()

    # -----------------------------

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

        self.add_to_history(q)
        self.history_list.hide()

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
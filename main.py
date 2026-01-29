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
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent, QFileInfo
from PyQt6.QtGui import QPixmap, QImage, QCursor, QAction, QGuiApplication

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
QWidget { color: #e0e0e0; font-family: "Segoe UI", "Microsoft JhengHei", Arial; font-size: 14px; }
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
    border-bottom: 1px solid #333;
}
QListWidget::item:hover {
    background-color: transparent;
}

/* Windows 11 風格右鍵選單樣式 */
QMenu {
    background-color: #2d2d2d;
    border: 1px solid #454545;
    border-radius: 8px;
    padding: 6px;
    color: #ffffff;
    font-family: "Segoe UI", "Microsoft JhengHei";
    font-size: 13px;
}
QMenu::item {
    background-color: transparent;
    padding: 6px 12px;
    border-radius: 4px;
    margin: 2px 4px;
    min-width: 120px;
}
QMenu::item:selected {
    background-color: #3f3f3f; /* Hover 顏色 */
}
QMenu::separator {
    height: 1px;
    background-color: #454545;
    margin: 4px 10px;
}

/* 訊息視窗樣式 */
QMessageBox { background-color: #2d2d2d; color: white; }
QMessageBox QLabel { color: #e0e0e0; }
QMessageBox QPushButton {
    background-color: #3e3e3e;
    color: white;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 6px 20px;
    min-width: 60px;
}
QMessageBox QPushButton:hover { background-color: #4e4e4e; }
"""

# ==========================================
#  自適應網格佈局
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
#  引擎與 Worker
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

# ==========================================
#  🔥 修改後的 ResultCard：支援右鍵選單
# ==========================================
class ResultCard(QFrame):
    def __init__(self, result_data, q_image):
        super().__init__()
        self.result_data = result_data
        self.path = result_data['path']
        self.filename = result_data['filename']
        self.q_image_thumbnail = q_image # 保存縮圖引用
        
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1])
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame { background-color: #2d2d2d; border-radius: 10px; border: 1px solid #3e3e3e; } 
            QFrame:hover { background-color: #383838; border: 1px solid #555; }
        """)
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

    # 處理左鍵點擊 (開啟檔案)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try: os.startfile(self.path)
            except: pass
        # 呼叫父類以確保其他事件正常
        super().mousePressEvent(event)

    # 處理右鍵選單
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        # 建立 Actions
        # 為了美觀，這裡使用 Unicode 符號模擬圖示，或者保持純文字
        action_copy = QAction("複製", self)
        action_copy.triggered.connect(self.copy_image)
        
        action_copy_path = QAction("複製路徑", self)
        action_copy_path.triggered.connect(self.copy_path)
        
        action_properties = QAction("詳細內容", self)
        action_properties.triggered.connect(self.show_properties)

        # 佈局選單
        menu.addAction(action_copy)
        menu.addAction(action_copy_path)
        menu.addSeparator() # 分隔線
        menu.addAction(action_properties)

        # 顯示選單
        menu.exec(event.globalPos())

    def copy_image(self):
        """複製原始圖片到剪貼簿"""
        try:
            # 嘗試讀取原圖放入剪貼簿 (獲得最高畫質)
            original_img = QImage(self.path)
            if not original_img.isNull():
                QApplication.clipboard().setImage(original_img)
            else:
                # 若讀取失敗則複製縮圖
                QApplication.clipboard().setImage(self.q_image_thumbnail)
        except Exception as e:
            print(f"Copy image failed: {e}")

    def copy_path(self):
        """複製路徑到剪貼簿"""
        QApplication.clipboard().setText(self.path)

    def show_properties(self):
        """顯示詳細內容"""
        try:
            info = QFileInfo(self.path)
            size_mb = info.size() / (1024 * 1024)
            created = info.birthTime().toString("yyyy/MM/dd HH:mm")
            modified = info.lastModified().toString("yyyy/MM/dd HH:mm")
            
            # 讀取圖片尺寸
            img = QImage(self.path)
            width, height = img.width(), img.height()
            
            msg_content = f"""
            <h3 style='color: white; margin-bottom: 5px;'>{self.filename}</h3>
            <hr>
            <table cellspacing='5' cellpadding='2'>
            <tr><td style='color:#aaaaaa;'>類型:</td><td style='color:white;'>{info.suffix().upper()} 檔案</td></tr>
            <tr><td style='color:#aaaaaa;'>路徑:</td><td style='color:white;'>{self.path}</td></tr>
            <tr><td style='color:#aaaaaa;'>大小:</td><td style='color:white;'>{size_mb:.2f} MB</td></tr>
            <tr><td style='color:#aaaaaa;'>尺寸:</td><td style='color:white;'>{width} x {height}</td></tr>
            <tr><td colspan='2'><hr></td></tr>
            <tr><td style='color:#aaaaaa;'>建立:</td><td style='color:white;'>{created}</td></tr>
            <tr><td style='color:#aaaaaa;'>修改:</td><td style='color:white;'>{modified}</td></tr>
            </table>
            """
            
            box = QMessageBox(self)
            box.setWindowTitle("詳細內容")
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(msg_content)
            # 設定 QMessageBox 按鈕文字 (通常是 OK)
            ok_btn = box.addButton("確定", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            
        except Exception as e:
            print(f"Show properties failed: {e}")

# ==========================================
#  歷史紀錄 Widget
# ==========================================
class HistoryItemWidget(QWidget):
    def __init__(self, text, search_callback, delete_callback):
        super().__init__()
        self.text = text
        self.search_callback = search_callback
        self.delete_callback = delete_callback
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)
        
        self.label = QLabel(f"🕒 {text}")
        self.label.setStyleSheet("color: #ccc; background: transparent;")
        self.label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.label.mousePressEvent = self.on_label_clicked
        
        layout.addWidget(self.label, stretch=1)

        self.del_btn = QPushButton("✕")
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
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

        self.setStyleSheet(".HistoryItemWidget:hover { background-color: #383838; border-radius: 4px; }")

    def on_label_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.search_callback(self.text)

    def on_delete_clicked(self):
        self.delete_callback(self.text)
    
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
#  主視窗
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
        
        for text in self.search_history:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 40)) 
            
            widget = HistoryItemWidget(
                text, 
                search_callback=self.trigger_history_search,
                delete_callback=self.delete_history_item
            )
            
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, widget)

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

    def delete_history_item(self, text):
        if text in self.search_history:
            self.search_history.remove(text)
            self.save_history_to_file()
            self.show_history_popup()

    def trigger_history_search(self, text):
        self.input.setText(text)
        self.start_search()

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
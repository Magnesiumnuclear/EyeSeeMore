import sys
import os
import time
import pickle
import threading
import json
from PIL import Image
import torch
import open_clip
from transformers import AutoTokenizer 

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox,
                             QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent, QFileInfo
from PyQt6.QtGui import QPixmap, QImage, QCursor, QAction, QColor, QFont

# --- 設定區 ---
INDEX_FILE = "idx_H14_multilingual.pkl"
HISTORY_FILE = "search_history.json"
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'

THUMBNAIL_SIZE = (220, 220)
CARD_SIZE = (240, 280) 
MIN_SPACING = 24       
WINDOW_TITLE = "Local AI Search (Image-to-Image Supported)"

# --- 樣式表 ---
WIN11_STYLESHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #ffffff; font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; font-size: 14px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-bottom: 1px solid #505050; border-radius: 4px; padding: 10px 12px; color: #ffffff; font-size: 15px; selection-background-color: #005fb8; }
QLineEdit:focus { border-bottom: 2px solid #60cdff; background-color: #323232; }
QComboBox { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 4px; padding: 6px 10px; min-width: 80px; }
QComboBox:hover { background-color: #383838; }
QComboBox::drop-down { border: none; width: 20px; }
QPushButton#PrimaryButton { background-color: #60cdff; color: #000000; font-weight: 600; border-radius: 4px; padding: 8px 20px; border: none; }
QPushButton#PrimaryButton:hover { background-color: #7ce0ff; }
QPushButton#PrimaryButton:pressed { background-color: #50b0db; }
QPushButton#PrimaryButton:disabled { background-color: #333333; color: #777777; }
QPushButton#GhostButton { background-color: transparent; color: #cccccc; border-radius: 4px; padding: 4px; }
QPushButton#GhostButton:hover { background-color: #383838; color: #ffffff; }
QScrollArea { border: none; background-color: transparent; }
QProgressBar { border: none; background-color: #1e1e1e; height: 3px; }
QProgressBar::chunk { background-color: #60cdff; }
QListWidget { background-color: #2b2b2b; border: 1px solid #3b3b3b; border-radius: 8px; outline: 0; padding: 4px; }
QListWidget::item { background-color: transparent; border-radius: 4px; padding: 8px; margin-bottom: 2px; }
QListWidget::item:hover { background-color: #383838; }
QListWidget::item:selected { background-color: #383838; border-left: 3px solid #60cdff; }
QMenu { background-color: rgba(30, 30, 30, 230); border: 1px solid #555555; padding: 5px; border-radius: 8px; }
QMenu::item { background-color: transparent; color: #eeeeee; padding: 8px 20px; margin: 2px 4px; border-radius: 4px; border: none; }
QMenu::item:selected { background-color: rgba(255, 255, 255, 30); color: #ffffff; }
QMenu::item:pressed { background-color: rgba(255, 255, 255, 50); }
QMenu::separator { height: 1px; background-color: #555555; margin: 4px 10px; }
QMessageBox { background-color: #2b2b2b; border: 1px solid #454545; }
QMessageBox QLabel { color: #e0e0e0; }
QMessageBox QPushButton { background-color: #383838; color: white; border: 1px solid #454545; border-radius: 4px; padding: 6px 24px; }
QMessageBox QPushButton:hover { background-color: #454545; border-color: #555; }
"""

class AdaptiveGridLayout(QLayout):
    def __init__(self, parent=None, min_spacing=20):
        super(AdaptiveGridLayout, self).__init__(parent)
        self._items = []; self._min_spacing = min_spacing
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
        effective_width = rect.width(); item_w, item_h = CARD_SIZE
        if self._items:
            n_cols = 1
            while True:
                required_w = (n_cols * item_w) + ((n_cols + 1) * self._min_spacing)
                if required_w > effective_width: n_cols -= 1; break
                n_cols += 1
            if n_cols < 1: n_cols = 1
        else: n_cols = 1
        total_item_w = n_cols * item_w; remaining_space = effective_width - total_item_w
        dynamic_spacing = remaining_space / (n_cols + 1)
        if dynamic_spacing < self._min_spacing: dynamic_spacing = self._min_spacing
        x = rect.x() + dynamic_spacing; y = rect.y() + self._min_spacing; current_col = 0
        for item in self._items:
            if not testOnly: item.setGeometry(QRect(QPoint(int(x), int(y)), QSize(item_w, item_h)))
            current_col += 1
            if current_col >= n_cols: current_col = 0; x = rect.x() + dynamic_spacing; y += item_h + self._min_spacing
            else: x += item_w + dynamic_spacing
        return y + item_h + self._min_spacing - rect.y() if current_col > 0 else y - rect.y()

# ==========================================
#  🔥 引擎 (支援 文字 與 圖片 雙模搜尋)
# ==========================================
class ImageSearchEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        print(f"[Engine] Initializing on {self.device.upper()}...")
        try:
            print(f"[Engine] Loading OpenCLIP model: {MODEL_NAME}...")
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                MODEL_NAME, pretrained=PRETRAINED, device=self.device
            )
            self.model.eval()
            print(f"[Engine] Loading Tokenizer directly from HuggingFace...")
            self.tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-large')
            if os.path.exists(INDEX_FILE):
                with open(INDEX_FILE, 'rb') as f: data = pickle.load(f)
                self.stored_embeddings = data['embeddings'].to(self.device)
                self.stored_paths = data['paths']
                self.is_ready = True
                print(f"[Engine] Loaded {len(self.stored_paths)} images from {INDEX_FILE}.")
            else: print(f"[Error] Index file not found: {INDEX_FILE}")
        except Exception as e: print(f"[Error] {e}")

    def search(self, query, top_k=20):
        """文字搜尋"""
        if not self.is_ready: return []
        with torch.no_grad():
            inputs = self.tokenizer(query, padding=True, truncation=True, return_tensors="pt").to(self.device)
            text_features = self.model.encode_text(inputs.input_ids)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            text_features = text_features.to(self.stored_embeddings.dtype)
            
        similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
        return self._get_results(similarity, top_k)

    def search_image(self, image_path, top_k=20):
        """🔥 圖片搜尋圖片"""
        if not self.is_ready: return []
        try:
            image = Image.open(image_path).convert('RGB')
            processed_image = self.preprocess(image).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                image_features = self.model.encode_image(processed_image)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                # 重要：確保資料型態一致 (FP16)
                image_features = image_features.to(self.stored_embeddings.dtype)
            
            similarity = (image_features @ self.stored_embeddings.T).squeeze(0)
            return self._get_results(similarity, top_k)
        except Exception as e:
            print(f"[Error] Image search failed: {e}")
            return []

    def _get_results(self, similarity, top_k):
        k = min(top_k, len(self.stored_paths))
        values, indices = similarity.topk(k)
        results = []
        for i in range(k):
            idx = indices[i].item()
            results.append({"score": values[i].item(), "path": self.stored_paths[idx], "filename": os.path.basename(self.stored_paths[idx])})
        return results

class SearchWorker(QThread):
    batch_ready = pyqtSignal(list); finished_search = pyqtSignal(float, int)
    
    # 新增 search_mode 參數
    def __init__(self, engine, query, top_k, img_cache, search_mode="text"): 
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.img_cache = img_cache
        self.search_mode = search_mode

    def run(self):
        start_time = time.time()
        
        # 根據模式選擇搜尋方式
        if self.search_mode == "image":
            raw_results = self.engine.search_image(self.query, self.top_k)
        else:
            raw_results = self.engine.search(self.query, self.top_k)
            
        count = 0; batch_buffer = []; BATCH_SIZE = 5
        for res in raw_results:
            path = res['path']; q_image = None
            if path in self.img_cache: q_image = self.img_cache[path]
            else:
                try:
                    with Image.open(path) as img:
                        img.load(); img = img.convert("RGBA"); img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS); data = img.tobytes("raw", "RGBA"); q_image = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy(); self.img_cache[path] = q_image
                except: continue
            if q_image:
                batch_buffer.append((res, q_image)); count += 1
                if len(batch_buffer) >= BATCH_SIZE: self.batch_ready.emit(batch_buffer); batch_buffer = []; time.sleep(0.001)
        if batch_buffer: self.batch_ready.emit(batch_buffer)
        self.finished_search.emit(time.time() - start_time, count)

# ==========================================
#  UI 元件
# ==========================================
class ResultCard(QFrame):
    # 🔥 新增訊號：請求以該圖片進行搜尋
    search_signal = pyqtSignal(str)

    def __init__(self, result_data, q_image):
        super().__init__()
        self.result_data = result_data; self.path = result_data['path']; self.filename = result_data['filename']; self.q_image_thumbnail = q_image
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1]); self.setFrameShape(QFrame.Shape.NoFrame); self.setObjectName("ResultCard")
        self.setStyleSheet("QFrame#ResultCard { background-color: #2b2b2b; border-radius: 8px; border: 1px solid #3b3b3b; } QFrame#ResultCard:hover { background-color: #323232; border: 1px solid #505050; }")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); layout = QVBoxLayout(); layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(8)
        self.img_label = QLabel(); self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.img_label.setStyleSheet("background: transparent; border: none;"); self.img_label.setPixmap(QPixmap.fromImage(q_image)); layout.addWidget(self.img_label)
        text_container = QWidget(); text_container.setStyleSheet("background: transparent; border: none;"); text_layout = QVBoxLayout(text_container); text_layout.setContentsMargins(0, 0, 0, 0); text_layout.setSpacing(2)
        name = result_data['filename']; name = name[:20] + "..." if len(name) > 22 else name
        name_label = QLabel(name); name_label.setStyleSheet("color: #ffffff; font-weight: 500; font-size: 13px;"); name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score_val = result_data['score']; score_color = "#60cdff" if score_val > 0.3 else "#999999"
        score_label = QLabel(f"{score_val:.4f}"); score_label.setStyleSheet(f"color: {score_color}; font-size: 12px; font-family: Consolas, Monospace;"); score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_layout.addWidget(name_label); text_layout.addWidget(score_label); layout.addWidget(text_container); self.setLayout(layout)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: 
            try: os.startfile(self.path) 
            except: pass
        super().mousePressEvent(event)
    def contextMenuEvent(self, event):
        menu = QMenu(self); menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground); menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint)
        
        # 🔥 修改功能：移除表情符號，並調整順序
        action_search_sim = QAction("Search Similar Images", self)
        action_search_sim.triggered.connect(self.trigger_image_search)
        
        action_copy = QAction("Copy Image", self); action_copy.triggered.connect(self.copy_image)
        action_copy_path = QAction("Copy Path", self); action_copy_path.triggered.connect(self.copy_path)
        action_properties = QAction("Properties", self); action_properties.triggered.connect(self.show_properties)
        
        # 順序：1. Copy Image, 2. Copy Path, 3. Search Similar Images, 4. Properties
        menu.addAction(action_copy)
        menu.addAction(action_copy_path)
        menu.addAction(action_search_sim) # 第 3 順位
        menu.addSeparator()
        menu.addAction(action_properties)
        
        menu.exec(event.globalPos())
    
    def trigger_image_search(self):
        # 發送訊號給父視窗
        self.search_signal.emit(self.path)

    def copy_image(self):
        try:
            original_img = QImage(self.path)
            if not original_img.isNull(): QApplication.clipboard().setImage(original_img)
            else: QApplication.clipboard().setImage(self.q_image_thumbnail)
        except: pass
    def copy_path(self): QApplication.clipboard().setText(self.path)
    def show_properties(self):
        try:
            info = QFileInfo(self.path); size_mb = info.size() / (1024 * 1024); created = info.birthTime().toString("yyyy-MM-dd HH:mm"); img = QImage(self.path); width, height = img.width(), img.height()
            msg_content = f"<h3 style='color: white; font-family: Segoe UI; margin: 0;'>{self.filename}</h3><div style='margin-top: 10px; margin-bottom: 10px; height: 1px; background-color: #555555;'></div><table cellspacing='5' cellpadding='2' style='font-size: 13px;'><tr><td style='color:#aaaaaa;'>Type</td><td style='color:white;'>{info.suffix().upper()}</td></tr><tr><td style='color:#aaaaaa;'>Size</td><td style='color:white;'>{size_mb:.2f} MB</td></tr><tr><td style='color:#aaaaaa;'>Dimensions</td><td style='color:white;'>{width} x {height}</td></tr><tr><td style='color:#aaaaaa;'>Created</td><td style='color:white;'>{created}</td></tr><tr><td style='color:#aaaaaa;'>Path</td><td style='color:#dddddd;'>{self.path}</td></tr></table>"
            box = QMessageBox(self); box.setWindowTitle("Properties"); box.setTextFormat(Qt.TextFormat.RichText); box.setText(msg_content); box.addButton("Close", QMessageBox.ButtonRole.AcceptRole); box.exec()
        except: pass

class HistoryItemWidget(QWidget):
    def __init__(self, text, search_callback, delete_callback):
        super().__init__(); self.text = text; self.search_callback = search_callback; self.delete_callback = delete_callback
        layout = QHBoxLayout(self); layout.setContentsMargins(10, 0, 5, 0)
        self.label = QLabel(text); self.label.setStyleSheet("color: #eeeeee; background: transparent;"); self.label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.label.mousePressEvent = self.on_label_clicked
        layout.addWidget(self.label, stretch=1)
        self.del_btn = QPushButton("×"); self.del_btn.setObjectName("GhostButton"); self.del_btn.setFixedSize(28, 28); self.del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.del_btn.setStyleSheet("QPushButton { font-size: 18px; padding-bottom: 4px; } QPushButton:hover { color: #ff6b6b; background-color: #3e3e3e; }")
        self.del_btn.clicked.connect(self.on_delete_clicked); layout.addWidget(self.del_btn)
    def on_label_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.search_callback(self.text)
    def on_delete_clicked(self): self.delete_callback(self.text)

class AdaptiveResultView(QScrollArea):
    # 🔥 新增訊號：轉發以圖搜圖請求
    image_search_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #1e1e1e;")
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
                # 連接卡片的搜尋訊號到 View 的訊號
                card.search_signal.connect(self.image_search_requested.emit)
                self.adaptive_layout.addWidget(card)
        finally:
            self.container.setUpdatesEnabled(True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(WINDOW_TITLE); self.resize(1280, 900); self.engine = None; self.img_cache = {}; self.search_history = [] 
        self.load_history(); self.init_ui(); QApplication.instance().installEventFilter(self); threading.Thread(target=self.load_engine, daemon=True).start()
    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f: self.search_history = json.load(f)
            except: self.search_history = []
    def save_history_to_file(self):
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(self.search_history, f, ensure_ascii=False)
        except: pass
    def add_to_history(self, query):
        if not query: return
        if query in self.search_history: self.search_history.remove(query)
        self.search_history.insert(0, query); 
        if len(self.search_history) > 10: self.search_history = self.search_history[:10]
        self.save_history_to_file()
    def init_ui(self):
        central = QWidget(); self.setCentralWidget(central); layout = QVBoxLayout(central); layout.setSpacing(0); layout.setContentsMargins(0, 0, 0, 0)
        top_bar = QFrame(); top_bar.setFixedHeight(90); top_bar.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #333;")
        header_layout = QHBoxLayout(top_bar); header_layout.setContentsMargins(30, 0, 30, 0); header_layout.setSpacing(15)
        title_label = QLabel("AI Search"); title_label.setStyleSheet("color: #e0e0e0; font-size: 18px; font-weight: 600; letter-spacing: 0.5px;"); header_layout.addWidget(title_label); header_layout.addStretch(1)
        search_container = QWidget(); search_container.setFixedWidth(600); search_layout = QHBoxLayout(search_container); search_layout.setContentsMargins(0, 0, 0, 0); search_layout.setSpacing(10)
        self.input = QLineEdit(); self.input.setPlaceholderText("Type to search..."); self.input.returnPressed.connect(self.start_search)
        self.combo_limit = QComboBox(); self.combo_limit.addItems(["20", "50", "100", "All"]); self.combo_limit.setCurrentText("50")
        self.btn = QPushButton("Search"); self.btn.setObjectName("PrimaryButton"); self.btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.btn.clicked.connect(self.start_search); self.btn.setEnabled(False) 
        search_layout.addWidget(self.input, stretch=1); search_layout.addWidget(self.combo_limit); search_layout.addWidget(self.btn); header_layout.addWidget(search_container); header_layout.addStretch(1) 
        self.status = QLabel("Initializing..."); self.status.setStyleSheet("color: #888888; font-size: 12px;"); header_layout.addWidget(self.status); layout.addWidget(top_bar)
        self.progress = QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        
        self.view_component = AdaptiveResultView()
        # 🔥 連接 View 的圖片搜尋請求到 Main Window 的處理函式
        self.view_component.image_search_requested.connect(self.start_image_search)
        layout.addWidget(self.view_component)
        
        self.history_list = QListWidget(self); self.history_list.hide(); self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus); shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(20); shadow.setColor(QColor(0, 0, 0, 100)); shadow.setOffset(0, 4); self.history_list.setGraphicsEffect(shadow)
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if self.history_list.isVisible():
                click_pos = event.globalPosition().toPoint(); input_global_pos = self.input.mapToGlobal(QPoint(0, 0)); input_rect = QRect(input_global_pos, self.input.size()); list_global_pos = self.history_list.mapToGlobal(QPoint(0, 0)); list_rect = QRect(list_global_pos, self.history_list.size())
                if not input_rect.contains(click_pos) and not list_rect.contains(click_pos): self.history_list.hide()
            if obj == self.input: self.show_history_popup()
        return super().eventFilter(obj, event)
    def show_history_popup(self):
        if not self.search_history: self.history_list.hide(); return
        self.history_list.clear(); title_item = QListWidgetItem(); title_widget = QLabel(" Recent Searches"); title_widget.setStyleSheet("color: #888888; font-size: 12px; padding: 4px;"); title_item.setFlags(Qt.ItemFlag.NoItemFlags); title_item.setSizeHint(QSize(0, 30)); self.history_list.addItem(title_item); self.history_list.setItemWidget(title_item, title_widget)
        for text in self.search_history: item = QListWidgetItem(); item.setSizeHint(QSize(0, 44)); widget = HistoryItemWidget(text, search_callback=self.trigger_history_search, delete_callback=self.delete_history_item); self.history_list.addItem(item); self.history_list.setItemWidget(item, widget)
        input_pos = self.input.mapTo(self, QPoint(0, 0)); input_h = self.input.height(); input_w = self.input.width(); list_height = min(320, self.history_list.sizeHintForRow(0) * (len(self.search_history) + 1) + 20); self.history_list.setGeometry(input_pos.x(), input_pos.y() + input_h + 8, input_w, list_height); self.history_list.show(); self.history_list.raise_()
    def resizeEvent(self, event): self.history_list.hide(); super().resizeEvent(event)
    def delete_history_item(self, text):
        if text in self.search_history: self.search_history.remove(text); self.save_history_to_file(); self.show_history_popup()
    def trigger_history_search(self, text): self.input.setText(text); self.start_search()
    def load_engine(self):
        try: self.engine = ImageSearchEngine(); QApplication.processEvents(); self.status.setText("System Ready"); self.btn.setEnabled(True)
        except Exception as e: print(e)
    def start_search(self):
        q = self.input.text().strip(); 
        if not q or not self.engine: return
        self.add_to_history(q); self.history_list.hide(); self.btn.setEnabled(False); self.progress.show(); self.progress.setRange(0, 0); self.status.setText("Searching..."); limit = self.combo_limit.currentText(); k = 100000 if limit == "All" else int(limit); self.view_component.clear(); 
        # 啟動文字搜尋 Worker
        self.worker = SearchWorker(self.engine, q, k, self.img_cache, search_mode="text"); 
        self.worker.batch_ready.connect(self.view_component.add_items); self.worker.finished_search.connect(self.on_finished); self.worker.finished.connect(self.worker.deleteLater); self.worker.start()
    
    # 🔥 新增：啟動圖片搜尋
    def start_image_search(self, image_path):
        if not self.engine: return
        self.history_list.hide(); self.btn.setEnabled(False); self.progress.show(); self.progress.setRange(0, 0)
        self.status.setText("Searching by Image..."); 
        # 更新輸入框顯示圖片檔名，讓使用者知道現在在搜這張圖
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        
        limit = self.combo_limit.currentText(); k = 100000 if limit == "All" else int(limit); self.view_component.clear(); 
        # 啟動圖片搜尋 Worker (search_mode="image")
        self.worker = SearchWorker(self.engine, image_path, k, self.img_cache, search_mode="image"); 
        self.worker.batch_ready.connect(self.view_component.add_items); self.worker.finished_search.connect(self.on_finished); self.worker.finished.connect(self.worker.deleteLater); self.worker.start()

    def on_finished(self, elapsed, total): self.progress.hide(); self.btn.setEnabled(True); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv); app.setStyleSheet(WIN11_STYLESHEET); w = MainWindow(); w.show(); sys.exit(app.exec())
import sys
import os
import time
import sqlite3
import threading
import json
from PIL import Image
import torch
import numpy as np
import open_clip
from transformers import AutoTokenizer 

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox,
                             QGraphicsDropShadowEffect, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent, QFileInfo
from PyQt6.QtGui import QPixmap, QImage, QCursor, QAction, QColor, QFont

# --- 設定區 ---
DB_FILE = "images.db"
HISTORY_FILE = "search_history.json"
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'

THUMBNAIL_SIZE = (220, 220)
CARD_SIZE = (240, 280) 
MIN_SPACING = 24       
WINDOW_TITLE = "Local AI Search (Hybrid: CLIP + OCR + Filename)"

# --- 樣式表 (保留 main-OSQ 風格) ---
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
QMenu { background-color: rgba(30, 30, 30, 250); border: 1px solid #555555; padding: 5px; border-radius: 8px; }
QMenu::item { background-color: transparent; color: #eeeeee; padding: 8px 20px; margin: 2px 4px; border-radius: 4px; border: none; }
QMenu::item:selected { background-color: rgba(255, 255, 255, 30); color: #ffffff; }
QMenu::item:pressed { background-color: rgba(255, 255, 255, 50); }
QMenu::separator { height: 1px; background-color: #555555; margin: 4px 10px; }
QMessageBox { background-color: #2b2b2b; border: 1px solid #454545; }
QMessageBox QLabel { color: #e0e0e0; }
QMessageBox QPushButton { background-color: #383838; color: white; border: 1px solid #454545; border-radius: 4px; padding: 6px 24px; }
QMessageBox QPushButton:hover { background-color: #454545; border-color: #555; }
QCheckBox { color: #ccc; spacing: 5px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #555; border-radius: 3px; background: #2d2d2d; }
QCheckBox::indicator:checked { background-color: #60cdff; border: 1px solid #60cdff; }
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
#  引擎核心 (SQLite + CLIP + OCR Read)
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
            self.tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-large')

            if os.path.exists(DB_FILE):
                self.load_data_from_db()
            else:
                print(f"[Error] Database file not found: {DB_FILE}")

        except Exception as e:
            print(f"[Error] Engine initialization failed: {e}")

    def load_data_from_db(self):
        print(f"[Engine] Connecting to database: {DB_FILE}...")
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        try:
            # 讀取 file_path, embedding 以及 ocr_text
            # 注意：如果資料庫是舊的(沒有 ocr_text)，這裡會報錯，需要重新建立索引
            cursor.execute("SELECT file_path, embedding, ocr_text FROM images")
            rows = cursor.fetchall()
            
            self.data_store = [] 
            embeddings_list = []
            
            for path, blob, ocr_text in rows:
                emb_array = np.frombuffer(blob, dtype=np.float32)
                embeddings_list.append(emb_array)
                
                # 處理 OCR 文字 (若是 None 則轉空字串)
                text_content = ocr_text if ocr_text else ""
                
                self.data_store.append({
                    "path": path,
                    "filename": os.path.basename(path),
                    "ocr_text": text_content.lower() # 預先轉小寫加速比對
                })

            if self.data_store:
                emb_matrix = np.stack(embeddings_list)
                self.stored_embeddings = torch.from_numpy(emb_matrix).to(self.device)
                self.is_ready = True
                print(f"[Engine] Loaded {len(self.data_store)} records.")
            else:
                print("[Engine] Database is empty.")
                
        except sqlite3.Error as e:
            print(f"[Error] Database query failed: {e}")
        finally:
            if conn: conn.close()

    def search_hybrid(self, query, top_k=50, use_ocr=True):
        """混合搜尋邏輯：CLIP + OCR + 檔名"""
        if not self.is_ready: return []
        
        results = []
        query_lower = query.lower()
        
        # 1. 計算 CLIP 視覺分數
        try:
            with torch.no_grad():
                inputs = self.tokenizer(query, padding=True, truncation=True, return_tensors="pt").to(self.device)
                text_features = self.model.encode_text(inputs.input_ids)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                text_features = text_features.to(self.stored_embeddings.dtype)
            
            similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
            scores = similarity.cpu().numpy()
            
        except Exception as e:
            print(f"CLIP Search Error: {e}")
            scores = np.zeros(len(self.data_store))

        # 2. 計算加權總分
        for idx, item in enumerate(self.data_store):
            clip_score = float(scores[idx])
            ocr_bonus = 0.0
            name_bonus = 0.0
            
            # 第一重加分：OCR 文字命中 (+0.5)
            if use_ocr and query_lower in item["ocr_text"]:
                ocr_bonus = 0.5
            
            # 第二重加分：檔名命中 (+0.2)
            if query_lower in item["filename"].lower():
                name_bonus = 0.2
                
            final_score = clip_score + ocr_bonus + name_bonus
            
            # 過濾掉太低分的 (可調整閾值)
            if final_score > 0.15: 
                results.append({
                    "score": final_score,
                    "clip_score": clip_score,
                    "ocr_bonus": ocr_bonus,
                    "name_bonus": name_bonus,
                    "is_ocr_match": (ocr_bonus > 0),
                    "path": item["path"],
                    "filename": item["filename"]
                })
        
        # 3. 排序與切片
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_image(self, image_path, top_k=50):
        """以圖搜圖 (維持原樣，但統一回傳格式)"""
        if not self.is_ready: return []
        try:
            image = Image.open(image_path).convert('RGB')
            processed_image = self.preprocess(image).unsqueeze(0).to(self.device)
            
            with torch.no_grad():
                image_features = self.model.encode_image(processed_image)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                image_features = image_features.to(self.stored_embeddings.dtype)
            
            similarity = (image_features @ self.stored_embeddings.T).squeeze(0)
            
            # 取得 Top K
            k = min(top_k, len(self.data_store))
            values, indices = similarity.topk(k)
            
            results = []
            for i in range(k):
                idx = indices[i].item()
                item = self.data_store[idx]
                score = values[i].item()
                results.append({
                    "score": score,
                    "clip_score": score, # 以圖搜圖時，基礎分就是 CLIP 分
                    "ocr_bonus": 0.0,
                    "name_bonus": 0.0,
                    "is_ocr_match": False,
                    "path": item["path"],
                    "filename": item["filename"]
                })
            return results
        except Exception as e:
            print(f"[Error] Image search failed: {e}")
            return []

class SearchWorker(QThread):
    batch_ready = pyqtSignal(list); finished_search = pyqtSignal(float, int)
    
    def __init__(self, engine, query, top_k, img_cache, search_mode="text", use_ocr=True): 
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.img_cache = img_cache
        self.search_mode = search_mode
        self.use_ocr = use_ocr

    def run(self):
        start_time = time.time()
        
        if self.search_mode == "image":
            raw_results = self.engine.search_image(self.query, self.top_k)
        else:
            # 使用混合搜尋
            raw_results = self.engine.search_hybrid(self.query, self.top_k, self.use_ocr)
            
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
    search_signal = pyqtSignal(str)

    def __init__(self, result_data, q_image):
        super().__init__()
        self.result_data = result_data
        self.path = result_data['path']
        self.filename = result_data['filename']
        self.q_image_thumbnail = q_image
        
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1])
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("ResultCard")
        
        # 根據是否為 OCR 命中改變邊框顏色
        border_color = "#3b3b3b"
        if result_data.get('is_ocr_match', False):
            border_color = "#4caf50" # 綠色代表文字命中
            
        self.setStyleSheet(f"""
            QFrame#ResultCard {{ background-color: #2b2b2b; border-radius: 8px; border: 1px solid {border_color}; }} 
            QFrame#ResultCard:hover {{ background-color: #323232; border: 1px solid #505050; }}
        """)
        
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = QVBoxLayout(); layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(8)
        
        self.img_label = QLabel(); self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet("background: transparent; border: none;")
        self.img_label.setPixmap(QPixmap.fromImage(q_image))
        layout.addWidget(self.img_label)
        
        text_container = QWidget(); text_container.setStyleSheet("background: transparent; border: none;")
        text_layout = QVBoxLayout(text_container); text_layout.setContentsMargins(0, 0, 0, 0); text_layout.setSpacing(2)
        
        name = result_data['filename']; name = name[:20] + "..." if len(name) > 22 else name
        name_label = QLabel(name); name_label.setStyleSheet("color: #ffffff; font-weight: 500; font-size: 13px;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 顯示總分
        score_val = result_data['score']
        score_color = "#60cdff" if score_val > 0.3 else "#999999"
        
        meta_layout = QHBoxLayout()
        score_label = QLabel(f"{score_val:.4f}")
        score_label.setStyleSheet(f"color: {score_color}; font-size: 12px; font-family: Consolas, Monospace;")
        meta_layout.addWidget(score_label)
        
        # 如果有 OCR 命中，顯示小標籤
        if result_data.get('is_ocr_match', False):
            ocr_tag = QLabel("TEXT"); ocr_tag.setStyleSheet("background-color: #4caf50; color: white; border-radius: 2px; padding: 1px 3px; font-size: 10px; font-weight: bold;")
            meta_layout.addWidget(ocr_tag)
        
        meta_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_layout.addWidget(name_label)
        text_layout.addLayout(meta_layout)
        
        layout.addWidget(text_container)
        self.setLayout(layout)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: 
            try: os.startfile(self.path) 
            except: pass
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint)
        
        action_copy = QAction("Copy Image", self); action_copy.triggered.connect(self.copy_image)
        action_copy_path = QAction("Copy Path", self); action_copy_path.triggered.connect(self.copy_path)
        action_search_sim = QAction("Search Similar Images", self); action_search_sim.triggered.connect(self.trigger_image_search)
        action_score = QAction("Score Details", self); action_score.triggered.connect(self.show_score_details) # 新增詳細分數
        action_properties = QAction("Properties", self); action_properties.triggered.connect(self.show_properties)
        
        menu.addAction(action_copy)
        menu.addAction(action_copy_path)
        menu.addAction(action_search_sim)
        menu.addSeparator()
        menu.addAction(action_score) # 加入選單
        menu.addAction(action_properties)
        
        menu.exec(event.globalPos())
    
    def trigger_image_search(self):
        self.search_signal.emit(self.path)

    def show_score_details(self):
        # 顯示詳細分數
        d = self.result_data
        msg = f"""
        <h3 style='color:white; margin:0;'>Score Breakdown</h3>
        <div style='height:1px; background:#555; margin:10px 0;'></div>
        <table style='color:#ddd; font-size:13px;'>
        <tr><td>Total Score:</td><td style='color:#60cdff; font-weight:bold;'>{d['score']:.4f}</td></tr>
        <tr><td>CLIP (Visual):</td><td>{d['clip_score']:.4f}</td></tr>
        <tr><td>OCR Bonus:</td><td style='color:#4caf50;'>+{d['ocr_bonus']:.2f}</td></tr>
        <tr><td>Filename Bonus:</td><td style='color:#ffb74d;'>+{d['name_bonus']:.2f}</td></tr>
        </table>
        """
        box = QMessageBox(self)
        box.setWindowTitle("Score Details")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(msg)
        box.addButton("Close", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

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
        self.del_btn = QPushButton("x"); self.del_btn.setObjectName("GhostButton"); self.del_btn.setFixedSize(28, 28); self.del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.del_btn.setStyleSheet("QPushButton { font-size: 18px; padding-bottom: 4px; } QPushButton:hover { color: #ff6b6b; background-color: #3e3e3e; }")
        self.del_btn.clicked.connect(self.on_delete_clicked); layout.addWidget(self.del_btn)
    def on_label_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.search_callback(self.text)
    def on_delete_clicked(self): self.delete_callback(self.text)

class AdaptiveResultView(QScrollArea):
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
        
        title_label = QLabel("AI Search"); title_label.setStyleSheet("color: #e0e0e0; font-size: 18px; font-weight: 600; letter-spacing: 0.5px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        
        search_container = QWidget(); search_container.setFixedWidth(600); search_layout = QHBoxLayout(search_container); search_layout.setContentsMargins(0, 0, 0, 0); search_layout.setSpacing(10)
        self.input = QLineEdit(); self.input.setPlaceholderText("Type to search..."); self.input.returnPressed.connect(self.start_search)
        
        # 新增 OCR Checkbox
        self.chk_ocr = QCheckBox("OCR"); self.chk_ocr.setChecked(True)
        self.chk_ocr.setToolTip("Enable Text Search inside images")
        
        self.combo_limit = QComboBox(); self.combo_limit.addItems(["20", "50", "100", "All"]); self.combo_limit.setCurrentText("50")
        self.btn = QPushButton("Search"); self.btn.setObjectName("PrimaryButton"); self.btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.btn.clicked.connect(self.start_search); self.btn.setEnabled(False) 
        
        search_layout.addWidget(self.input, stretch=1)
        search_layout.addWidget(self.chk_ocr) # 加入 Checkbox
        search_layout.addWidget(self.combo_limit)
        search_layout.addWidget(self.btn)
        
        header_layout.addWidget(search_container)
        header_layout.addStretch(1) 
        
        self.status = QLabel("Initializing..."); self.status.setStyleSheet("color: #888888; font-size: 12px;"); header_layout.addWidget(self.status); layout.addWidget(top_bar)
        self.progress = QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        
        self.view_component = AdaptiveResultView()
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
        # 傳遞 OCR Checkbox 的狀態
        self.worker = SearchWorker(self.engine, q, k, self.img_cache, search_mode="text", use_ocr=self.chk_ocr.isChecked()); 
        self.worker.batch_ready.connect(self.view_component.add_items); self.worker.finished_search.connect(self.on_finished); self.worker.finished.connect(self.worker.deleteLater); self.worker.start()
    
    def start_image_search(self, image_path):
        if not self.engine: return
        self.history_list.hide(); self.btn.setEnabled(False); self.progress.show(); self.progress.setRange(0, 0)
        self.status.setText("Searching by Image..."); 
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        
        limit = self.combo_limit.currentText(); k = 100000 if limit == "All" else int(limit); self.view_component.clear(); 
        self.worker = SearchWorker(self.engine, image_path, k, self.img_cache, search_mode="image"); 
        self.worker.batch_ready.connect(self.view_component.add_items); self.worker.finished_search.connect(self.on_finished); self.worker.finished.connect(self.worker.deleteLater); self.worker.start()

    def on_finished(self, elapsed, total): self.progress.hide(); self.btn.setEnabled(True); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv); app.setStyleSheet(WIN11_STYLESHEET); w = MainWindow(); w.show(); sys.exit(app.exec())
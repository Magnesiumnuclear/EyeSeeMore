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
                             QGraphicsDropShadowEffect, QCheckBox, QToolTip)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent, QFileInfo
from PyQt6.QtGui import QPixmap, QImage, QCursor, QAction, QColor, QFont, QIcon

import ctypes
from ctypes import wintypes

# --- 設定區 ---
DB_FILE = "images.db"
HISTORY_FILE = "search_history.json"
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'

THUMBNAIL_SIZE = (240, 240) # 稍微加大一點
CARD_SIZE = (260, 320)      # 卡片變高，容納 OCR 標籤
MIN_SPACING = 20
WINDOW_TITLE = "AI Neural Search (CLIP + OCR)"

# --- 樣式表 (維持暗色系) ---
WIN11_STYLESHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #f0f0f0; font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; font-size: 14px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-bottom: 2px solid #505050; border-radius: 4px; padding: 10px 12px; color: #ffffff; font-size: 16px; selection-background-color: #005fb8; }
QLineEdit:focus { border-bottom: 2px solid #60cdff; background-color: #323232; }
QComboBox { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 4px; padding: 6px; min-width: 80px; }
QComboBox:hover { background-color: #383838; }
QPushButton#PrimaryButton { background-color: #60cdff; color: #000000; font-weight: 700; border-radius: 4px; padding: 8px 24px; border: none; }
QPushButton#PrimaryButton:hover { background-color: #7ce0ff; }
QPushButton#PrimaryButton:pressed { background-color: #50b0db; }
QPushButton#PrimaryButton:disabled { background-color: #333333; color: #777777; }
QScrollArea { border: none; background-color: transparent; }
QProgressBar { border: none; background-color: #1e1e1e; height: 3px; }
QProgressBar::chunk { background-color: #60cdff; }
QListWidget { background-color: #2b2b2b; border: 1px solid #3b3b3b; border-radius: 8px; outline: 0; }
QListWidget::item { padding: 8px; }
QListWidget::item:selected { background-color: #383838; border-left: 3px solid #60cdff; }
QMenu { background-color: #2b2b2b; border: 1px solid #454545; padding: 5px; }
QMenu::item { padding: 6px 20px; color: #eeeeee; }
QMenu::item:selected { background-color: #383838; }
QToolTip { background-color: #2b2b2b; color: #ffffff; border: 1px solid #555555; padding: 5px; }
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
#  引擎核心 (SQLite + CLIP)
# ==========================================
class ImageSearchEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        print(f"[Engine] Initializing on {self.device.upper()}...")
        
        try:
            print(f"[Engine] Loading OpenCLIP: {MODEL_NAME}...")
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
            # 讀取 ocr_text 欄位 (如果舊資料庫沒有這個欄位，這裡可能會報錯，請先跑一次 indexer)
            cursor.execute("SELECT file_path, embedding, ocr_text FROM images")
            rows = cursor.fetchall()
            
            self.data_store = [] # 用於存儲 (path, embedding_tensor, ocr_text)
            embeddings_list = []
            
            for path, blob, ocr_text in rows:
                emb_array = np.frombuffer(blob, dtype=np.float32)
                embeddings_list.append(emb_array)
                # 處理 None 的文字
                text_content = ocr_text if ocr_text else ""
                self.data_store.append({
                    "path": path,
                    "ocr_text": text_content.lower(), # 預先轉小寫加速搜尋
                    "filename": os.path.basename(path)
                })

            if self.data_store:
                emb_matrix = np.stack(embeddings_list)
                self.stored_embeddings = torch.from_numpy(emb_matrix).to(self.device)
                self.is_ready = True
                print(f"[Engine] Loaded {len(self.data_store)} records.")
            else:
                print("[Engine] Database is empty.")
                
        except Exception as e:
            print(f"[Error] DB Load failed: {e}")
        finally:
            conn.close()

    def search_hybrid(self, query, top_k=50, use_ocr=True):
        """混合搜尋：CLIP 語義 + OCR 文字匹配"""
        if not self.is_ready: return []
        
        results = []
        query_lower = query.lower()
        
        # 1. 計算 CLIP 分數 (Semantic Score)
        try:
            with torch.no_grad():
                inputs = self.tokenizer(query, padding=True, truncation=True, return_tensors="pt").to(self.device)
                text_features = self.model.encode_text(inputs.input_ids)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                text_features = text_features.to(self.stored_embeddings.dtype)
            
            # 向量相似度
            similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
            scores = similarity.cpu().numpy() # 轉回 CPU 方便處理
            
        except Exception as e:
            print(f"CLIP Search Error: {e}")
            scores = np.zeros(len(self.data_store))

        # 2. 混合邏輯
        for idx, item in enumerate(self.data_store):
            clip_score = float(scores[idx])
            ocr_score = 0.0
            
            # OCR 加權邏輯
            if use_ocr and query_lower in item["ocr_text"]:
                ocr_score = 0.5  # 如果 OCR 文字中有關鍵字，直接加 0.5 分 (相當於把相關性拉很高)
            
            # 檔案名稱加權 (也很有用)
            if query_lower in item["filename"].lower():
                ocr_score += 0.2
                
            final_score = clip_score + ocr_score
            
            # 過濾掉太低分的
            if final_score > 0.15: 
                results.append({
                    "score": final_score,
                    "clip_score": clip_score,
                    "is_ocr_match": (ocr_score > 0.3), # 標記是否為文字命中
                    "path": item["path"],
                    "filename": item["filename"],
                    "ocr_text": item["ocr_text"]
                })
        
        # 3. 排序與切片
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_image(self, image_path, top_k=50):
        if not self.is_ready: return []
        try:
            image = Image.open(image_path).convert('RGB')
            processed_image = self.preprocess(image).unsqueeze(0).to(self.device)
            with torch.no_grad():
                image_features = self.model.encode_image(processed_image)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                image_features = image_features.to(self.stored_embeddings.dtype)
            similarity = (image_features @ self.stored_embeddings.T).squeeze(0)
            
            # 這裡回傳標準格式
            values, indices = similarity.topk(min(top_k, len(self.data_store)))
            results = []
            for i in range(len(indices)):
                idx = indices[i].item()
                item = self.data_store[idx]
                results.append({
                    "score": values[i].item(),
                    "clip_score": values[i].item(),
                    "is_ocr_match": False,
                    "path": item["path"],
                    "filename": item["filename"],
                    "ocr_text": item["ocr_text"]
                })
            return results
        except Exception as e:
            print(f"Image search error: {e}")
            return []

class SearchWorker(QThread):
    batch_ready = pyqtSignal(list); finished_search = pyqtSignal(float, int)
    
    def __init__(self, engine, query, top_k, img_cache, mode="text", use_ocr=True): 
        super().__init__()
        self.engine = engine; self.query = query; self.top_k = top_k
        self.img_cache = img_cache; self.mode = mode; self.use_ocr = use_ocr

    def run(self):
        t0 = time.time()
        if self.mode == "image":
            raw_results = self.engine.search_image(self.query, self.top_k)
        else:
            raw_results = self.engine.search_hybrid(self.query, self.top_k, self.use_ocr)
            
        batch = []
        for res in raw_results:
            path = res['path']
            if path not in self.img_cache:
                try:
                    with Image.open(path) as img:
                        img.load(); img = img.convert("RGBA"); img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                        data = img.tobytes("raw", "RGBA")
                        q_img = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy()
                        self.img_cache[path] = q_img
                except: continue
            
            batch.append((res, self.img_cache[path]))
            if len(batch) >= 5:
                self.batch_ready.emit(batch); batch = []; time.sleep(0.005)
        
        if batch: self.batch_ready.emit(batch)
        self.finished_search.emit(time.time() - t0, len(raw_results))

# ==========================================
#  UI 元件
# ==========================================
class ResultCard(QFrame):
    search_signal = pyqtSignal(str)

    def __init__(self, data, q_image):
        super().__init__()
        self.data = data; self.path = data['path']
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1])
        self.setObjectName("ResultCard")
        
        # 根據是否為 OCR 命中改變邊框顏色
        border_color = "#3b3b3b"
        if data.get('is_ocr_match', False):
            border_color = "#4caf50" # 綠色邊框代表文字命中
            
        self.setStyleSheet(f"""
            QFrame#ResultCard {{ background-color: #2b2b2b; border-radius: 8px; border: 1px solid {border_color}; }}
            QFrame#ResultCard:hover {{ background-color: #323232; border: 1px solid #7ce0ff; }}
        """)
        
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 8, 8, 8); layout.setSpacing(5)
        
        # 圖片
        img_lbl = QLabel(); img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setPixmap(QPixmap.fromImage(q_image))
        layout.addWidget(img_lbl)
        
        # 檔名
        name_lbl = QLabel(data['filename']); name_lbl.setStyleSheet("color: white; font-weight: bold;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 分數與標籤
        meta_layout = QHBoxLayout()
        score_lbl = QLabel(f"{data['score']:.2f}")
        score_lbl.setStyleSheet("color: #60cdff; font-family: Consolas;")
        meta_layout.addWidget(score_lbl)
        
        if data.get('is_ocr_match', False):
            ocr_tag = QLabel("TEXT MATCH"); ocr_tag.setStyleSheet("background-color: #4caf50; color: white; border-radius: 3px; padding: 2px 4px; font-size: 10px; font-weight: bold;")
            meta_layout.addWidget(ocr_tag)
            
        meta_layout.addStretch()
        layout.addWidget(name_lbl); layout.addLayout(meta_layout)
        
        # Tooltip 顯示辨識出的文字
        ocr_snippet = data['ocr_text'][:200] + "..." if len(data['ocr_text']) > 200 else data['ocr_text']
        if ocr_snippet:
            self.setToolTip(f"OCR: {ocr_snippet}")
        else:
            self.setToolTip(f"Path: {self.path}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: 
            try: os.startfile(self.path) 
            except: pass
    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.addAction("Search Similar Images", lambda: self.search_signal.emit(self.path))
        menu.addAction("Copy Path", lambda: QApplication.clipboard().setText(self.path))
        menu.exec(e.globalPos())

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE); self.resize(1280, 900)
        self.engine = None; self.img_cache = {}
        self.apply_dark_mode()
        self.init_ui()
        threading.Thread(target=self.load_engine, daemon=True).start()

    def apply_dark_mode(self):
        # 強制 Windows DWM 暗色模式
        try:
            hwnd = int(self.winId())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
        except: pass

    def init_ui(self):
        main_widget = QWidget(); self.setCentralWidget(main_widget)
        root_layout = QVBoxLayout(main_widget); root_layout.setContentsMargins(0, 0, 0, 0); root_layout.setSpacing(0)
        
        # Top Bar
        top_bar = QFrame(); top_bar.setFixedHeight(80); top_bar.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #333;")
        top_layout = QHBoxLayout(top_bar); top_layout.setContentsMargins(20, 0, 20, 0)
        
        title = QLabel("NEURAL SEARCH"); title.setStyleSheet("font-size: 18px; font-weight: 800; color: #888; letter-spacing: 1px;")
        
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("Search for objects, atmosphere, or text inside images...")
        self.search_input.returnPressed.connect(self.start_text_search)
        
        self.btn_search = QPushButton("SEARCH"); self.btn_search.setObjectName("PrimaryButton")
        self.btn_search.clicked.connect(self.start_text_search); self.btn_search.setEnabled(False)
        
        # Checkbox: Enable OCR
        self.chk_ocr = QCheckBox("Enable Text Search (OCR)"); self.chk_ocr.setChecked(True)
        self.chk_ocr.setStyleSheet("QCheckBox { color: #ccc; } QCheckBox::indicator:checked { background-color: #60cdff; }")
        
        top_layout.addWidget(title); top_layout.addSpacing(20)
        top_layout.addWidget(self.search_input, 1); top_layout.addWidget(self.chk_ocr); top_layout.addWidget(self.btn_search)
        
        root_layout.addWidget(top_bar)
        
        # Results Area
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.content_widget = QWidget(); self.grid = AdaptiveGridLayout(self.content_widget)
        self.scroll.setWidget(self.content_widget)
        root_layout.addWidget(self.scroll)
        
        # Status Bar
        self.status_bar = QFrame(); self.status_bar.setFixedHeight(30); self.status_bar.setStyleSheet("background-color: #252525;")
        self.status_lbl = QLabel("Initializing engine..."); self.status_lbl.setStyleSheet("color: #aaa; margin-left: 10px;")
        stat_layout = QHBoxLayout(self.status_bar); stat_layout.setContentsMargins(0,0,0,0)
        stat_layout.addWidget(self.status_lbl); stat_layout.addStretch()
        root_layout.addWidget(self.status_bar)

    def load_engine(self):
        self.engine = ImageSearchEngine()
        if self.engine.is_ready:
            self.status_lbl.setText("Engine Ready. Index loaded.")
            self.btn_search.setEnabled(True)
        else:
            self.status_lbl.setText("Engine Load Failed.")

    def start_text_search(self):
        query = self.search_input.text().strip()
        if not query or not self.engine: return
        self.run_search(query, mode="text")

    def start_image_search(self, path):
        self.search_input.setText(f"[IMAGE] {os.path.basename(path)}")
        self.run_search(path, mode="image")

    def run_search(self, query, mode):
        # Clear Grid
        while self.grid.count(): 
            item = self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        self.status_lbl.setText("Searching...")
        self.btn_search.setEnabled(False)
        
        self.worker = SearchWorker(self.engine, query, 50, self.img_cache, mode, self.chk_ocr.isChecked())
        self.worker.batch_ready.connect(self.add_cards)
        self.worker.finished_search.connect(self.search_done)
        self.worker.start()

    def add_cards(self, batch):
        for data, q_img in batch:
            card = ResultCard(data, q_img)
            card.search_signal.connect(self.start_image_search)
            self.grid.addWidget(card)

    def search_done(self, t, count):
        self.status_lbl.setText(f"Found {count} results in {t:.3f}s")
        self.btn_search.setEnabled(True)

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    # 強制使用 Windows 暗色支援
    sys.argv += ['-platform', 'windows:darkmode=2']
    app = QApplication(sys.argv); app.setStyleSheet(WIN11_STYLESHEET)
    w = MainWindow(); w.show(); sys.exit(app.exec())
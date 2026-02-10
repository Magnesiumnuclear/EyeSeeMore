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
                             QGraphicsDropShadowEffect, QCheckBox, QInputDialog, QDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent, QFileInfo, QTimer
from PyQt6.QtGui import QPixmap, QImage, QCursor, QAction, QColor, QFont, QKeySequence, QShortcut, QFontMetrics

# --- 設定區 ---
DB_FILE = "images.db"
HISTORY_FILE = "search_history.json"
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'

THUMBNAIL_SIZE = (220, 220)
CARD_SIZE = (240, 280) 
MIN_SPACING = 24       
WINDOW_TITLE = "Local AI Search"

# --- 樣式表 ---
WIN11_STYLESHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #ffffff; font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; font-size: 14px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-bottom: 1px solid #505050; border-radius: 4px; padding: 10px 12px; color: #ffffff; font-size: 15px; selection-background-color: #005fb8; }
QLineEdit:focus { border-bottom: 2px solid #60cdff; background-color: #323232; }
QComboBox { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 4px; padding: 6px 10px; min-width: 80px; }
QComboBox:hover { background-color: #383838; }
QComboBox::drop-down { border: none; width: 20px; }
QPushButton#MenuButton { background-color: transparent; border: 1px solid #3e3e3e; border-radius: 4px; padding: 6px 12px; font-weight: bold; }
QPushButton#MenuButton:hover { background-color: #333333; border-color: #666; }
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
/* Scrollbar Styling */
QScrollBar:vertical { border: none; background: #2b2b2b; width: 8px; margin: 0px 0px 0px 0px; border-radius: 4px; }
QScrollBar::handle:vertical { background: #555; min-height: 20px; border-radius: 4px; }
QScrollBar::add-line:vertical { height: 0px; subcontrol-position: bottom; subcontrol-origin: margin; }
QScrollBar::sub-line:vertical { height: 0px; subcontrol-position: top; subcontrol-origin: margin; }
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
#  引擎核心
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
            # [修改] 增加讀取 ocr_data
            cursor.execute("SELECT file_path, embedding, ocr_text, ocr_data FROM images")
            rows = cursor.fetchall()
            
            self.data_store = [] 
            embeddings_list = []
            
            for path, blob, ocr_text, ocr_data_json in rows:
                if not os.path.exists(path): continue 
                emb_array = np.frombuffer(blob, dtype=np.float32)
                embeddings_list.append(emb_array)
                
                text_content = ocr_text if ocr_text else ""
                
                # [修改] 解析 JSON
                ocr_boxes = []
                if ocr_data_json:
                    try: ocr_boxes = json.loads(ocr_data_json)
                    except: pass

                self.data_store.append({
                    "path": path,
                    "filename": os.path.basename(path),
                    "ocr_text": text_content.lower(),
                    "ocr_data": ocr_boxes # 儲存座標數據
                })
            
            # ... (以下保持不變)
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

    def get_folder_stats(self):
        """
        [修改] 統計各資料夾的圖片數量
        優先從 'folder_stats' 表讀取 (由 indexer.py 生成)
        """
        if not os.path.exists(DB_FILE): return []
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            
            # 1. 檢查 folder_stats 表是否存在
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='folder_stats'")
            if cursor.fetchone():
                # 從統計表直接讀取 (速度快)
                cursor.execute("SELECT folder_path, image_count FROM folder_stats ORDER BY folder_path ASC")
            else:
                # Fallback: 如果沒有統計表，使用 Group By 即時計算 (速度較慢)
                print("[Engine] 'folder_stats' table missing. Calculating on the fly...")
                cursor.execute("SELECT folder_path, COUNT(*) FROM images GROUP BY folder_path")
                
            stats = cursor.fetchall()
            conn.close()
            return stats
        except Exception as e:
            print(f"[Error] Failed to get stats: {e}")
            return []

    def rename_file(self, old_path, new_name):
        """重命名檔案並更新資料庫與記憶體，不重跑AI"""
        folder = os.path.dirname(old_path)
        new_path = os.path.join(folder, new_name)
        
        if os.path.exists(new_path):
            return False, "Target filename already exists."

        try:
            # 1. 實體重命名
            os.rename(old_path, new_path)
            
            # 2. 更新資料庫
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("UPDATE images SET file_path = ?, filename = ? WHERE file_path = ?", 
                           (new_path, new_name, old_path))
            conn.commit()
            conn.close()
            
            # 3. 更新記憶體中的索引 (data_store)
            for item in self.data_store:
                if item["path"] == old_path:
                    item["path"] = new_path
                    item["filename"] = new_name
                    break
                    
            return True, new_path
        except Exception as e:
            return False, str(e)


    def search_hybrid(self, query, top_k=50, use_ocr=True):
        if not self.is_ready: return []
        
        results = []
        query_lower = query.lower()
        
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

        for idx, item in enumerate(self.data_store):
            clip_score = float(scores[idx])
            ocr_bonus = 0.0
            name_bonus = 0.0
            
            if use_ocr and query_lower in item["ocr_text"]:
                ocr_bonus = 0.5
            
            if query_lower in item["filename"].lower():
                name_bonus = 0.2
                
            final_score = clip_score + ocr_bonus + name_bonus
            
            if final_score > 0.15: 
                results.append({
                    "score": final_score,
                    "clip_score": clip_score,
                    "ocr_bonus": ocr_bonus,
                    "name_bonus": name_bonus,
                    "is_ocr_match": (ocr_bonus > 0),
                    "path": item["path"],
                    "filename": item["filename"],
                    "ocr_data": item.get("ocr_data", []) # [修正] 這裡原本漏掉了！補上傳遞座標資料
                })
        
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
            
            k = min(top_k, len(self.data_store))
            values, indices = similarity.topk(k)
            
            results = []
            for i in range(k):
                idx = indices[i].item()
                item = self.data_store[idx]
                score = values[i].item()
                results.append({
                    "score": score,
                    "clip_score": score,
                    "ocr_bonus": 0.0,
                    "name_bonus": 0.0,
                    "is_ocr_match": False,
                    "path": item["path"],
                    "filename": item["filename"],
                    "ocr_data": item.get("ocr_data", []) # [修正] 這裡原本也漏掉了！
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
from PyQt6.QtGui import QPainter, QPen, QPolygon

class OCRLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ocr_data = []
        self.show_ocr_boxes = False
        self.original_size = QSize(0, 0) # 圖片原始尺寸

    def set_ocr_data(self, data, orig_w, orig_h):
        self.ocr_data = data
        self.original_size = QSize(orig_w, orig_h)

    def set_draw_boxes(self, show):
        self.show_ocr_boxes = show
        self.update() # 觸發重繪

    def paintEvent(self, event):
        super().paintEvent(event) # 先畫圖片
        
        if self.show_ocr_boxes and self.ocr_data and self.pixmap():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # 設定畫筆 (紅色框，黃色字)
            pen = QPen(QColor(255, 0, 0, 200)) # 紅色半透明
            pen.setWidth(2)
            painter.setPen(pen)
            
            # 計算縮放比例
            displayed_w = self.pixmap().width()
            displayed_h = self.pixmap().height()
            
            # 計算圖片在 Label 中的偏移量 (因為是 Center 對齊)
            offset_x = (self.width() - displayed_w) / 2
            offset_y = (self.height() - displayed_h) / 2
            
            scale_x = displayed_w / self.original_size.width()
            scale_y = displayed_h / self.original_size.height()

            for item in self.ocr_data:
                box = item.get("box") # [[x,y], [x,y], [x,y], [x,y]]
                if box:
                    # 轉換座標
                    poly_points = []
                    for pt in box:
                        nx = pt[0] * scale_x + offset_x
                        ny = pt[1] * scale_y + offset_y
                        poly_points.append(QPoint(int(nx), int(ny)))
                    
                    painter.drawPolygon(QPolygon(poly_points))
# ==========================================
#  UI 元件
# ==========================================
class PreviewOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 220);")
        
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 使用自定義的 Label
        self.image_label = OCRLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: transparent;")
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0,0,0, 150))
        self.image_label.setGraphicsEffect(shadow)
        
        self.layout.addWidget(self.image_label)
        
        self.filename_label = QLabel()
        self.filename_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; background: transparent; margin-top: 10px;")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.filename_label)
        
        self.ocr_hint = QLabel("Hold SHIFT to view OCR text locations")
        self.ocr_hint.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        self.layout.addWidget(self.ocr_hint, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_image(self, result_data):
        path = result_data['path']
        if not os.path.exists(path): return
        
        img = QImage(path)
        if img.isNull(): return
        
        # 確保視窗大小
        screen_size = self.parent().size()
        max_w = int(screen_size.width() * 0.85)
        max_h = int(screen_size.height() * 0.85)
        
        pixmap = QPixmap.fromImage(img)
        pixmap = pixmap.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        self.image_label.setPixmap(pixmap)
        
        # 設定 OCR 數據
        orig_w, orig_h = img.width(), img.height()
        ocr_boxes = result_data.get('ocr_data', [])
        
        # 除錯用：印出有沒有座標資料
        # print(f"Loaded OCR Data for {os.path.basename(path)}: {len(ocr_boxes)} boxes") 
        
        self.image_label.set_ocr_data(ocr_boxes, orig_w, orig_h)
        
        self.filename_label.setText(os.path.basename(path))
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()

    # [新增] 給主視窗呼叫的開關
    def set_ocr_visible(self, visible):
        self.image_label.set_draw_boxes(visible)

    # 移除內部的 KeyPressEvent，改由 MainWindow 控制
    # def keyPressEvent(self, event): ... (已刪除)
    
    # 這裡只保留 Esc 和 Space 關閉功能 (Shift 交給 MainWindow)
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.hide()

    def mousePressEvent(self, event):
        self.hide()

class ResultCard(QFrame):
    search_signal = pyqtSignal(str)
    selected_signal = pyqtSignal(str) # 選取時發出訊號 (回傳路徑)
    rename_signal = pyqtSignal(object) # 發出重命名請求 (回傳自己)

    def __init__(self, result_data, q_image):
        super().__init__()
        self.result_data = result_data
        self.path = result_data['path']
        self.filename = result_data['filename']
        self.q_image_thumbnail = q_image
        self.is_selected = False
        
        self.setFixedSize(CARD_SIZE[0], CARD_SIZE[1])
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("ResultCard")
        
        self.update_style()
        
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        layout = QVBoxLayout(); layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(8)
        
        self.img_label = QLabel(); self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet("background: transparent; border: none;")
        self.img_label.setPixmap(QPixmap.fromImage(q_image))
        layout.addWidget(self.img_label)
        
        text_container = QWidget(); text_container.setStyleSheet("background: transparent; border: none;")
        text_layout = QVBoxLayout(text_container); text_layout.setContentsMargins(0, 0, 0, 0); text_layout.setSpacing(2)
        
        self.name_label = QLabel(self.truncate_name(self.filename))
        self.name_label.setStyleSheet("color: #ffffff; font-weight: 500; font-size: 13px;")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        score_val = result_data['score']
        score_color = "#60cdff" if score_val > 0.3 else "#999999"
        
        meta_layout = QHBoxLayout()
        score_label = QLabel(f"{score_val:.4f}")
        score_label.setStyleSheet(f"color: {score_color}; font-size: 12px; font-family: Consolas, Monospace;")
        meta_layout.addWidget(score_label)
        
        if result_data.get('is_ocr_match', False):
            ocr_tag = QLabel("TEXT"); ocr_tag.setStyleSheet("background-color: #4caf50; color: white; border-radius: 2px; padding: 1px 3px; font-size: 10px; font-weight: bold;")
            meta_layout.addWidget(ocr_tag)
        
        meta_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_layout.addWidget(self.name_label)
        text_layout.addLayout(meta_layout)
        
        layout.addWidget(text_container)
        self.setLayout(layout)

    def truncate_name(self, name):
        return name[:20] + "..." if len(name) > 22 else name

    def update_style(self):
        # 根據是否被選取或 OCR 命中改變邊框
        border_color = "#3b3b3b"
        if self.is_selected:
            border_color = "#60cdff" # 選取時變藍色
            border_width = "2px"
        elif self.result_data.get('is_ocr_match', False):
            border_color = "#4caf50" 
            border_width = "1px"
        else:
            border_width = "1px"
            
        self.setStyleSheet(f"""
            QFrame#ResultCard {{ background-color: #2b2b2b; border-radius: 8px; border: {border_width} solid {border_color}; }} 
            QFrame#ResultCard:hover {{ background-color: #323232; border: 1px solid #7ce0ff; }}
        """)

    def set_selected(self, selected):
        self.is_selected = selected
        self.update_style()

    def update_info(self, new_path, new_filename):
        self.path = new_path
        self.filename = new_filename
        self.name_label.setText(self.truncate_name(new_filename))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: 
            self.selected_signal.emit(self.path)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            try: os.startfile(self.path) 
            except: pass
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint)
        
        action_rename = QAction("Rename", self); action_rename.triggered.connect(lambda: self.rename_signal.emit(self))
        action_copy = QAction("Copy Image", self); action_copy.triggered.connect(self.copy_image)
        action_copy_path = QAction("Copy Path", self); action_copy_path.triggered.connect(self.copy_path)
        action_search_sim = QAction("Search Similar Images", self); action_search_sim.triggered.connect(self.trigger_image_search)
        action_score = QAction("Score Details", self); action_score.triggered.connect(self.show_score_details)
        action_properties = QAction("Properties", self); action_properties.triggered.connect(self.show_properties)
        
        menu.addAction(action_copy)
        menu.addAction(action_copy_path)
        menu.addAction(action_search_sim)
        menu.addSeparator()
        menu.addAction(action_rename) # 新增重命名
        menu.addSeparator()
        menu.addAction(action_score)
        menu.addAction(action_properties)
        
        menu.exec(event.globalPos())
    
    def trigger_image_search(self): self.search_signal.emit(self.path)
    
    def show_score_details(self):
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
        box = QMessageBox(self); box.setWindowTitle("Score Details"); box.setTextFormat(Qt.TextFormat.RichText); box.setText(msg); box.addButton("Close", QMessageBox.ButtonRole.AcceptRole); box.exec()

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
    card_selected = pyqtSignal(str)
    rename_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #1e1e1e;")
        self.adaptive_layout = AdaptiveGridLayout(self.container, min_spacing=MIN_SPACING)
        self.setWidget(self.container)
        self.cards = []
        self.current_idx = -1 # [新增] 追蹤當前索引

    # ... (clear 與 add_items 保持不變) ...
    # 注意：add_items 裡面的 card 要加上索引，或者我們用 cards list 的順序

    def clear(self):
        self.cards = []
        self.current_idx = -1
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
                card.selected_signal.connect(self.on_card_selected_by_click) # 改名區分
                card.rename_signal.connect(self.rename_requested.emit)
                self.adaptive_layout.addWidget(card)
                self.cards.append(card)
        finally:
            self.container.setUpdatesEnabled(True)

    def on_card_selected_by_click(self, path):
        # 找出點擊的是哪個 index
        for i, card in enumerate(self.cards):
            if card.path == path:
                self.set_selection(i)
                break

    def set_selection(self, index):
        if index < 0 or index >= len(self.cards): return
        
        # 取消舊的
        if 0 <= self.current_idx < len(self.cards):
            self.cards[self.current_idx].set_selected(False)
            
        # 設定新的
        self.current_idx = index
        card = self.cards[index]
        card.set_selected(True)
        self.ensureWidgetVisible(card) # 自動滾動
        self.card_selected.emit(card.path)

    def get_selected_data(self):
        if 0 <= self.current_idx < len(self.cards):
            return self.cards[self.current_idx].result_data
        return None

    def navigate(self, direction):
        if not self.cards: return
        
        # 如果還沒選取，從 0 開始
        if self.current_idx == -1:
            self.set_selection(0)
            return

        # 計算當前一行有幾個 (Columns)
        # 邏輯：容器寬度 / (卡片寬 + 間距)
        viewport_w = self.viewport().width()
        item_w = CARD_SIZE[0]
        # 簡單估算列數
        cols = max(1, (viewport_w - MIN_SPACING) // (item_w + MIN_SPACING))
        
        new_idx = self.current_idx
        
        if direction == "D":   # Right
            new_idx += 1
        elif direction == "A": # Left
            new_idx -= 1
        elif direction == "W": # Up
            new_idx -= cols
        elif direction == "S": # Down
            new_idx += cols
            
        # 邊界檢查
        new_idx = max(0, min(new_idx, len(self.cards) - 1))
        
        if new_idx != self.current_idx:
            self.set_selection(new_idx)

class StatsMenuWidget(QFrame):
    """
    [修改] 可收合的資料夾統計選單
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.setFixedWidth(420) # 保持足夠寬度
        self.setFixedHeight(500)
        self.setStyleSheet("""
            QFrame { background-color: #252525; border: 1px solid #3e3e3e; border-radius: 6px; }
            QLabel { color: #ccc; border: none; background: transparent; }
        """)
        
        # 主佈局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)
        
        # 標題區
        title_container = QWidget()
        title_container.setStyleSheet("background-color: #2d2d2d; border-bottom: 1px solid #3e3e3e; border-top-left-radius: 6px; border-top-right-radius: 6px;")
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(15, 10, 15, 10)
        title_lbl = QLabel("Indexed Folders")
        title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        title_layout.addWidget(title_lbl)
        self.main_layout.addWidget(title_container)

        # 滾動區域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        # 底部統計區
        footer_container = QWidget()
        footer_container.setStyleSheet("background-color: #2d2d2d; border-top: 1px solid #3e3e3e; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        footer_layout = QHBoxLayout(footer_container)
        footer_layout.setContentsMargins(15, 8, 15, 8)
        self.total_label = QLabel("Total: 0 images")
        self.total_label.setStyleSheet("color: #60cdff; font-weight: bold;")
        footer_layout.addWidget(self.total_label, alignment=Qt.AlignmentFlag.AlignRight)
        self.main_layout.addWidget(footer_container)

    def update_stats(self, stats):
        # 清除舊內容
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        if not stats:
            self.content_layout.addWidget(QLabel("No statistics available.\nRun indexer.py first."))
            self.total_label.setText("Total: 0 images")
            return
            
        total_images = 0
        
        # 準備字型測量工具
        # 寬度估算: 420(總寬) - 80(數字標籤與邊距的保留空間) = 約 340px 可用於顯示路徑
        fm = QFontMetrics(QFont("Segoe UI", 13)) 
        max_text_width = 340 

        for folder, count in stats:
            total_images += count
            
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 5, 5, 5)
            row_layout.setSpacing(10)
            
            # --- 修改重點 ---
            # 直接顯示完整路徑，但如果真的太長(超出340px)，會自動在中間顯示 "..." (ElideMiddle)
            # 這樣既能滿足完整顯示的需求，又能防止視窗被撐爆
            display_text = fm.elidedText(folder, Qt.TextElideMode.ElideMiddle, max_text_width)
            
            lbl_name = QLabel(display_text)
            lbl_name.setToolTip(folder) # 滑鼠懸停依然顯示完整路徑(以防萬一被切斷)
            lbl_name.setStyleSheet("font-size: 13px; color: #dddddd;")
            
            lbl_count = QLabel(f"{count}")
            lbl_count.setStyleSheet("color: #aaaaaa; font-size: 13px; background-color: #333; padding: 2px 8px; border-radius: 10px;")
            lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            row_layout.addWidget(lbl_name, stretch=1)
            row_layout.addWidget(lbl_count)
            
            # Hover effect for row
            row.setStyleSheet(".QWidget:hover { background-color: #333333; border-radius: 4px; }")
            
            self.content_layout.addWidget(row)
            
        self.total_label.setText(f"Total: {total_images:,} images")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(WINDOW_TITLE); self.resize(1280, 900)
        self.engine = None; self.img_cache = {}; self.search_history = [] 
        self.current_selected_path = None
        
        self.load_history(); self.init_ui()
        
        # 鍵盤監聽 (處理空白鍵)
        QApplication.instance().installEventFilter(self)
        threading.Thread(target=self.load_engine, daemon=True).start()

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
        
        # Top Bar
        top_bar = QFrame(); top_bar.setFixedHeight(90); top_bar.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #333;")
        header_layout = QHBoxLayout(top_bar); header_layout.setContentsMargins(20, 0, 30, 0); header_layout.setSpacing(15)
        
        # 選單按鈕
        self.btn_menu = QPushButton("Menu"); self.btn_menu.setObjectName("MenuButton")
        self.btn_menu.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_menu.clicked.connect(self.toggle_menu)
        
        title_label = QLabel("AI Search"); title_label.setStyleSheet("color: #e0e0e0; font-size: 18px; font-weight: 600; letter-spacing: 0.5px;")
        
        header_layout.addWidget(self.btn_menu)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        
        # 搜尋區
        search_container = QWidget(); search_container.setFixedWidth(600)
        search_layout = QHBoxLayout(search_container); search_layout.setContentsMargins(0, 0, 0, 0); search_layout.setSpacing(10)
        self.input = QLineEdit(); self.input.setPlaceholderText("Type and press Enter..."); self.input.returnPressed.connect(self.start_search)
        
        self.chk_ocr = QCheckBox("OCR"); self.chk_ocr.setChecked(True)
        self.chk_ocr.setToolTip("Enable Text Search inside images")
        
        self.combo_limit = QComboBox(); self.combo_limit.addItems(["20", "50", "100", "All"]); self.combo_limit.setCurrentText("50")
        
        search_layout.addWidget(self.input, stretch=1)
        search_layout.addWidget(self.chk_ocr)
        search_layout.addWidget(self.combo_limit)
        # 移除 Search Button
        
        header_layout.addWidget(search_container)
        header_layout.addStretch(1) 
        
        self.status = QLabel("Initializing..."); self.status.setStyleSheet("color: #888888; font-size: 12px;"); header_layout.addWidget(self.status); layout.addWidget(top_bar)
        self.progress = QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        
        # 主內容區 (使用 Stacked Layout 以便浮動層)
        self.view_component = AdaptiveResultView()
        self.view_component.image_search_requested.connect(self.start_image_search)
        self.view_component.card_selected.connect(self.on_card_selected)
        self.view_component.rename_requested.connect(self.handle_rename)
        layout.addWidget(self.view_component)
        
        # 歷史紀錄彈窗
        self.history_list = QListWidget(self); self.history_list.hide(); self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(20); shadow.setColor(QColor(0, 0, 0, 100)); shadow.setOffset(0, 4); self.history_list.setGraphicsEffect(shadow)

        # 浮動選單 (Stats Menu)
        self.stats_menu = StatsMenuWidget(self)
        
        # 預覽圖層 (Mac Style Preview)
        self.preview_overlay = PreviewOverlay(self)

    def eventFilter(self, obj, event):
        # 處理鍵盤按下 (KeyPress)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            
            # [新增] 全域 Shift 偵測 (按下) -> 開啟紅框
            if key == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible():
                    self.preview_overlay.set_ocr_visible(True)
                return True # 不攔截其他行為，但標記已處理

            if not self.input.hasFocus():
                if key == Qt.Key.Key_W:
                    self.view_component.navigate("W"); return True
                elif key == Qt.Key.Key_S:
                    self.view_component.navigate("S"); return True
                elif key == Qt.Key.Key_A:
                    self.view_component.navigate("A"); return True
                elif key == Qt.Key.Key_D:
                    self.view_component.navigate("D"); return True
                elif key == Qt.Key.Key_Space:
                    self.toggle_preview(); return True
        
        # [新增] 處理鍵盤放開 (KeyRelease) -> 關閉紅框
        if event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible():
                    self.preview_overlay.set_ocr_visible(False)
                return True

        # 處理滑鼠點擊 (MouseButtonPress)
        if event.type() == QEvent.Type.MouseButtonPress:
            click_pos = event.globalPosition().toPoint()
            
            if self.history_list.isVisible():
                input_rect = QRect(self.input.mapToGlobal(QPoint(0, 0)), self.input.size())
                list_rect = QRect(self.history_list.mapToGlobal(QPoint(0, 0)), self.history_list.size())
                if not input_rect.contains(click_pos) and not list_rect.contains(click_pos): 
                    self.history_list.hide()
            
            if self.stats_menu.isVisible():
                btn_rect = QRect(self.btn_menu.mapToGlobal(QPoint(0, 0)), self.btn_menu.size())
                menu_rect = QRect(self.stats_menu.mapToGlobal(QPoint(0, 0)), self.stats_menu.size())
                if not btn_rect.contains(click_pos) and not menu_rect.contains(click_pos): 
                    self.stats_menu.hide()

            if obj == self.input: 
                self.show_history_popup()

        return super().eventFilter(obj, event)

    def toggle_preview(self):
        if self.preview_overlay.isVisible():
            self.preview_overlay.hide()
        else:
            # [修改] 改為從 view_component 獲取當前選取的完整資料 (包含 OCR)
            data = self.view_component.get_selected_data()
            if data:
                self.preview_overlay.show_image(data)

    def toggle_menu(self):
        if self.stats_menu.isVisible():
            self.stats_menu.hide()
        else:
            # 更新數據並顯示
            if self.engine:
                stats = self.engine.get_folder_stats()
                self.stats_menu.update_stats(stats)
            
            # 定位到按鈕下方
            btn_pos = self.btn_menu.mapTo(self, QPoint(0,0))
            # 調整 Y 位置稍微有點間距
            menu_x = btn_pos.x()
            menu_y = btn_pos.y() + self.btn_menu.height() + 8
            
            # 確保不會超出底部邊界 (簡單檢查)
            if menu_y + self.stats_menu.height() > self.height():
                 self.stats_menu.setFixedHeight(self.height() - menu_y - 20)
            
            self.stats_menu.move(menu_x, menu_y)
            self.stats_menu.show()
            self.stats_menu.raise_()


    def on_card_selected(self, path):
        self.current_selected_path = path

    def handle_rename(self, card_item):
        """處理重新命名邏輯"""
        old_name = card_item.filename
        old_path = card_item.path
        
        new_name, ok = QInputDialog.getText(self, "Rename File", "New filename:", text=old_name)
        
        if ok and new_name and new_name != old_name:
            success, result = self.engine.rename_file(old_path, new_name)
            if success:
                # 更新卡片 UI
                new_path = result
                card_item.update_info(new_path, new_name)
                # 更新當前選取路徑
                if self.current_selected_path == old_path:
                    self.current_selected_path = new_path
            else:
                QMessageBox.warning(self, "Error", f"Rename failed: {result}")

    def show_history_popup(self):
        if not self.search_history: self.history_list.hide(); return
        self.history_list.clear(); title_item = QListWidgetItem(); title_widget = QLabel(" Recent Searches"); title_widget.setStyleSheet("color: #888888; font-size: 12px; padding: 4px;"); title_item.setFlags(Qt.ItemFlag.NoItemFlags); title_item.setSizeHint(QSize(0, 30)); self.history_list.addItem(title_item); self.history_list.setItemWidget(title_item, title_widget)
        for text in self.search_history: item = QListWidgetItem(); item.setSizeHint(QSize(0, 44)); widget = HistoryItemWidget(text, search_callback=self.trigger_history_search, delete_callback=self.delete_history_item); self.history_list.addItem(item); self.history_list.setItemWidget(item, widget)
        input_pos = self.input.mapTo(self, QPoint(0, 0)); input_h = self.input.height(); input_w = self.input.width(); list_height = min(320, self.history_list.sizeHintForRow(0) * (len(self.search_history) + 1) + 20); self.history_list.setGeometry(input_pos.x(), input_pos.y() + input_h + 8, input_w, list_height); self.history_list.show(); self.history_list.raise_()
    
    def resizeEvent(self, event): 
        self.history_list.hide()
        self.stats_menu.hide()
        if self.preview_overlay.isVisible():
            self.preview_overlay.resize(self.size())
        super().resizeEvent(event)
        
    def delete_history_item(self, text):
        if text in self.search_history: self.search_history.remove(text); self.save_history_to_file(); self.show_history_popup()
    def trigger_history_search(self, text): self.input.setText(text); self.start_search()
    
    def load_engine(self):
        try: self.engine = ImageSearchEngine(); QApplication.processEvents(); self.status.setText("System Ready")
        except Exception as e: print(e)
        
    def start_search(self):
        q = self.input.text().strip(); 
        if not q or not self.engine: return
        self.add_to_history(q); self.history_list.hide(); self.progress.show(); self.progress.setRange(0, 0); self.status.setText("Searching..."); limit = self.combo_limit.currentText(); k = 100000 if limit == "All" else int(limit); self.view_component.clear(); 
        
        self.current_selected_path = None # 重置選取
        self.worker = SearchWorker(self.engine, q, k, self.img_cache, search_mode="text", use_ocr=self.chk_ocr.isChecked()); 
        self.worker.batch_ready.connect(self.view_component.add_items); self.worker.finished_search.connect(self.on_finished); self.worker.finished.connect(self.worker.deleteLater); self.worker.start()
    
    def start_image_search(self, image_path):
        if not self.engine: return
        self.history_list.hide(); self.progress.show(); self.progress.setRange(0, 0)
        self.status.setText("Searching by Image..."); 
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        
        limit = self.combo_limit.currentText(); k = 100000 if limit == "All" else int(limit); self.view_component.clear(); 
        self.current_selected_path = None
        self.worker = SearchWorker(self.engine, image_path, k, self.img_cache, search_mode="image"); 
        self.worker.batch_ready.connect(self.view_component.add_items); self.worker.finished_search.connect(self.on_finished); self.worker.finished.connect(self.worker.deleteLater); self.worker.start()

    def on_finished(self, elapsed, total): self.progress.hide(); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv); app.setStyleSheet(WIN11_STYLESHEET); w = MainWindow(); w.show(); sys.exit(app.exec())
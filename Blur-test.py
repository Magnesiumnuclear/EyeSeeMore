import sys
import os
import time
import sqlite3
import threading
import json
import queue
from PIL import Image
import torch
import numpy as np
import open_clip
from transformers import AutoTokenizer 

# --- CORRECTED IMPORTS ---
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox,
                             QGraphicsDropShadowEffect, QCheckBox, QInputDialog, QDialog,
                             QListView, QAbstractItemView, QStyle, QStyledItemDelegate) # Removed QFileSystemModel

from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QPoint, QRect, QSize, QEvent, 
                          QFileInfo, QTimer, QAbstractListModel, QModelIndex, 
                          QRunnable, QThreadPool, QObject, QByteArray, QBuffer, QIODevice)

from PyQt6.QtGui import (QPixmap, QImage, QCursor, QAction, QColor, QFont, 
                         QKeySequence, QShortcut, QFontMetrics, QPainter, 
                         QPen, QBrush, QPainterPath, QPolygon, QImageReader)

# --- Configuration ---
DB_FILE = "images.db"
THUMB_DB_FILE = "thumbnails.db" # Opt #3: L2 Cache DB
HISTORY_FILE = "search_history.json"
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'

# Visualization Constants
CARD_WIDTH = 240
CARD_HEIGHT = 280
THUMB_HEIGHT = 200 # Area for image
ICON_SIZE = QSize(CARD_WIDTH, CARD_HEIGHT)
WINDOW_TITLE = "Local AI Search (Virtual List Optimized)"

# --- Stylesheet ---
WIN11_STYLESHEET = """
QMainWindow { background-color: #1e1e1e; }
QWidget { color: #ffffff; font-family: "Segoe UI", "Microsoft JhengHei", sans-serif; font-size: 14px; }
QLineEdit { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-bottom: 1px solid #505050; border-radius: 4px; padding: 10px 12px; color: #ffffff; font-size: 15px; selection-background-color: #005fb8; }
QLineEdit:focus { border-bottom: 2px solid #60cdff; background-color: #323232; }
QComboBox { background-color: #2d2d2d; border: 1px solid #3e3e3e; border-radius: 4px; padding: 6px 10px; min-width: 80px; }
QComboBox:hover { background-color: #383838; }
QListView { background-color: #1e1e1e; border: none; outline: none; }
QProgressBar { border: none; background-color: #1e1e1e; height: 3px; }
QProgressBar::chunk { background-color: #60cdff; }
QListWidget { background-color: #2b2b2b; border: 1px solid #3b3b3b; border-radius: 8px; outline: 0; padding: 4px; }
QListWidget::item:hover { background-color: #383838; }
QListWidget::item:selected { background-color: #383838; border-left: 3px solid #60cdff; }
QMenu { background-color: rgba(30, 30, 30, 250); border: 1px solid #555555; padding: 5px; border-radius: 8px; }
QMenu::item { background-color: transparent; color: #eeeeee; padding: 8px 20px; margin: 2px 4px; border-radius: 4px; }
QMenu::item:selected { background-color: rgba(255, 255, 255, 30); color: #ffffff; }
"""

# ==========================================
#  Core Engine (Unchanged Logic)
# ==========================================
class ImageSearchEngine:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        print(f"[Engine] Initializing on {self.device.upper()}...")
        try:
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                MODEL_NAME, pretrained=PRETRAINED, device=self.device
            )
            self.model.eval()
            self.tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-large')
            if os.path.exists(DB_FILE): self.load_data_from_db()
            else: print(f"[Error] Database file not found: {DB_FILE}")
        except Exception as e: print(f"[Error] Engine init failed: {e}")

    def load_data_from_db(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT file_path, embedding, ocr_text, ocr_data FROM images")
            rows = cursor.fetchall()
            self.data_store = [] 
            embeddings_list = []
            for path, blob, ocr_text, ocr_data_json in rows:
                if not os.path.exists(path): continue 
                embeddings_list.append(np.frombuffer(blob, dtype=np.float32))
                ocr_boxes = []
                if ocr_data_json:
                    try: ocr_boxes = json.loads(ocr_data_json)
                    except: pass
                self.data_store.append({
                    "path": path, "filename": os.path.basename(path),
                    "ocr_text": (ocr_text or "").lower(), "ocr_data": ocr_boxes
                })
            if self.data_store:
                self.stored_embeddings = torch.from_numpy(np.stack(embeddings_list)).to(self.device)
                self.is_ready = True
                print(f"[Engine] Loaded {len(self.data_store)} records.")
        except Exception as e: print(f"[Error] DB query failed: {e}")
        finally: conn.close()

    def get_folder_stats(self):
        if not os.path.exists(DB_FILE): return []
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='folder_stats'")
            if cursor.fetchone():
                cursor.execute("SELECT folder_path, image_count FROM folder_stats ORDER BY folder_path ASC")
            else:
                cursor.execute("SELECT folder_path, COUNT(*) FROM images GROUP BY folder_path")
            stats = cursor.fetchall()
            conn.close()
            return stats
        except: return []

    def rename_file(self, old_path, new_name):
        folder = os.path.dirname(old_path)
        new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path): return False, "Target exists."
        try:
            os.rename(old_path, new_path)
            conn = sqlite3.connect(DB_FILE)
            conn.execute("UPDATE images SET file_path = ?, filename = ? WHERE file_path = ?", (new_path, new_name, old_path))
            conn.commit(); conn.close()
            for item in self.data_store:
                if item["path"] == old_path:
                    item["path"] = new_path; item["filename"] = new_name; break
            return True, new_path
        except Exception as e: return False, str(e)

    def search_hybrid(self, query, top_k=50, use_ocr=True):
        if not self.is_ready: return []
        try:
            with torch.no_grad():
                inputs = self.tokenizer(query, padding=True, truncation=True, return_tensors="pt").to(self.device)
                text_features = self.model.encode_text(inputs.input_ids)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                similarity = (text_features @ self.stored_embeddings.T).squeeze(0).cpu().numpy()
        except: similarity = np.zeros(len(self.data_store))

        results = []
        q_lower = query.lower()
        for idx, item in enumerate(self.data_store):
            score = float(similarity[idx])
            ocr_bonus = 0.5 if use_ocr and q_lower in item["ocr_text"] else 0.0
            name_bonus = 0.2 if q_lower in item["filename"].lower() else 0.0
            final = score + ocr_bonus + name_bonus
            if final > 0.15:
                results.append({
                    "score": final, "clip_score": score, "ocr_bonus": ocr_bonus, 
                    "name_bonus": name_bonus, "is_ocr_match": (ocr_bonus > 0),
                    "path": item["path"], "filename": item["filename"], "ocr_data": item["ocr_data"]
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_image(self, image_path, top_k=50):
        if not self.is_ready: return []
        try:
            image = Image.open(image_path).convert('RGB')
            processed = self.preprocess(image).unsqueeze(0).to(self.device)
            with torch.no_grad():
                feats = self.model.encode_image(processed)
                feats /= feats.norm(dim=-1, keepdim=True)
                similarity = (feats @ self.stored_embeddings.T).squeeze(0)
            values, indices = similarity.topk(min(top_k, len(self.data_store)))
            results = []
            for i in range(len(indices)):
                idx = indices[i].item()
                item = self.data_store[idx]
                score = values[i].item()
                results.append({
                    "score": score, "clip_score": score, "ocr_bonus": 0.0, "name_bonus": 0.0,
                    "is_ocr_match": False, "path": item["path"], "filename": item["filename"], "ocr_data": item["ocr_data"]
                })
            return results
        except: return []

class SearchWorker(QThread):
    results_ready = pyqtSignal(list, float, int)
    
    def __init__(self, engine, query, top_k, mode="text", use_ocr=True): 
        super().__init__()
        self.engine = engine; self.query = query; self.top_k = top_k
        self.mode = mode; self.use_ocr = use_ocr

    def run(self):
        t0 = time.time()
        if self.mode == "image": results = self.engine.search_image(self.query, self.top_k)
        else: results = self.engine.search_hybrid(self.query, self.top_k, self.use_ocr)
        self.results_ready.emit(results, time.time() - t0, len(results))

# ==========================================
#  Virtual List Components (Optimization Core)
# ==========================================

# Data Holder (Opt #6: Pre-calculation)
class ImageItem:
    def __init__(self, data):
        self.data = data
        self.path = data['path']
        # Pre-calculate display strings
        self.name_truncated = self.truncate_name(data['filename'])
        self.score_text = f"{data['score']:.4f}"
        self.is_ocr = data.get('is_ocr_match', False)
        # Store colors as objects to avoid recreating them in paint
        self.score_color = QColor("#60cdff") if data['score'] > 0.3 else QColor("#999999")
        
    def truncate_name(self, name):
        return name[:20] + "..." if len(name) > 22 else name

# Async Loader Signal
class LoaderSignals(QObject):
    loaded = pyqtSignal(str, QPixmap)

# Background Loader (Opt #1 & #2)
class ThumbnailLoader(QRunnable):
    def __init__(self, path, target_size, cache_db_path, token):
        super().__init__()
        self.path = path
        self.target_size = target_size
        self.db_path = cache_db_path
        self.token = token # For cancellation checking
        self.signals = LoaderSignals()

    def run(self):
        # Opt #3: Check L2 Disk Cache first
        pixmap = self.load_from_l2_cache()
        if pixmap:
            self.signals.loaded.emit(self.path, pixmap)
            return

        # Load from disk if not in L2
        if not os.path.exists(self.path): return

        try:
            reader = QImageReader(self.path)
            
            # Opt #1: Pre-scaling (Modified to remove ImageOption check)
            orig_size = reader.size()
            if orig_size.isValid():
                scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
                reader.setScaledSize(scaled_size)
            
            reader.setAutoTransform(True)
            image = reader.read()
            
            if not image.isNull():
                # Safety fallback: If the reader ignored setScaledSize (some formats don't support it),
                # manually scale the image now to ensure we don't use too much RAM.
                if image.width() > self.target_size.width() * 1.5:
                     image = image.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)

                # Opt #1: Convert to Premultiplied ARGB for fast rendering
                if image.format() != QImage.Format.Format_ARGB32_Premultiplied:
                    image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                
                final_pixmap = QPixmap.fromImage(image)
                self.save_to_l2_cache(final_pixmap) # Save to L2
                self.signals.loaded.emit(self.path, final_pixmap)
        except Exception as e:
            print(f"Load error: {e}")

    def load_from_l2_cache(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT blob_data FROM thumbnails WHERE file_path=?", (self.path,))
            row = cursor.fetchone()
            conn.close()
            if row:
                img = QImage.fromData(row[0])
                if not img.isNull():
                    return QPixmap.fromImage(img)
        except: pass
        return None

    def save_to_l2_cache(self, pixmap):
        try:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            # Save as optimized JPG for cache
            pixmap.save(buf, "JPG", 85) 
            blob = ba.data()
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO thumbnails (file_path, blob_data) VALUES (?, ?)", 
                           (self.path, blob))
            conn.commit()
            conn.close()
        except: pass

# Virtual Model
class VirtualImageModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        
        # Opt #3: L1 RAM Cache (Limit ~200 items)
        self.l1_cache = {} 
        self.max_l1_size = 200
        self.l1_keys = [] # To track LRU
        
        # Opt #3: Init L2 Cache DB
        self.init_l2_db()

        # Thread Pool
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        
        # Opt #5: Batch Update Queue & Timer
        self.loaded_queue = queue.Queue()
        self.batch_timer = QTimer()
        self.batch_timer.setInterval(30) # 30ms throttling
        self.batch_timer.timeout.connect(self.process_loaded_batch)
        self.batch_timer.start()
        
        self.loading_set = set()
        self.current_token = 0 # To invalidate old tasks

    def init_l2_db(self):
        conn = sqlite3.connect(THUMB_DB_FILE)
        conn.execute("CREATE TABLE IF NOT EXISTS thumbnails (file_path TEXT PRIMARY KEY, blob_data BLOB)")
        conn.close()

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.items)):
            return None
        
        item = self.items[index.row()]
        
        if role == Qt.ItemDataRole.DisplayRole:
            return item # Return full object for Delegate
        
        return None

    def get_pixmap(self, path):
        # Check L1 Cache
        if path in self.l1_cache:
            # Move to end (LRU)
            self.l1_keys.remove(path)
            self.l1_keys.append(path)
            return self.l1_cache[path]
        
        # Trigger load if needed
        if path not in self.loading_set:
            self.loading_set.add(path)
            loader = ThumbnailLoader(path, QSize(CARD_WIDTH, THUMB_HEIGHT), THUMB_DB_FILE, self.current_token)
            loader.signals.loaded.connect(self.on_image_loaded)
            self.pool.start(loader)
        
        return None # Return None, Delegate draws placeholder

    def on_image_loaded(self, path, pixmap):
        self.loaded_queue.put((path, pixmap))

    def process_loaded_batch(self):
        if self.loaded_queue.empty(): return
        
        while not self.loaded_queue.empty():
            path, pixmap = self.loaded_queue.get()
            if path in self.loading_set:
                self.loading_set.remove(path)
            
            # Update L1 Cache
            if len(self.l1_cache) >= self.max_l1_size:
                oldest = self.l1_keys.pop(0)
                del self.l1_cache[oldest]
            
            self.l1_cache[path] = pixmap
            self.l1_keys.append(path)
        
        # Force refresh
        top = self.index(0, 0)
        bottom = self.index(len(self.items)-1, 0)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])

    def set_results(self, raw_results):
        self.beginResetModel()
        self.items = [ImageItem(r) for r in raw_results]
        self.loading_set.clear()
        self.l1_cache.clear()
        self.l1_keys.clear()
        self.current_token += 1
        self.endResetModel()

    def update_item_path(self, old_path, new_path, new_name):
        for i, item in enumerate(self.items):
            if item.path == old_path:
                item.path = new_path
                item.data['path'] = new_path
                item.data['filename'] = new_name
                item.name_truncated = item.truncate_name(new_name)
                # Invalidate cache
                if old_path in self.l1_cache: del self.l1_cache[old_path]
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])
                break

# Optimized Delegate
class ResultDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg_color = QColor("#2b2b2b")
        self.hover_color = QColor("#323232")
        self.selected_border = QColor("#60cdff")
        self.ocr_border = QColor("#4caf50")
        self.text_color = QColor("#ffffff")
        
        self.font_name = QFont("Segoe UI", 10, QFont.Weight.Medium)
        self.font_score = QFont("Consolas", 9)
        self.font_ocr = QFont("Segoe UI", 8, QFont.Weight.Bold)

    def sizeHint(self, option, index):
        return ICON_SIZE

    def paint(self, painter, option, index):
        if not index.isValid(): return
        
        # Retrieve pre-calculated object
        item = index.data(Qt.ItemDataRole.DisplayRole)
        if not item: return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = option.rect
        
        # 1. Background & Selection
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_hover = option.state & QStyle.StateFlag.State_MouseOver
        
        bg_brush = self.hover_color if is_hover else self.bg_color
        border_pen = QPen(Qt.PenStyle.NoPen)
        
        if is_selected:
            border_pen = QPen(self.selected_border, 2)
        elif item.is_ocr:
            border_pen = QPen(self.ocr_border, 1)
        else:
            border_pen = QPen(QColor("#3b3b3b"), 1)
            
        # Draw Card Body
        card_rect = rect.adjusted(4, 4, -4, -4)
        painter.setBrush(bg_brush)
        painter.setPen(border_pen)
        painter.drawRoundedRect(card_rect, 8, 8)
        
        # 2. Image Area
        img_rect = QRect(card_rect.left() + 10, card_rect.top() + 10, 
                         card_rect.width() - 20, THUMB_HEIGHT)
        
        # Fetch Pixmap from Model's L1 Cache
        model = index.model()
        pixmap = model.get_pixmap(item.path)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1e1e1e"))
        painter.drawRoundedRect(img_rect, 4, 4)
        
        if pixmap and not pixmap.isNull():
            painter.setClipRect(img_rect)
            x_off = (pixmap.width() - img_rect.width()) // 2
            y_off = (pixmap.height() - img_rect.height()) // 2
            painter.drawPixmap(img_rect.left(), img_rect.top(), pixmap, 
                               x_off, y_off, img_rect.width(), img_rect.height())
            painter.setClipping(False)
        else:
            painter.setPen(QColor("#555"))
            painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "Loading...")

        # 3. Text Info
        text_y = img_rect.bottom() + 20
        name_rect = QRect(card_rect.left(), text_y, card_rect.width(), 20)
        
        painter.setFont(self.font_name)
        painter.setPen(self.text_color)
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, item.name_truncated)
        
        # 4. Score & Tags
        meta_y = name_rect.bottom() + 2
        meta_rect = QRect(card_rect.left(), meta_y, card_rect.width(), 20)
        
        # Calculate positions
        total_w = QFontMetrics(self.font_score).horizontalAdvance(item.score_text)
        if item.is_ocr: total_w += 35
        
        start_x = meta_rect.center().x() - (total_w // 2)
        
        painter.setFont(self.font_score)
        painter.setPen(item.score_color)
        painter.drawText(start_x, meta_y + 14, item.score_text)
        
        if item.is_ocr:
            tag_x = start_x + QFontMetrics(self.font_score).horizontalAdvance(item.score_text) + 5
            tag_rect = QRect(tag_x, meta_y + 3, 30, 14)
            painter.setBrush(QColor("#4caf50"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(tag_rect, 2, 2)
            
            painter.setFont(self.font_ocr)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, "TEXT")

        painter.restore()

# ==========================================
#  UI Components
# ==========================================

class OCRLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ocr_data = []; self.show_ocr_boxes = False; self.original_size = QSize(0, 0)
    def set_ocr_data(self, data, orig_w, orig_h):
        self.ocr_data = data; self.original_size = QSize(orig_w, orig_h)
    def set_draw_boxes(self, show):
        self.show_ocr_boxes = show; self.update()
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.show_ocr_boxes and self.ocr_data and self.pixmap():
            painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(255, 0, 0, 200)); pen.setWidth(2); painter.setPen(pen)
            dw, dh = self.pixmap().width(), self.pixmap().height()
            ox, oy = (self.width()-dw)/2, (self.height()-dh)/2
            sx, sy = dw/self.original_size.width(), dh/self.original_size.height()
            for item in self.ocr_data:
                box = item.get("box")
                if box:
                    pts = [QPoint(int(pt[0]*sx+ox), int(pt[1]*sy+oy)) for pt in box]
                    painter.drawPolygon(QPolygon(pts))

class PreviewOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide(); self.setStyleSheet("background-color: rgba(0, 0, 0, 220);")
        self.layout = QVBoxLayout(self); self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label = OCRLabel(); self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(40); shadow.setColor(QColor(0,0,0, 150))
        self.image_label.setGraphicsEffect(shadow)
        self.layout.addWidget(self.image_label)
        self.filename_label = QLabel(); self.filename_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; background: transparent; margin-top: 10px;")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.filename_label)
        self.layout.addWidget(QLabel("Hold SHIFT for OCR", styleSheet="color:#888; margin-top:5px;"), alignment=Qt.AlignmentFlag.AlignCenter)

    def show_image(self, item_data):
        path = item_data['path']
        if not os.path.exists(path): return
        img = QImage(path)
        if img.isNull(): return
        screen = self.parent().size()
        pix = QPixmap.fromImage(img).scaled(screen * 0.85, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(pix)
        self.image_label.set_ocr_data(item_data['ocr_data'], img.width(), img.height())
        self.filename_label.setText(item_data['filename'])
        self.resize(self.parent().size()); self.show(); self.raise_(); self.setFocus()
    
    def set_ocr_visible(self, visible): self.image_label.set_draw_boxes(visible)
    def keyPressEvent(self, e): 
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape): self.hide()
    def mousePressEvent(self, e): self.hide()

class StatsMenuWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide(); self.setFixedSize(420, 500)
        self.setStyleSheet("background-color: #252525; border: 1px solid #3e3e3e; border-radius: 6px;")
        self.layout = QVBoxLayout(self)
        self.content = QLabel("Loading stats...", alignment=Qt.AlignmentFlag.AlignTop)
        self.content.setStyleSheet("color: #ccc; padding: 10px;")
        self.layout.addWidget(self.content)

    def update_stats(self, stats):
        txt = "<b>Indexed Folders</b><br><hr>"
        total = 0
        for f, c in stats:
            txt += f"{f} <span style='color:#60cdff'>({c})</span><br>"
            total += c
        txt += f"<hr>Total: {total} images"
        self.content.setText(txt)

class HistoryItemWidget(QWidget):
    def __init__(self, text, cb, del_cb):
        super().__init__()
        l = QHBoxLayout(self); l.setContentsMargins(10,0,5,0)
        lbl = QLabel(text); lbl.setStyleSheet("color:#eee;"); lbl.mousePressEvent = lambda e: cb(text)
        btn = QPushButton("x"); btn.setFixedSize(28,28); btn.clicked.connect(lambda: del_cb(text))
        btn.setStyleSheet("background:transparent; color:#ccc; border:none;")
        l.addWidget(lbl, 1); l.addWidget(btn)

# ==========================================
#  Main Window
# ==========================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(WINDOW_TITLE); self.resize(1280, 900)
        self.engine = None; self.search_history = []
        self.load_history(); self.init_ui()
        QApplication.instance().installEventFilter(self)
        threading.Thread(target=self.load_engine, daemon=True).start()

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try: 
                with open(HISTORY_FILE, 'r') as f: self.search_history = json.load(f)
            except: pass

    def save_history(self):
        with open(HISTORY_FILE, 'w') as f: json.dump(self.search_history, f)

    def init_ui(self):
        central = QWidget(); self.setCentralWidget(central); layout = QVBoxLayout(central); layout.setSpacing(0); layout.setContentsMargins(0,0,0,0)
        
        # Header
        top = QFrame(); top.setFixedHeight(90); top.setStyleSheet("background:#1e1e1e; border-bottom:1px solid #333;")
        h_layout = QHBoxLayout(top); h_layout.setContentsMargins(20,0,30,0)
        
        self.btn_menu = QPushButton("Menu"); self.btn_menu.clicked.connect(self.toggle_menu)
        self.btn_menu.setStyleSheet("background:#333; color:white; border:1px solid #555; padding:6px 12px; border-radius:4px;")
        
        search_box = QWidget(); search_box.setFixedWidth(600)
        s_layout = QHBoxLayout(search_box); s_layout.setContentsMargins(0,0,0,0)
        self.input = QLineEdit(); self.input.setPlaceholderText("Search..."); self.input.returnPressed.connect(self.start_search)
        self.chk_ocr = QCheckBox("OCR"); self.chk_ocr.setChecked(True)
        self.combo_lim = QComboBox(); self.combo_lim.addItems(["50", "100", "500", "All"])
        
        s_layout.addWidget(self.input, 1); s_layout.addWidget(self.chk_ocr); s_layout.addWidget(self.combo_lim)
        
        h_layout.addWidget(self.btn_menu); h_layout.addWidget(QLabel("  AI Search", styleSheet="color:white; font-size:16px; font-weight:bold;"))
        h_layout.addStretch(); h_layout.addWidget(search_box); h_layout.addStretch()
        self.status = QLabel("Init..."); self.status.setStyleSheet("color:#888;"); h_layout.addWidget(self.status)
        layout.addWidget(top)
        
        self.progress = QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        
        # --- Virtual ListView ---
        self.list_view = QListView()
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setUniformItemSizes(True) 
        self.list_view.setGridSize(ICON_SIZE) 
        self.list_view.setSpacing(10)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        
        self.model = VirtualImageModel()
        self.delegate = ResultDelegate()
        
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        
        # Connections
        self.list_view.doubleClicked.connect(self.open_file)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)
        
        layout.addWidget(self.list_view)
        
        # Overlays
        self.history_list = QListWidget(self); self.history_list.hide()
        shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(20); self.history_list.setGraphicsEffect(shadow)
        self.stats_menu = StatsMenuWidget(self)
        self.preview_overlay = PreviewOverlay(self)

    def load_engine(self):
        try: self.engine = ImageSearchEngine(); self.status.setText("Ready")
        except: pass

    def start_search(self):
        if not self.engine: return
        q = self.input.text().strip(); 
        if not q: return
        
        # History
        if q in self.search_history: self.search_history.remove(q)
        self.search_history.insert(0, q); self.search_history=self.search_history[:10]; self.save_history()
        
        self.history_list.hide(); self.progress.show(); self.progress.setRange(0,0)
        self.status.setText("Searching...")
        
        lim_txt = self.combo_lim.currentText()
        k = 100000 if lim_txt == "All" else int(lim_txt)
        
        self.worker = SearchWorker(self.engine, q, k, "text", self.chk_ocr.isChecked())
        self.worker.results_ready.connect(self.on_results)
        self.worker.start()

    def on_results(self, results, time_taken, count):
        self.progress.hide()
        self.status.setText(f"Found {count} in {time_taken:.2f}s")
        self.model.set_results(results)
        self.list_view.scrollToTop()

    def open_file(self, index):
        item = self.model.items[index.row()]
        try: os.startfile(item.path)
        except: pass

    def show_context_menu(self, pos):
        index = self.list_view.indexAt(pos)
        if not index.isValid(): return
        
        item = self.model.items[index.row()]
        menu = QMenu(self)
        
        act_rename = QAction("Rename", self)
        act_rename.triggered.connect(lambda: self.rename_item(item))
        menu.addAction(act_rename)
        
        act_copy_path = QAction("Copy Path", self)
        act_copy_path.triggered.connect(lambda: QApplication.clipboard().setText(item.path))
        menu.addAction(act_copy_path)
        
        act_search_sim = QAction("Search Similar", self)
        act_search_sim.triggered.connect(lambda: self.search_similar(item.path))
        menu.addAction(act_search_sim)

        menu.exec(self.list_view.mapToGlobal(pos))

    def rename_item(self, item):
        new_name, ok = QInputDialog.getText(self, "Rename", "New Name:", text=item.data['filename'])
        if ok and new_name:
            success, res = self.engine.rename_file(item.path, new_name)
            if success:
                self.model.update_item_path(item.path, res, new_name)
            else:
                QMessageBox.warning(self, "Error", res)

    def search_similar(self, path):
        self.input.setText(f"[IMG] {os.path.basename(path)}")
        self.progress.show(); self.progress.setRange(0,0)
        self.status.setText("Searching Image...")
        
        lim_txt = self.combo_lim.currentText()
        k = 100000 if lim_txt == "All" else int(lim_txt)
        
        self.worker = SearchWorker(self.engine, path, k, "image")
        self.worker.results_ready.connect(self.on_results)
        self.worker.start()

    # --- Event Filters & Interactions ---
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Space:
                self.toggle_preview(); return True
            if event.key() == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible(): self.preview_overlay.set_ocr_visible(True)
        
        if event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Shift:
            if self.preview_overlay.isVisible(): self.preview_overlay.set_ocr_visible(False)
            
        if event.type() == QEvent.Type.MouseButtonPress:
            if obj == self.input: self.show_history()
            else: self.history_list.hide(); self.stats_menu.hide()
            
        return super().eventFilter(obj, event)

    def toggle_preview(self):
        if self.preview_overlay.isVisible(): self.preview_overlay.hide()
        else:
            idx = self.list_view.currentIndex()
            if idx.isValid():
                item = self.model.items[idx.row()]
                self.preview_overlay.show_image(item.data)

    def toggle_menu(self):
        if self.stats_menu.isVisible(): self.stats_menu.hide()
        else:
            if self.engine: self.stats_menu.update_stats(self.engine.get_folder_stats())
            pos = self.btn_menu.mapToGlobal(QPoint(0, self.btn_menu.height()))
            self.stats_menu.move(self.mapFromGlobal(pos))
            self.stats_menu.show()

    def show_history(self):
        if not self.search_history: return
        self.history_list.clear()
        for txt in self.search_history:
            item = QListWidgetItem(self.history_list)
            item.setSizeHint(QSize(0,40))
            w = HistoryItemWidget(txt, lambda t: (self.input.setText(t), self.start_search()), 
                                  lambda t: self.search_history.remove(t) or self.show_history())
            self.history_list.setItemWidget(item, w)
        p = self.input.mapTo(self, QPoint(0, self.input.height()))
        self.history_list.setGeometry(p.x(), p.y()+5, self.input.width(), 300)
        self.history_list.show(); self.history_list.raise_()

if __name__ == "__main__":
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QImageReader.setAllocationLimit(512)
    app = QApplication(sys.argv)
    app.setStyleSheet(WIN11_STYLESHEET)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
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
from datetime import datetime
from collections import OrderedDict

# [New] 引入 OpenCV (給 Grad-CAM 用)
import cv2

# [New] 引入設定管理器
from config_manager import ConfigManager 

# [修正] 確保所有 PyQt6 模組都已引入
from PyQt6.QtGui import QActionGroup
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox,
                             QGraphicsDropShadowEffect, QCheckBox, QInputDialog, QDialog,
                             QStyledItemDelegate, QStyle, QFileIconProvider, QAbstractItemView, QListView)
from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QPoint, QRect, QRectF, QSize, QEvent, 
                          QFileInfo, QTimer, QAbstractListModel, QRunnable, QThreadPool, QObject, QModelIndex)
from PyQt6.QtGui import (QPixmap, QImage, QCursor, QAction, QColor, QFont, QKeySequence, 
                         QShortcut, QFontMetrics, QPainter, QBrush, QPen, QIcon, QPainterPath, QPolygon, QImageReader)

THUMBNAIL_SIZE = (220, 180)
CARD_SIZE = (240, 290) 
MIN_SPACING = 24       
WINDOW_TITLE = "Local AI Search (High Performance)"

# ==========================================
#  樣式表
# ==========================================
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

# ==========================================
#  [NEW] 高效能資料模型與載入器
# ==========================================

class ImageItem:
    """單張圖片的資料結構，統一管理所有屬性"""
    def __init__(self, path, filename, score, ocr_text="", ocr_data=None, mtime=0):
        self.path = path
        self.filename = filename
        self.score = score
        self.ocr_text = ocr_text
        self.ocr_data = ocr_data if ocr_data else []
        self.mtime = mtime
        self.is_ocr_match = False 

class WorkerSignals(QObject):
    result = pyqtSignal(str, QPixmap) 

class ThumbnailLoader(QRunnable):
    """背景圖片讀取器 (智慧縮放版)"""
    def __init__(self, file_path, target_size):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.signals = WorkerSignals()

    def run(self):
        try:
            reader = QImageReader(self.file_path)
            orig_size = reader.size()
            if not orig_size.isValid():
                self.signals.result.emit(self.file_path, QPixmap())
                return

            # 智慧縮放
            scaled_size = orig_size.scaled(
                self.target_size, 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding
            )
            
            reader.setScaledSize(scaled_size)
            reader.setAutoTransform(True)

            image = reader.read()
            if not image.isNull():
                self.signals.result.emit(self.file_path, QPixmap.fromImage(image))
            else:
                self.signals.result.emit(self.file_path, QPixmap())
                
        except Exception:
            self.signals.result.emit(self.file_path, QPixmap())

class SearchResultsModel(QAbstractListModel):
    """核心 Model：管理搜尋結果列表與圖片快取"""
    def __init__(self, item_size):
        super().__init__()
        self.items = []
        self.item_size = item_size 
        
        self._thumbnail_cache = OrderedDict()
        self.CACHE_SIZE = 200 
        
        self._loading_set = set() 
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4) 

    # [新增] 用於切換檢視模式時更新尺寸
    def update_target_size(self, new_size):
        self.item_size = new_size
        self._thumbnail_cache.clear() # 清除舊尺寸的快取，重新載入清晰的圖
        self._loading_set.clear()

    # ... (其餘 set_search_results, rowCount, data, request_thumbnail, on_thumbnail_loaded 保持不變) ...
    # 這裡為了節省版面，請保留原本的程式碼，只要補上 update_target_size 即可
    def set_search_results(self, results_dict_list):
        self.beginResetModel()
        self.items = []
        self._thumbnail_cache.clear()
        self._loading_set.clear()
        
        for res in results_dict_list:
            item = ImageItem(
                path=res['path'],
                filename=res['filename'],
                score=res['score'],
                ocr_text=res.get('ocr_text', ""),
                ocr_data=res.get('ocr_data', []),
                mtime=res.get('mtime', 0)
            )
            if res.get('is_ocr_match', False):
                item.is_ocr_match = True
                
            self.items.append(item)
            
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.items)):
            return None

        item = self.items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
            
        elif role == Qt.ItemDataRole.UserRole:
            return item 

        elif role == Qt.ItemDataRole.DecorationRole:
            if item.path in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(item.path)
                return self._thumbnail_cache[item.path]
            
            if item.path not in self._loading_set:
                self.request_thumbnail(item.path)
            
            return None

        return None

    def request_thumbnail(self, file_path):
        self._loading_set.add(file_path)
        loader = ThumbnailLoader(file_path, self.item_size)
        loader.signals.result.connect(self.on_thumbnail_loaded)
        self.thread_pool.start(loader)

    def on_thumbnail_loaded(self, file_path, pixmap):
        if file_path in self._loading_set:
            self._loading_set.remove(file_path)

        if not pixmap.isNull():
            self._thumbnail_cache[file_path] = pixmap
            if len(self._thumbnail_cache) > self.CACHE_SIZE:
                self._thumbnail_cache.popitem(last=False)

            for row, item in enumerate(self.items):
                if item.path == file_path:
                    idx = self.index(row, 0)
                    self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])
                    break

class ImageDelegate(QStyledItemDelegate):
    """負責繪製列表中的每一個項目 (支援動態調整大小)"""
    def __init__(self, card_size, thumb_height, parent=None):
        super().__init__(parent)
        self.padding = 10
        self.radius = 8
        self.font_name = QFont("Segoe UI", 10, QFont.Weight.Medium)
        self.font_score = QFont("Consolas", 9)
        self.font_tag = QFont("Segoe UI", 8, QFont.Weight.Bold)
        
        self.card_size = card_size
        self.thumb_height = thumb_height
        
        # 取得系統預設圖示
        provider = QFileIconProvider()
        # 使用一個不存在的 .jpg 檔名來獲取系統對 jpg 的預設圖示
        self.placeholder_icon = provider.icon(QFileInfo("template.jpg"))

    # [新增] 更新尺寸的方法
    def set_view_params(self, card_size, thumb_height):
        self.card_size = card_size
        self.thumb_height = thumb_height

    def sizeHint(self, option, index):
        return self.card_size

    def paint(self, painter: QPainter, option, index):
        if not index.isValid(): return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        item = index.data(Qt.ItemDataRole.UserRole)
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)

        if not item: 
            painter.restore()
            return

        rect = option.rect
        card_rect = rect.adjusted(4, 4, -4, -4)

        # 狀態判斷
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_hover = option.state & QStyle.StateFlag.State_MouseOver
        
        bg_color = QColor("#2b2b2b")
        border_color = QColor("#3b3b3b")
        border_width = 1

        if is_selected:
            border_color = QColor("#60cdff")
            border_width = 2
        elif item.is_ocr_match:
            border_color = QColor("#4caf50")
            border_width = 1
        elif is_hover:
            bg_color = QColor("#323232")
            border_color = QColor("#7ce0ff")

        # 1. 繪製背景
        path = QPainterPath()
        path.addRoundedRect(QRectF(card_rect), self.radius, self.radius)
        
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, border_width))
        painter.drawPath(path)

        # --- 版面計算 ---
        bottom_margin = self.padding
        score_height = 20
        score_y = card_rect.bottom() - bottom_margin - score_height
        score_rect = QRect(
            card_rect.left() + self.padding,
            score_y,
            100, score_height
        )

        name_height = 20
        name_y = score_y - 2 - name_height
        text_rect = QRect(
            card_rect.left() + self.padding,
            name_y,
            card_rect.width() - 2 * self.padding,
            name_height
        )

        img_rect_height = self.thumb_height
        img_rect = QRect(
            card_rect.left() + self.padding,
            card_rect.top() + self.padding,
            card_rect.width() - 2 * self.padding,
            img_rect_height
        )
        
        painter.setClipPath(path) 
        
        if pixmap and not pixmap.isNull():
            # 有縮圖時：繪製縮圖
            scaled_pixmap = pixmap.scaled(
                img_rect.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            x_off = (img_rect.width() - scaled_pixmap.width()) / 2
            y_off = (img_rect.height() - scaled_pixmap.height()) / 2
            painter.drawPixmap(
                img_rect.left() + int(x_off), 
                img_rect.top() + int(y_off), 
                scaled_pixmap
            )
        else:
            # ==========================================
            # [修改] 動態計算預設圖示大小
            # ==========================================
            
            # 1. 計算可用空間的最小邊 (寬或高)
            min_dim = min(img_rect.width(), img_rect.height())
            
            # 2. 設定圖示大小為可用空間的 45% (看起來比較像 Windows 檔案總管)
            # 你可以調整 0.80 這個數值 (0.3 ~ 0.6 效果都不錯)
            icon_size = int(min_dim * 0.80)
            
            # 3. 設定最小限制，避免圖示小到看不見
            icon_size = max(48, icon_size)
            
            # 4. 居中計算
            icon_rect = QRect(
                img_rect.center().x() - icon_size // 2,
                img_rect.center().y() - icon_size // 2,
                icon_size, icon_size
            )
            
            painter.setOpacity(0.2) # 稍微透明一點，讓它看起來像背景浮水印
            self.placeholder_icon.paint(painter, icon_rect)
            painter.setOpacity(1.0)

        painter.setClipping(False)

        # 3. 繪製文字
        painter.setFont(self.font_name)
        painter.setPen(QColor("#ffffff"))
        fm = QFontMetrics(self.font_name)
        elided_name = fm.elidedText(item.filename, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

        # 4. 繪製分數
        painter.setFont(self.font_score)
        score_val = float(item.score)
        
        # 只有分數大於 0 才顯示高亮顏色 (0.0 通常代表剛載入還沒搜尋)
        if score_val > 0.0001:
            if score_val > 0.3:
                painter.setPen(QColor("#60cdff"))
            else:
                painter.setPen(QColor("#999999"))
            painter.drawText(score_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{score_val:.4f}")
        else:
            # 如果分數是 0 (例如剛啟動顯示全部圖片時)，顯示日期可能比較實用，或者留白
            # 這裡示範顯示日期
            pass

        # 5. OCR 標籤
        if item.is_ocr_match:
            tag_text = "TEXT"
            tag_width = 36
            tag_rect = QRect(
                card_rect.right() - self.padding - tag_width,
                score_rect.top() + 2,
                tag_width, 16
            )
            painter.setBrush(QBrush(QColor("#4caf50")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(tag_rect, 3, 3)
            painter.setFont(self.font_tag)
            painter.setPen(QColor("white"))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)

        painter.restore()
# ==========================================
#  引擎核心
# ==========================================
class ImageSearchEngine:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_ready = False
        self.model = None
        self.preprocess = None
        self.tokenizer = None
        
        # [修正] 預先定義 stored_embeddings
        self.stored_embeddings = None 
        self.data_store = []

        # 1. 初始化資料庫
        print(f"[Engine] Initializing Database...")
        if os.path.exists(self.config.db_path):
            self.load_data_from_db()
        else:
            print(f"[Error] Database file not found: {self.config.db_path}")

    def load_ai_models(self):
        """第二階段：載入重量級 AI 模型 (耗時操作)"""
        try:
            model_name = self.config.get("model_name")
            pretrained = self.config.get("pretrained")

            print(f"[Engine] Loading OpenCLIP model: {model_name}...")
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=pretrained, device=self.device
            )
            self.model.eval()
            self.tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-large')
            
            # 模型載入完畢，標記為 Ready
            self.is_ready = True
            print(f"[Engine] AI Models Loaded. System is fully ready.")
            
        except Exception as e:
            print(f"[Error] AI Model loading failed: {e}")

    def get_all_images_sorted(self):
        """
        [高效能] 取得資料庫中所有圖片，並依時間 (新->舊) 排序。
        用於冷啟動時的瀑布流顯示。
        """
        if not hasattr(self, 'data_store') or not self.data_store:
            return []
        
        print(f"[Engine] Sorting {len(self.data_store)} images by date...")
        
        # 1. 使用 Python 內建 Timsort 進行快速排序 (mtime 大的排前面)
        sorted_data = sorted(self.data_store, key=lambda x: x["mtime"], reverse=True)
        
        # 2. 轉換為 UI 需要的格式
        results = []
        for item in sorted_data:
            results.append({
                "score": 0.0, # 初始顯示沒有相似度分數
                "clip_score": 0.0,
                "ocr_bonus": 0.0,
                "name_bonus": 0.0,
                "is_ocr_match": False,
                "path": item["path"],
                "filename": item["filename"],
                "ocr_data": item.get("ocr_data", []),
                "mtime": item.get("mtime", 0)
            })
            
        return results

    def load_data_from_db(self):
        print(f"[Engine] Connecting to database: {self.config.db_path}...")
        conn = sqlite3.connect(self.config.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT file_path, embedding, ocr_text, ocr_data, mtime FROM images")
            rows = cursor.fetchall()
            
            self.data_store = [] 
            embeddings_list = []
            
            for path, blob, ocr_text, ocr_data_json, mtime in rows:
                if not os.path.exists(path): continue 
                
                # 這裡只需存 embedding array，不用轉 tensor (省記憶體/時間)
                emb_array = np.frombuffer(blob, dtype=np.float32)
                embeddings_list.append(emb_array)
                
                text_content = ocr_text if ocr_text else ""
                
                ocr_boxes = []
                if ocr_data_json:
                    try: ocr_boxes = json.loads(ocr_data_json)
                    except: pass

                self.data_store.append({
                    "path": path,
                    "filename": os.path.basename(path),
                    "ocr_text": text_content.lower(),
                    "ocr_data": ocr_boxes,
                    "mtime": mtime
                })
            
            if self.data_store and embeddings_list:
                # 預先轉好 tensor 以備搜尋用
                emb_matrix = np.stack(embeddings_list)
                self.stored_embeddings = torch.from_numpy(emb_matrix).to(self.device)
                print(f"[Engine] Loaded {len(self.data_store)} records from DB.")
            else:
                print("[Engine] Database is empty or no valid files found.")
                # [修正 2] 確保即使沒資料，變數也要存在，避免後續 NoneType 錯誤
                self.stored_embeddings = None
                
        except sqlite3.Error as e:
            print(f"[Error] Database query failed: {e}")
        finally:
            if conn: conn.close()

    def get_folder_stats(self):
        if not os.path.exists(self.config.db_path): return []
        try:
            conn = sqlite3.connect(self.config.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='folder_stats'")
            if cursor.fetchone():
                cursor.execute("SELECT folder_path, image_count FROM folder_stats ORDER BY folder_path ASC")
            else:
                cursor.execute("SELECT folder_path, COUNT(*) FROM images GROUP BY folder_path")
            stats = cursor.fetchall()
            conn.close()
            return stats
        except Exception as e:
            print(f"[Error] Failed to get stats: {e}"); return []

    def rename_file(self, old_path, new_name):
        folder = os.path.dirname(old_path); new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path): return False, "Target filename already exists."
        try:
            os.rename(old_path, new_path)
            conn = sqlite3.connect(self.config.db_path); cursor = conn.cursor()
            cursor.execute("UPDATE images SET file_path = ?, filename = ? WHERE file_path = ?", (new_path, new_name, old_path))
            conn.commit(); conn.close()
            for item in self.data_store:
                if item["path"] == old_path:
                    item["path"] = new_path; item["filename"] = new_name; break
            return True, new_path
        except Exception as e: return False, str(e)

    def search_hybrid(self, query, top_k=50, use_ocr=True):
        # [安全檢查] 增加檢查 stored_embeddings 是否存在
        if not self.is_ready or self.stored_embeddings is None: 
            return [] 
            
        results = []; query_lower = query.lower()
        try:
            with torch.no_grad():
                inputs = self.tokenizer(query, padding=True, truncation=True, return_tensors="pt").to(self.device)
                text_features = self.model.encode_text(inputs.input_ids)
                text_features /= text_features.norm(dim=-1, keepdim=True)
                text_features = text_features.to(self.stored_embeddings.dtype)
            
            similarity = (text_features @ self.stored_embeddings.T).squeeze(0)
            scores = similarity.cpu().numpy()
        except Exception as e:
            print(f"CLIP Search Error: {e}"); scores = np.zeros(len(self.data_store))

        for idx, item in enumerate(self.data_store):
            clip_score = float(scores[idx]); ocr_bonus = 0.0; name_bonus = 0.0
            if use_ocr and query_lower in item["ocr_text"]: ocr_bonus = 0.5
            if query_lower in item["filename"].lower(): name_bonus = 0.2
            final_score = clip_score + ocr_bonus + name_bonus
            if final_score > 0.15: 
                results.append({
                    "score": final_score, "clip_score": clip_score, "ocr_bonus": ocr_bonus, "name_bonus": name_bonus,
                    "is_ocr_match": (ocr_bonus > 0), "path": item["path"], "filename": item["filename"],
                    "ocr_data": item.get("ocr_data", []), "mtime": item.get("mtime", 0)
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_image(self, image_path, top_k=50):
        # [安全檢查]
        if not self.is_ready or self.stored_embeddings is None: 
            return []
            
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
                idx = indices[i].item(); item = self.data_store[idx]; score = values[i].item()
                results.append({
                    "score": score, "clip_score": score, "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                    "path": item["path"], "filename": item["filename"], "ocr_data": item.get("ocr_data", []), "mtime": item.get("mtime", 0)
                })
            return results
        except Exception as e:
            print(f"[Error] Image search failed: {e}"); return []

class SearchWorker(QThread):
    batch_ready = pyqtSignal(list) 
    finished_search = pyqtSignal(float, int)
    
    def __init__(self, engine, query, top_k, search_mode="text", use_ocr=True): 
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.search_mode = search_mode
        self.use_ocr = use_ocr

    def run(self):
        start_time = time.time()
        
        if self.search_mode == "image":
            raw_results = self.engine.search_image(self.query, self.top_k)
        else:
            raw_results = self.engine.search_hybrid(self.query, self.top_k, self.use_ocr)
            
        self.batch_ready.emit(raw_results)
        self.finished_search.emit(time.time() - start_time, len(raw_results))

# ==========================================
#  UI 元件
# ==========================================
class OCRLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ocr_data = []
        self.show_ocr_boxes = False
        self.original_size = QSize(0, 0)

    def set_ocr_data(self, data, orig_w, orig_h):
        self.ocr_data = data
        self.original_size = QSize(orig_w, orig_h)

    def set_draw_boxes(self, show):
        self.show_ocr_boxes = show
        self.update() 

    def paintEvent(self, event):
        super().paintEvent(event)
        
        # 只有在需要繪製 OCR 框、有資料且有圖片時才進入
        if self.show_ocr_boxes and self.ocr_data and self.pixmap():
            
            # [加入] 安全檢查：防止原始尺寸為 0 導致除法錯誤
            if self.original_size.width() == 0 or self.original_size.height() == 0:
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            pen = QPen(QColor(255, 0, 0, 200)) 
            pen.setWidth(2)
            painter.setPen(pen)
            
            displayed_w = self.pixmap().width()
            displayed_h = self.pixmap().height()
            
            offset_x = (self.width() - displayed_w) / 2
            offset_y = (self.height() - displayed_h) / 2
            
            # 這裡如果 original_size 是 0，沒有上面的檢查就會崩潰
            scale_x = displayed_w / self.original_size.width()
            scale_y = displayed_h / self.original_size.height()

            for item in self.ocr_data:
                box = item.get("box") 
                if box:
                    poly_points = []
                    for pt in box:
                        nx = pt[0] * scale_x + offset_x
                        ny = pt[1] * scale_y + offset_y
                        poly_points.append(QPoint(int(nx), int(ny)))
                    
                    painter.drawPolygon(QPolygon(poly_points))

class PreviewOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        self.setStyleSheet("background-color: rgba(0, 0, 0, 220);")
        
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
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
        # [修改] 兼容 ImageItem 物件
        if isinstance(result_data, ImageItem):
            path = result_data.path
            ocr_boxes = result_data.ocr_data
        else: # 字典
            path = result_data['path']
            ocr_boxes = result_data.get('ocr_data', [])

        if not os.path.exists(path): return
        
        img = QImage(path)
        if img.isNull(): return
        
        screen_size = self.parent().size()
        max_w = int(screen_size.width() * 0.85)
        max_h = int(screen_size.height() * 0.85)
        
        pixmap = QPixmap.fromImage(img)
        pixmap = pixmap.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        self.image_label.setPixmap(pixmap)
        
        orig_w, orig_h = img.width(), img.height()
        self.image_label.set_ocr_data(ocr_boxes, orig_w, orig_h)
        
        self.filename_label.setText(os.path.basename(path))
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()

    def set_ocr_visible(self, visible):
        self.image_label.set_draw_boxes(visible)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.hide()

    def mousePressEvent(self, event):
        self.hide()

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

class StatsMenuWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.setFixedWidth(420)
        self.setFixedHeight(500)
        self.setStyleSheet("""
            QFrame { background-color: #252525; border: 1px solid #3e3e3e; border-radius: 6px; }
            QLabel { color: #ccc; border: none; background: transparent; }
        """)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)
        
        title_container = QWidget()
        title_container.setStyleSheet("background-color: #2d2d2d; border-bottom: 1px solid #3e3e3e; border-top-left-radius: 6px; border-top-right-radius: 6px;")
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(15, 10, 15, 10)
        title_lbl = QLabel("Indexed Folders")
        title_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 14px;")
        title_layout.addWidget(title_lbl)
        self.main_layout.addWidget(title_container)

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
        
        footer_container = QWidget()
        footer_container.setStyleSheet("background-color: #2d2d2d; border-top: 1px solid #3e3e3e; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;")
        footer_layout = QHBoxLayout(footer_container)
        footer_layout.setContentsMargins(15, 8, 15, 8)
        self.total_label = QLabel("Total: 0 images")
        self.total_label.setStyleSheet("color: #60cdff; font-weight: bold;")
        footer_layout.addWidget(self.total_label, alignment=Qt.AlignmentFlag.AlignRight)
        self.main_layout.addWidget(footer_container)

    def update_stats(self, stats):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        if not stats:
            self.content_layout.addWidget(QLabel("No statistics available.\nRun indexer.py first."))
            self.total_label.setText("Total: 0 images")
            return
            
        total_images = 0
        fm = QFontMetrics(QFont("Segoe UI", 13)) 
        max_text_width = 340 

        for folder, count in stats:
            total_images += count
            
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(5, 5, 5, 5)
            row_layout.setSpacing(10)
            
            display_text = fm.elidedText(folder, Qt.TextElideMode.ElideMiddle, max_text_width)
            
            lbl_name = QLabel(display_text)
            lbl_name.setToolTip(folder)
            lbl_name.setStyleSheet("font-size: 13px; color: #dddddd;")
            
            lbl_count = QLabel(f"{count}")
            lbl_count.setStyleSheet("color: #aaaaaa; font-size: 13px; background-color: #333; padding: 2px 8px; border-radius: 10px;")
            lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            row_layout.addWidget(lbl_name, stretch=1)
            row_layout.addWidget(lbl_count)
            
            row.setStyleSheet(".QWidget:hover { background-color: #333333; border-radius: 4px; }")
            
            self.content_layout.addWidget(row)
            
        self.total_label.setText(f"Total: {total_images:,} images")

class FolderHoverMenu(QWidget):
    """
    [最終修正版] 二級點擊選單
    1. 改為 Popup 模式：點擊外部自動關閉，點擊按鈕切換顯示。
    2. 強制寬度計算：根據按鈕數量手動計算寬度，確保 "+" 按鈕 100% 顯示。
    """
    folder_clicked = pyqtSignal(str)
    add_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # [關鍵] 使用 Popup 屬性，這樣點擊視窗外部時會自動關閉
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 主佈局 (外層透明)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 內部容器
        self.container_frame = QFrame()
        self.container_frame.setObjectName("MenuContainer")
        
        # 容器佈局 (橫向排列)
        self.container_layout = QHBoxLayout(self.container_frame)
        self.container_layout.setContentsMargins(5, 5, 5, 5) # 邊距
        self.container_layout.setSpacing(5)              # 間距
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.main_layout.addWidget(self.container_frame)

        # 樣式表
        self.setStyleSheet("""
            QFrame#MenuContainer {
                background-color: rgba(45, 45, 45, 255); /* 改為不透明深色，避免視覺干擾 */
                border: 1px solid #666;
                border-radius: 0px;
            }
            QPushButton {
                background-color: #333;
                border: 1px solid #555;
                color: #eee;
                border-radius: 4px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #60cdff;
                color: #111;
                border: 1px solid #60cdff;
            }
            /* 新增按鈕特別樣式 (綠色加號) */
            QPushButton#AddBtn {
                background-color: #2a2a2a;
                border: 1px dashed #777;
                font-size: 20px;
                color: #aaa;
                font-weight: 900;
            }
            QPushButton#AddBtn:hover {
                background-color: #4caf50;
                border: 1px solid #4caf50;
                color: white;
            }
            QToolTip {
                background-color: #222;
                color: #fff;
                border: 1px solid #555;
            }
        """)

    def update_menu(self, stats):
        # 清除舊按鈕
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        btn_size = 48 # 按鈕尺寸
        
        # 1. 建立資料夾按鈕
        for folder_path, count in stats:
            btn = QPushButton()
            btn.setFixedSize(btn_size, btn_size)
            
            name = os.path.basename(folder_path)
            display_text = name[:2].upper() if len(name) >= 2 else name.upper()
            btn.setText(display_text)
            btn.setToolTip(f"{folder_path}\n({count} images)")
            
            btn.clicked.connect(lambda checked, p=folder_path: self.on_folder_click(p))
            self.container_layout.addWidget(btn)

        # 2. 建立「新增按鈕」 (+)
        self.btn_add = QPushButton("+")
        self.btn_add.setObjectName("AddBtn")
        self.btn_add.setFixedSize(btn_size, btn_size)
        self.btn_add.setToolTip("Add new folder source...")
        self.btn_add.clicked.connect(self.on_add_click)
        self.container_layout.addWidget(self.btn_add)

    def on_folder_click(self, path):
        self.folder_clicked.emit(path)
        self.close() # 點擊後關閉選單

    def on_add_click(self):
        self.add_clicked.emit()
        self.close()

    def show_at(self, global_pos, height):
        """
        顯示選單，並強制計算正確寬度
        """
        # 設定高度
        self.container_frame.setFixedHeight(height)
        
        # [關鍵修復] 手動計算寬度，解決 layout 更新不及導致切邊的問題
        # 寬度 = 左邊距(5) + 右邊距(5) + (按鈕數 * 寬度) + ((按鈕數-1) * 間距)
        
        btn_count = self.container_layout.count()
        btn_width = 48
        spacing = 5
        margin = 5
        
        if btn_count > 0:
            total_width = (margin * 2) + (btn_count * btn_width) + ((btn_count - 1) * spacing)
            # 加上一點緩衝 (2px) 避免邊框被切
            total_width += 4
        else:
            total_width = 100 # 預設值
            
        self.resize(total_width, height)
        self.container_frame.setFixedSize(total_width, height)

        # 移動並顯示
        self.move(global_pos)
        self.show()

class SidebarWidget(QFrame):
    folder_selected = pyqtSignal(str) 
    toggled = pyqtSignal(bool)
    add_folder_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.expanded_width = 240
        self.collapsed_width = 60 
        self.is_expanded = True
        self.stats_cache = []
        
        self.setStyleSheet("""
            QFrame { background-color: #252525; border-right: 1px solid #333; }
            QPushButton {
                background: transparent;
                border: none;
                color: #ccc;
                text-align: left;
                padding-left: 0px; 
            }
            QPushButton:hover {
                background-color: #333;
                color: white;
            }
            QPushButton#Row1 {
                border-left: 3px solid transparent; 
            }
            QPushButton#Row1:hover {
                background-color: #383838;
                border-left: 3px solid #60cdff; 
            }
        """)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 1. 漢堡選單
        self.btn_toggle = QPushButton("≡")
        self.btn_toggle.setFixedSize(60, 60)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet("font-size: 26px; text-align: center;")
        self.btn_toggle.clicked.connect(self.toggle_sidebar)
        self.layout.addWidget(self.btn_toggle)

        # 2. Row 1: All Images (點擊觸發選單)
        self.row1_container = QWidget()
        self.row1_container.setFixedHeight(60) 
        
        self.row1_layout = QHBoxLayout(self.row1_container)
        self.row1_layout.setContentsMargins(0, 0, 0, 0)
        self.row1_layout.setSpacing(0)
        
        self.btn_all_images = QPushButton()
        self.btn_all_images.setObjectName("Row1")
        self.btn_all_images.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_all_images.setFixedHeight(60)
        self.btn_all_images.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.icon_folder = QFileIconProvider().icon(QFileInfo("."))
        self.btn_all_images.setIcon(self.icon_folder)
        self.btn_all_images.setIconSize(QSize(24, 24))
        
        # [修改] 點擊時觸發選單，而不是只送出訊號
        self.btn_all_images.clicked.connect(self.on_row1_clicked)
        
        self.row1_layout.addWidget(self.btn_all_images)
        self.layout.addWidget(self.row1_container)

        # [修改] 移除了 eventFilter (不再需要懸浮觸發)
        
        # 3. 初始化二級選單
        self.hover_menu = FolderHoverMenu(self)
        self.hover_menu.folder_clicked.connect(self.on_sub_folder_clicked)
        self.hover_menu.add_clicked.connect(self.add_folder_requested.emit)
        
        self.update_ui_text()
        self.setFixedWidth(self.expanded_width)

    def update_folders(self, stats):
        self.stats_cache = stats
        self.hover_menu.update_menu(stats)
        total = sum(c for _, c in stats)
        self.all_images_text = f"  All Images ({total})"
        self.update_ui_text()

    def toggle_sidebar(self):
        self.is_expanded = not self.is_expanded
        self.setFixedWidth(self.expanded_width if self.is_expanded else self.collapsed_width)
        self.update_ui_text()
        self.toggled.emit(self.is_expanded)

    def update_ui_text(self):
        base_style = """
            QPushButton#Row1:hover {
                background-color: #383838;
                border-left: 3px solid #60cdff;
            }
        """
        if self.is_expanded:
            self.btn_all_images.setText(getattr(self, 'all_images_text', "  All Images"))
            self.btn_all_images.setStyleSheet(base_style + """
                QPushButton#Row1 { text-align: left; padding-left: 18px; border-left: 3px solid transparent; }
            """)
        else:
            self.btn_all_images.setText("")
            self.btn_all_images.setStyleSheet(base_style + """
                QPushButton#Row1 { text-align: center; padding-left: 0px; border-left: 3px solid transparent; }
            """)

    def on_row1_clicked(self):
        """點擊第一行資料夾時的動作"""
        # 1. 先執行「顯示全部」的邏輯 (如果您希望點擊也切換到首頁)
        self.folder_selected.emit("ALL")
        
        # 2. 切換顯示二級選單
        if self.hover_menu.isVisible():
            self.hover_menu.close()
        else:
            # 計算位置：Sidebar 右上角
            sidebar_global_pos = self.mapToGlobal(QPoint(0, 0))
            row1_y = self.btn_toggle.height()
            
            target_x = sidebar_global_pos.x() + self.width()
            target_y = sidebar_global_pos.y() + row1_y
            
            self.hover_menu.show_at(QPoint(target_x, target_y), 60)

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

class MainWindow(QMainWindow):
    # 定義訊號
    random_data_ready = pyqtSignal(list)
    ai_ready = pyqtSignal()

    def __init__(self, config: ConfigManager):
        # [關鍵修正] 這行一定要在第一行，且不能漏掉！
        super().__init__()
        
        self.config = config
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1280, 900)
        self.engine = None
        self.search_history = [] 
        self.current_selected_path = None
        
        # 設定歷史紀錄檔路徑
        self.history_file_path = os.path.join(self.config.app_root, "search_history.json")

        self.load_history()
        self.init_ui()
        
        # [修改 2] 連接訊號：當 AI 準備好時，執行 on_ai_loaded
        self.random_data_ready.connect(self.model.set_search_results)
        self.ai_ready.connect(self.on_ai_loaded)

        # 連接訊號
        self.random_data_ready.connect(self.model.set_search_results)

        QApplication.instance().installEventFilter(self)
        
        # 啟動背景載入 (這裡才會去建立 ImageSearchEngine)
        threading.Thread(target=self.load_engine, daemon=True).start()

    def init_ui(self):
        # ... (前段 layout 設定保持不變) ...
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 左側：側邊欄 ---
        self.sidebar = SidebarWidget()
        self.sidebar.folder_selected.connect(self.on_folder_filter)
        self.sidebar.toggled.connect(self.on_sidebar_toggled)

        self.sidebar.add_folder_requested.connect(self.on_add_folder_clicked)

        main_layout.addWidget(self.sidebar)
        
        # --- 右側 ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Top Bar
        top_bar = QFrame()
        # [修改] 高度改為 60，與側邊欄按鈕切齊
        top_bar.setFixedHeight(60) 
        top_bar.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #333;")
        header_layout = QHBoxLayout(top_bar)
        header_layout.setContentsMargins(20, 0, 30, 0)
        header_layout.setSpacing(15)
        
        title_label = QLabel("Gallery") 
        title_label.setStyleSheet("color: #e0e0e0; font-size: 18px; font-weight: 600;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch(1)
        
        # ... (中間搜尋區 search_container 設定保持不變) ...
        search_container = QWidget()
        search_container.setFixedWidth(500)
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Search images...")
        self.input.returnPressed.connect(self.start_search)
        self.chk_ocr = QCheckBox("OCR"); self.chk_ocr.setChecked(True)
        self.combo_limit = QComboBox(); self.combo_limit.addItems(["20", "50", "100", "All"]); self.combo_limit.setCurrentText("50")
        search_layout.addWidget(self.input, stretch=1); search_layout.addWidget(self.chk_ocr); search_layout.addWidget(self.combo_limit)
        header_layout.addWidget(search_container)
        
        # Status Label
        self.status = QLabel("Initializing..."); self.status.setStyleSheet("color: #888888; font-size: 12px; margin-left: 10px;")
        header_layout.addWidget(self.status)
        right_layout.addWidget(top_bar)
        
        self.progress = QProgressBar(); self.progress.hide(); right_layout.addWidget(self.progress)
        
        # List View
        self.list_view = QListView()
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setUniformItemSizes(True) 
        self.list_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.list_view.setSpacing(MIN_SPACING)
        self.list_view.setMouseTracking(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setStyleSheet("QListView { border: none; background-color: #1e1e1e; }")

        self.current_card_size = QSize(CARD_SIZE[0], CARD_SIZE[1])
        self.current_thumb_size = QSize(CARD_SIZE[0], THUMBNAIL_SIZE[1])
        self.current_view_mode = "large"

        self.model = SearchResultsModel(self.current_thumb_size)
        self.delegate = ImageDelegate(self.current_card_size, THUMBNAIL_SIZE[1])
        
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        
        self.list_view.clicked.connect(self.on_item_clicked)
        self.list_view.doubleClicked.connect(self.on_item_double_clicked)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        right_layout.addWidget(self.list_view)
        main_layout.addWidget(right_container)
        
        # 其他浮動元件
        self.history_list = QListWidget(self); self.history_list.hide(); self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(20); shadow.setColor(QColor(0, 0, 0, 100)); shadow.setOffset(0, 4); self.history_list.setGraphicsEffect(shadow)
        self.preview_overlay = PreviewOverlay(self)

    # [新增] 處理新增資料夾的 Slot
    def on_add_folder_clicked(self):
        from PyQt6.QtWidgets import QFileDialog
        
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            # 呼叫 ConfigManager 新增資料夾
            if self.config.add_source_folder(folder):
                QMessageBox.information(self, "Success", f"Added: {folder}\nPlease restart or re-index to scan new images.")
                # 若您的架構支援熱重載，可在此呼叫 self.engine.reload()
            else:
                QMessageBox.warning(self, "Duplicate", "This folder is already indexed.")

    def on_sidebar_toggled(self, is_expanded):
        """
        當側邊欄收合/展開時，強制 QListView 重新計算 Grid 佈局。
        """
        # 1. 強制處理所有的 Layout 事件，確保 sidebar 的寬度變更已經應用到 main_layout
        QApplication.processEvents()
        
        # 2. 重新計算間距
        self.adjust_layout()

    # [修正] 實作資料夾篩選邏輯
    def on_folder_filter(self, path):
        if not self.engine: return
        
        print(f"Filtering by: {path}")
        
        # 1. 如果是 "ALL"，顯示全部 (依時間排序)
        if path == "ALL":
            all_imgs = self.engine.get_all_images_sorted()
            self.model.set_search_results(all_imgs)
            self.status.setText(f"Showing all {len(all_imgs)} images")
            return

        # 2. 篩選特定資料夾
        # 這邊簡單用 Python list comprehension 過濾 (高效能做法建議在 Engine 寫 SQL)
        if self.engine.data_store:
            filtered = [
                item for item in self.engine.data_store 
                if item["path"].startswith(path)
            ]
            
            # 轉換格式給 Model
            results = []
            for item in filtered:
                results.append({
                    "score": 0.0,
                    "path": item["path"],
                    "filename": item["filename"],
                    "ocr_data": item.get("ocr_data", []),
                    "mtime": item.get("mtime", 0)
                })
            
            # 按時間排序
            results.sort(key=lambda x: x["mtime"], reverse=True)
            
            self.model.set_search_results(results)
            self.status.setText(f"Folder: {os.path.basename(path)} ({len(results)} items)")

    def eventFilter(self, obj, event):
        # 處理鍵盤按下 (KeyPress)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            
            # 全域 Shift 偵測 (按下) -> 開啟紅框
            if key == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible():
                    self.preview_overlay.set_ocr_visible(True)
                return True 

            if not self.input.hasFocus():
                if key == Qt.Key.Key_W:
                    self.list_view.setFocus(); self.send_nav_key(Qt.Key.Key_Up); return True
                elif key == Qt.Key.Key_S:
                    self.list_view.setFocus(); self.send_nav_key(Qt.Key.Key_Down); return True
                elif key == Qt.Key.Key_A:
                    self.list_view.setFocus(); self.send_nav_key(Qt.Key.Key_Left); return True
                elif key == Qt.Key.Key_D:
                    self.list_view.setFocus(); self.send_nav_key(Qt.Key.Key_Right); return True
                elif key == Qt.Key.Key_Space:
                    self.toggle_preview(); return True
        
        # 處理鍵盤放開 (KeyRelease) -> 關閉紅框
        if event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible():
                    self.preview_overlay.set_ocr_visible(False)
                return True

        # 處理滑鼠點擊 (MouseButtonPress)
        if event.type() == QEvent.Type.MouseButtonPress:
            click_pos = event.globalPosition().toPoint()
            
            # 點擊外部關閉歷史紀錄
            if self.history_list.isVisible():
                input_rect = QRect(self.input.mapToGlobal(QPoint(0, 0)), self.input.size())
                list_rect = QRect(self.history_list.mapToGlobal(QPoint(0, 0)), self.history_list.size())
                if not input_rect.contains(click_pos) and not list_rect.contains(click_pos): 
                    self.history_list.hide()
            
            # [修正] 移除舊的 stats_menu 判斷邏輯
            # if self.stats_menu.isVisible(): ... (已刪除)

            if obj == self.input: 
                self.show_history_popup()

        return super().eventFilter(obj, event)

    # [新增] 輔助函式：發送模擬按鍵給 ListView
    def send_nav_key(self, key_code):
        from PyQt6.QtGui import QKeyEvent
        press_event = QKeyEvent(QEvent.Type.KeyPress, key_code, Qt.KeyboardModifier.NoModifier)
        release_event = QKeyEvent(QEvent.Type.KeyRelease, key_code, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.list_view, press_event)
        QApplication.sendEvent(self.list_view, release_event)

    def toggle_preview(self):
        if self.preview_overlay.isVisible():
            self.preview_overlay.hide()
        else:
            # 獲取選取項目
            index = self.list_view.currentIndex()
            if index.isValid():
                item = index.data(Qt.ItemDataRole.UserRole)
                if item:
                    self.preview_overlay.show_image(item)

    def on_ai_loaded(self):
        """當 AI 模型載入完成後被呼叫 (會在主執行緒執行)"""
        count = len(self.engine.data_store) if self.engine else 0
        self.status.setText(f"System Ready ({count} images)")
        self.progress.hide()
        
        # 這裡會去抓取資料夾統計，並建立二級選單的按鈕
        if self.engine:
            stats = self.engine.get_folder_stats()
            self.sidebar.update_folders(stats) # 這行才是真正建立按鈕的地方！

    # 右鍵選單邏輯
    def show_context_menu(self, pos):
        index = self.list_view.indexAt(pos)
        menu = QMenu(self)
        
        if index.isValid():
            item = index.data(Qt.ItemDataRole.UserRole)
            if not item: return

            action_copy = QAction("Copy Image", self)
            action_copy.triggered.connect(lambda: self.copy_image_to_clipboard(item.path))
            action_path = QAction("Copy Path", self)
            action_path.triggered.connect(lambda: QApplication.clipboard().setText(item.path))
            action_search = QAction("Search Similar", self)
            action_search.triggered.connect(lambda: self.start_image_search(item.path))
            action_rename = QAction("Rename", self)
            action_rename.triggered.connect(lambda: self.handle_rename_model(index, item))
            action_props = QAction("Properties", self)
            action_props.triggered.connect(lambda: self.show_properties_dialog(item))

            menu.addAction(action_copy)
            menu.addAction(action_path)
            menu.addAction(action_search)
            menu.addSeparator()
            menu.addAction(action_rename)
            menu.addAction(action_props)
        else:
            view_menu = menu.addMenu("檢視 (View)")
            
            action_xl = QAction("超大圖示 (Extra Large)", self); action_xl.setCheckable(True)
            action_xl.setChecked(self.current_view_mode == "xl")
            action_xl.triggered.connect(lambda: self.change_view_mode("xl"))
            
            action_l = QAction("大圖示 (Large)", self); action_l.setCheckable(True)
            action_l.setChecked(self.current_view_mode == "large")
            action_l.triggered.connect(lambda: self.change_view_mode("large"))
            
            action_m = QAction("中圖示 (Medium)", self); action_m.setCheckable(True)
            action_m.setChecked(self.current_view_mode == "medium")
            action_m.triggered.connect(lambda: self.change_view_mode("medium"))
            
            group = QActionGroup(self)
            group.addAction(action_xl); group.addAction(action_l); group.addAction(action_m)
            view_menu.addAction(action_xl); view_menu.addAction(action_l); view_menu.addAction(action_m)

        menu.exec(self.list_view.mapToGlobal(pos))

    def change_view_mode(self, mode):
        if mode == self.current_view_mode: return
        self.current_view_mode = mode
        
        if mode == "xl":
            new_card_size = QSize(320, 380); thumb_h = 240
        elif mode == "large":
            new_card_size = QSize(240, 290); thumb_h = 160
        elif mode == "medium":
            new_card_size = QSize(180, 230); thumb_h = 120
        else: return

        self.current_card_size = new_card_size
        self.current_thumb_size = QSize(new_card_size.width(), thumb_h)

        self.delegate.set_view_params(new_card_size, thumb_h)
        self.model.update_target_size(self.current_thumb_size)
        self.model.layoutChanged.emit()
        self.adjust_layout()

    def adjust_layout(self):
        """
        [回歸 test.py 邏輯] 全動態均分佈局
        1. 放棄上方固定距離，讓 Top Margin 跟隨左右間距自動調整。
        2. 算法：剩餘空間 / (列數 + 1)。
        3. 效果：四周邊距 (上、下、左、右) 與圖片間距完全相等，視覺上最和諧。
        """
        # 防呆
        if not hasattr(self, 'list_view') or self.list_view.width() <= 0: return

        # 1. 取得 ListView 當前寬度
        # 因為這是在 Sidebar 旁邊，這個寬度已經是扣除 Sidebar 後的剩餘寬度
        raw_width = self.list_view.width()
        
        # 2. 扣除滾動條預留空間
        # test.py 使用 26px，我們這裡照抄以確保行為一致
        # (這包含滾動條本體 8px + 左右緩衝)
        view_w = raw_width - 26
        
        # 取得目前卡片寬度
        item_w = self.current_card_size.width()
        
        # 3. 計算列數 (Columns)
        n_cols = view_w // item_w
        if n_cols < 1: n_cols = 1
        
        # 4. 計算剩餘空間
        total_card_w = n_cols * item_w
        remaining_space = view_w - total_card_w
        
        # 5. 計算間距 (Space)
        # 邏輯：均分給 (左邊界 + 所有圖片間隙 + 右邊界)
        # 總縫隙數 = n_cols + 1
        space = int(remaining_space // (n_cols + 1))
        
        # 安全限制：不小於 0
        space = max(0, space)

        # 6. 應用設定
        # setSpacing: 圖片之間的距離
        self.list_view.setSpacing(space)
        
        # setContentsMargins: 四周邊界
        # 關鍵差異：這裡把 Top (第二個參數) 也設為 space，不再鎖死 20
        self.list_view.setContentsMargins(space, space, space, space)

    def on_item_clicked(self, index):
        if not index.isValid(): return
        item = index.data(Qt.ItemDataRole.UserRole)
        if item: self.current_selected_path = item.path

    def on_item_double_clicked(self, index):
        if not index.isValid(): return
        item = index.data(Qt.ItemDataRole.UserRole)
        if item:
            try: os.startfile(item.path)
            except: pass

    def copy_image_to_clipboard(self, path):
        try:
            img = QImage(path)
            if not img.isNull(): QApplication.clipboard().setImage(img)
        except: pass

    def show_properties_dialog(self, item):
        from datetime import datetime
        date_str = "Unknown"
        if item.mtime > 0:
            date_str = datetime.fromtimestamp(item.mtime).strftime('%Y-%m-%d %H:%M')
        msg = f"<h3>{item.filename}</h3><hr><b>Path:</b> {item.path}<br><b>Score:</b> {item.score:.4f}<br><b>Date:</b> {date_str}"
        QMessageBox.information(self, "Properties", msg)

    def handle_rename_model(self, index, item):
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=item.filename)
        if ok and new_name and new_name != item.filename:
            success, result = self.engine.rename_file(item.path, new_name)
            if success:
                item.filename = new_name
                item.path = result 
                self.model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            else:
                QMessageBox.warning(self, "Error", f"Rename failed: {result}")

    def load_history(self):
        # [修改 3] 使用 self.history_file_path
        if os.path.exists(self.history_file_path):
            try:
                with open(self.history_file_path, 'r', encoding='utf-8') as f: 
                    self.search_history = json.load(f)
            except: self.search_history = []

    def save_history_to_file(self):
        # [修改 4] 使用 self.history_file_path
        try:
            with open(self.history_file_path, 'w', encoding='utf-8') as f: 
                json.dump(self.search_history, f, ensure_ascii=False)
        except: pass

    def add_to_history(self, query):
        if not query: return
        if query in self.search_history: self.search_history.remove(query)
        self.search_history.insert(0, query); 
        if len(self.search_history) > 10: self.search_history = self.search_history[:10]
        self.save_history_to_file()

    def delete_history_item(self, text):
        if text in self.search_history: self.search_history.remove(text); self.save_history_to_file(); self.show_history_popup()
    
    def trigger_history_search(self, text): 
        self.input.setText(text); self.start_search()

    def show_history_popup(self):
        if not self.search_history: self.history_list.hide(); return
        self.history_list.clear()
        title_item = QListWidgetItem()
        title_widget = QLabel(" Recent Searches")
        title_widget.setStyleSheet("color: #888888; font-size: 12px; padding: 4px;")
        title_item.setFlags(Qt.ItemFlag.NoItemFlags)
        title_item.setSizeHint(QSize(0, 30))
        self.history_list.addItem(title_item)
        self.history_list.setItemWidget(title_item, title_widget)
        
        for text in self.search_history:
            item = QListWidgetItem(); item.setSizeHint(QSize(0, 44))
            widget = HistoryItemWidget(text, search_callback=self.trigger_history_search, delete_callback=self.delete_history_item)
            self.history_list.addItem(item); self.history_list.setItemWidget(item, widget)
            
        input_pos = self.input.mapTo(self, QPoint(0, 0))
        list_height = min(320, self.history_list.sizeHintForRow(0) * (len(self.search_history) + 1) + 20)
        self.history_list.setGeometry(input_pos.x(), input_pos.y() + self.input.height() + 8, self.input.width(), list_height)
        self.history_list.show(); self.history_list.raise_()
    
    def load_engine(self):
        try:
            #self.status.setText("Loading Database...")
            
            # 正確建立 Engine 實例
            self.engine = ImageSearchEngine(self.config)
            
            #self.status.setText("Rendering Gallery...")
            # 呼叫排序方法
            all_images = self.engine.get_all_images_sorted()
            
            if all_images:
                self.random_data_ready.emit(all_images)
                self.status.setText(f"Loaded {len(all_images)} images. Loading AI in background...")
            
            time.sleep(0.05)
            
            # 載入模型
            self.engine.load_ai_models()

            self.ai_ready.emit()
            
            QApplication.processEvents()
            self.status.setText(f"System Ready ({len(all_images)} images indexed)")
            
        except Exception as e: 
            print(f"Engine Load Error: {e}")
            import traceback
            traceback.print_exc()
        
    def start_search(self):
        q = self.input.text().strip()
        if not q or not self.engine: return
        
        self.add_to_history(q)
        self.history_list.hide()
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status.setText("Searching...")
        
        limit = self.combo_limit.currentText()
        k = 100000 if limit == "All" else int(limit)
        
        # [修改] 使用新的 Worker，並連接到 Model
        self.worker = SearchWorker(self.engine, q, k, search_mode="text", use_ocr=self.chk_ocr.isChecked())
        self.worker.batch_ready.connect(self.model.set_search_results)
        self.worker.finished_search.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def start_image_search(self, image_path):
        if not self.engine: return
        self.history_list.hide(); self.progress.show(); self.progress.setRange(0, 0)
        self.status.setText("Searching by Image...")
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        
        limit = self.combo_limit.currentText()
        k = 100000 if limit == "All" else int(limit)
        
        self.worker = SearchWorker(self.engine, image_path, k, search_mode="image")
        self.worker.batch_ready.connect(self.model.set_search_results)
        self.worker.finished_search.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # 隱藏浮動視窗
        self.history_list.hide()
        if self.preview_overlay.isVisible():
            self.preview_overlay.resize(self.size())
            
        # [關鍵] 視窗大小改變時，Viewport 寬度也會變，必須重算
        # 使用 QTimer.singleShot 0 毫秒，確保在 resize 事件完成後才計算，避免卡頓與計算錯誤
        QTimer.singleShot(0, self.adjust_layout)

    def showEvent(self, event):
        super().showEvent(event)
        # 延遲觸發，確保 Qt 的幾何運算已經完成
        QTimer.singleShot(10, self.adjust_layout)

    def on_finished(self, elapsed, total): self.progress.hide(); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

if __name__ == "__main__":
    # 1. 初始化 ConfigManager (這會自動建立 config.json 如果不存在)
    app_config = ConfigManager()

    # (可選) 檢查是否為第一次執行，如果是，可以在這裡跳出提示
    if not app_config.get("source_folders"):
        print("提示：目前沒有設定圖片來源資料夾，請在 config.json 中設定或之後透過介面新增。")

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        
    app = QApplication(sys.argv)
    app.setStyleSheet(WIN11_STYLESHEET)
    
    # 2. 將 config 傳入主視窗
    w = MainWindow(app_config) 
    w.show()
    sys.exit(app.exec())
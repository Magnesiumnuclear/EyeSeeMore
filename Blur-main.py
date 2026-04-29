import sys
import os
import time
import sqlite3
import threading
import json
from PIL import Image

import numpy as np
import onnxruntime as ort

from transformers import AutoTokenizer 
from datetime import datetime
from collections import OrderedDict
from indexer import IndexerService
import re

from indexer import IndexerService, NumpyPreprocess

import subprocess

import faiss

from core.search_orchestrator import SearchOrchestrator
from core.image_action_manager import ImageActionManager
from utils.translator import Translator

# [New] 引入設定管理器
from core.config_manager import ConfigManager
from ui.theme_manager import ThemeManager

# [修正] 確保所有 PyQt6 模組都已引入
from PyQt6.QtGui import QActionGroup
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLayout, QLineEdit, QPushButton, 
                             QLabel, QScrollArea, QComboBox, QProgressBar, QFrame,
                             QListWidget, QListWidgetItem, QSizePolicy, QMenu, QMessageBox,
                             QGraphicsDropShadowEffect, QCheckBox, QInputDialog, QDialog,
                             QStyledItemDelegate, QStyle, QFileIconProvider, QAbstractItemView, QListView,
                             QRadioButton, QGroupBox, QStackedWidget, QTabWidget, QGridLayout, QSplitter
                             , QSlider)
from PyQt6.QtCore import (Qt, QThread, pyqtSignal, QPoint, QPointF, QRect, QRectF, QSize, QEvent, 
                          QFileInfo, QTimer, QAbstractListModel, QRunnable, QThreadPool, QObject, QModelIndex, QByteArray)
from PyQt6.QtGui import (QPixmap, QImage, QCursor, QAction, QColor, QFont, QKeySequence, 
                         QShortcut, QFontMetrics, QPainter, QBrush, QPen, QIcon, QPainterPath, QPolygon, QImageReader
                         , QDrag, QRegion)

THUMBNAIL_SIZE = (220, 180)
CARD_SIZE = (240, 290) 
MIN_SPACING = 24       
WINDOW_TITLE = "EyeSeeMore-(Alpha)"

'''
EyeSeeMore 
的核心靈魂在於其諧音：「I see more (我看見更多)」。
它代表著即便圖片的檔名是毫無意義的亂碼，軟體依然能穿透表象，看見圖片真正的意涵與內含的文字。
核心設計哲學：回歸圖像本質
無視亂碼檔名：打破「檔名即搜尋關鍵字」的傳統限制，即便圖片檔名是隨機生成的字串，系統也能精準命中。
「看」而非「讀」：傳統軟體是在「讀」標籤，EyeSeeMore 則是透過視覺模型在「看」內容，提取抽象的語義特徵。
'''



# TODO: [UI 改造] 將「AI 引擎設定」頁面重構為「模型管理中心」
# TODO: [互動邏輯] 實作左側「收合選單資料夾」的點擊與右鍵行為
# TODO: 介面與顯示優化：在圖片卡片上顯示更多資訊（如修改日期、OCR 文字預覽等），並優化分數顯示的視覺效果
# TODO: Help -> About 內加入版本資訊、開發者聯繫方式、GitHub 頁面連結等GPL (General Public License) 協議要求的資訊
# TODO: 搜尋介面的ORC控制的分數控制
# TODO: 控制欄的UIUX優化
# TODO: OCR 紅框互動能直接在預覽端修改OCR辨識的結果
# TODO: 想要加上Satisfactory主題的UI樣式
# TODO: 想要加上BlueArchive主題的UI樣式
# TODO: 刪除 Unicode 符號 減少AI味
# TODO: BUG 由手機相機拍的圖片視覺規格都是width > height 的導致橫圖直圖 塞選沒用
# TODO: 分隔正向量與負向量的拖拽功能

import sys
import ctypes
from ctypes import wintypes

# 定義 Windows 工作列狀態常數
TBPF_NOPROGRESS = 0       # 隱藏 / 恢復正常
TBPF_INDETERMINATE = 0x1  # 綠色流光 (載入中)
TBPF_NORMAL = 0x2         # 綠色進度條 (處理中)
TBPF_ERROR = 0x4          # 紅色進度條 (發生錯誤)
TBPF_PAUSED = 0x8         # 黃色進度條 (暫停)

if sys.platform == 'win32':
    ole32 = ctypes.windll.ole32

    # 定義 GUID 結構
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8)
        ]

    # ITaskbarList3 的虛擬函數表 (VTable)
    class ITaskbarList3Vtbl(ctypes.Structure):
        _fields_ = [
            ("QueryInterface", ctypes.c_void_p),
            ("AddRef", ctypes.c_void_p),
            ("Release", ctypes.c_void_p),
            ("HrInit", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)),
            ("AddTab", ctypes.c_void_p),
            ("DeleteTab", ctypes.c_void_p),
            ("ActivateTab", ctypes.c_void_p),
            ("SetActiveAlt", ctypes.c_void_p),
            ("MarkFullscreenWindow", ctypes.c_void_p),
            # [關鍵] 設定進度條數值的函數指標
            ("SetProgressValue", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, ctypes.c_uint64, ctypes.c_uint64)),
            # [關鍵] 設定進度條狀態的函數指標
            ("SetProgressState", ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, ctypes.c_int)),
            ("RegisterTab", ctypes.c_void_p),
            ("UnregisterTab", ctypes.c_void_p),
            ("SetTabOrder", ctypes.c_void_p),
            ("SetTabActive", ctypes.c_void_p),
            ("ThumbBarAddButtons", ctypes.c_void_p),
            ("ThumbBarUpdateButtons", ctypes.c_void_p),
            ("ThumbBarSetImageList", ctypes.c_void_p),
            ("SetOverlayIcon", ctypes.c_void_p),
            ("SetThumbnailTooltip", ctypes.c_void_p),
            ("SetThumbnailClip", ctypes.c_void_p)
        ]

    class ITaskbarList3(ctypes.Structure):
        _fields_ = [("lpVtbl", ctypes.POINTER(ITaskbarList3Vtbl))]

    # CLSID 與 IID 定義
    CLSID_TaskbarList = GUID(0x56FDF344, 0xFD6D, 0x11d0, (0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90))
    IID_ITaskbarList3 = GUID(0xEA1AFB91, 0x9E28, 0x4B86, (0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF))


# Translator 已移至 utils/translator.py

class TaskbarController:
    """用來控制 Windows 工作列圖示的萬能控制器"""
    def __init__(self, window_id):
        self.hwnd = int(window_id)  # 取得 PyQt 視窗的底層 HWND
        self.taskbar = None
        if sys.platform == 'win32':
            self._init_com()

    def _init_com(self):
        try:
            # 確保 COM 被初始化
            ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
            
            # 建立 ITaskbarList3 實例
            obj = ctypes.POINTER(ITaskbarList3)()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_TaskbarList),
                None,
                1,  # CLSCTX_INPROC_SERVER
                ctypes.byref(IID_ITaskbarList3),
                ctypes.byref(obj)
            )
            
            if hr == 0:
                self.taskbar = obj
                # 呼叫 HrInit 啟用工作列控制
                self.taskbar.contents.lpVtbl.contents.HrInit(self.taskbar)
        except Exception as e:
            print(f"Taskbar init error: {e}")

    def set_state(self, state_code):
        """切換進度條狀態 (如綠色、紅色、流光)"""
        if self.taskbar:
            self.taskbar.contents.lpVtbl.contents.SetProgressState(self.taskbar, self.hwnd, state_code)

    def set_progress(self, current, total):
        """設定進度條百分比"""
        if self.taskbar and total > 0:
            self.taskbar.contents.lpVtbl.contents.SetProgressValue(self.taskbar, self.hwnd, current, total)
# ==========================================


class ImageItem:
    """單張圖片的資料結構，統一管理所有屬性"""
    def __init__(self, path, filename, score, ocr_text="", mtime=0, width=0, height=0):
        self.path = path
        self.filename = filename
        self.score = score
        self.ocr_text = ocr_text
        self.mtime = mtime
        self.width = width
        self.height = height
        self.is_ocr_match = False
        self.is_pinned = False

        self.score_val = float(score)
        self.score_str = f"{self.score_val:.4f}" if self.score_val > 0.0001 else ""
        self._elided_name_cache = {}

    def get_elided_name(self, fm, width):
        """動態快取省略檔名，相同寬度的卡片只需要計算一次"""
        if width not in self._elided_name_cache:
            self._elided_name_cache[width] = fm.elidedText(self.filename, Qt.TextElideMode.ElideRight, width)
        return self._elided_name_cache[width]

class WorkerSignals(QObject):
    result = pyqtSignal(str, QPixmap, bool) #加入一個布林值 is_final，讓系統知道這是不是最終的高清圖

class PreviewSignals(QObject):
    #  關鍵修復：將跨執行緒的傳遞物件從 QPixmap 換成絕對安全的 QImage
    result = pyqtSignal(str, QImage, list, int, int, str, bool)

class PreviewLoader(QRunnable):
    """專門用於大圖預覽的高清背景讀取器 + 幾何碰撞運算器"""
    def __init__(self, file_path, target_size, engine, query, is_precise, orig_w, orig_h):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.engine = engine  #  拿到引擎準備去撈資料
        self.query = query
        self.is_precise = is_precise
        self.orig_w = orig_w
        self.orig_h = orig_h
        self.signals = PreviewSignals()
        self.is_cancelled = False

    def _sort_points(self, box):
        """背景排序：將 OpenCV 隨機順序的四個點定義為 TL, TR, BR, BL"""
        import numpy as np
        pts = np.array(box)
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1) 
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect.tolist()

    def run(self):
        if self.is_cancelled: return
        
        # ==========================================
        #  任務 A-0：背景向 SQLite 請求 JSON 解析 (秒速且不卡 UI)
        # ==========================================
        raw_ocr_data = []
        if self.engine:
            raw_ocr_data = self.engine.get_ocr_data_by_path(self.file_path)

        if self.is_cancelled: return
        
        # ==========================================
        #  任務 A：背景執行 Shapely 群組合併
        # ==========================================
        merged_data = []
        try:
            from shapely.geometry import Polygon as ShapelyPolygon
        except ImportError:
            ShapelyPolygon = None

        if not ShapelyPolygon:
            #  這裡原本用 self.raw_ocr_data，現在改用剛剛撈出來的 raw_ocr_data
            for item in raw_ocr_data:
                merged_data.append({
                    "box": item.get("box", []),
                    "results": [{"lang": item.get("lang", "unk"), "text": item.get("text", ""), "conf": item.get("conf", 0.0)}]
                })
        else:
            for item in raw_ocr_data:
                if self.is_cancelled: return
                box = item.get("box")
                # ... (下面的 Shapely 合併邏輯完全維持不變，只要確保迴圈是用 raw_ocr_data 即可) ...
                if not box or len(box) != 4: continue
                
                try:
                    sorted_box = self._sort_points(box)
                    current_poly = ShapelyPolygon(sorted_box)
                    if not current_poly.is_valid or current_poly.area <= 0: continue
                except: 
                    continue
                
                is_merged = False
                for existing in merged_data:
                    existing_poly = existing.get("poly")
                    if not existing_poly: continue
                    try:
                        if current_poly.intersects(existing_poly):
                            inter_area = current_poly.intersection(existing_poly).area
                            min_area = min(current_poly.area, existing_poly.area)
                            if (inter_area / min_area) > 0.85:
                                existing["results"].append({
                                    "lang": item.get("lang", "unk"),
                                    "text": item.get("text", ""),
                                    "conf": item.get("conf", 0.0)
                                })
                                is_merged = True
                                break
                    except: pass
                
                if not is_merged:
                    merged_data.append({
                        "box": sorted_box,
                        "poly": current_poly,
                        "results": [{
                            "lang": item.get("lang", "unk"),
                            "text": item.get("text", ""),
                            "conf": item.get("conf", 0.0)
                        }]
                    })
        
        for m in merged_data:
            m.pop("poly", None)

        if self.is_cancelled: return

        # ==========================================
        #  任務 B：背景讀取高清圖片 (改用 QImage)
        # ==========================================
        final_img = QImage() # 建立一個空的 QImage 作為預設值
        try:
            reader = QImageReader(self.file_path)
            reader.setAutoTransform(True)
            orig_size = reader.size()
            
            if orig_size.isValid():
                scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(scaled_size)
                img = reader.read()
                
                if not self.is_cancelled and not img.isNull():
                    # 轉換格式，但保持為 QImage
                    final_img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        except Exception as e:
            print(f"Preview Loader Error: {e}")

        if not self.is_cancelled:
            # 安全地將 QImage 與 OCR 資料一起發射給主執行緒
            self.signals.result.emit(self.file_path, final_img, merged_data, self.orig_w, self.orig_h, self.query, self.is_precise)

class ThumbnailLoader(QRunnable):
    """背景圖片讀取器 (智慧縮放 + GPU 材質加速版)"""
    def __init__(self, file_path, target_size):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.signals = WorkerSignals()
        self.is_cancelled = False

    def run(self):
        if self.is_cancelled:
            self.signals.result.emit(self.file_path, QPixmap(), True)
            return

        import hashlib
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.join(base_dir, ".cache", "thumbnails")
        
        path_hash = hashlib.md5(self.file_path.encode('utf-8')).hexdigest()
        cache_path = os.path.join(cache_dir, f"{path_hash}.webp")

        image = QImage()
        has_l2 = False
        
        if os.path.exists(cache_path):
            image.load(cache_path)
            if not image.isNull():
                has_l2 = True

        #  判定：目標尺寸如果大於 256 (例如 XL 模式)，代表 L2 尺寸不夠，需要升級！
        needs_upgrade = (self.target_size.width() > 256 or self.target_size.height() > 256)

        # ==========================================
        #  階段一：光速發射 L2 佔位圖 (毫秒級)
        # ==========================================
        if has_l2:
            if self.is_cancelled:
                self.signals.result.emit(self.file_path, QPixmap(), True)
                return
            
            # 關鍵魔法：在背景將小圖「平滑放大」到目標尺寸，UI 接手時直接貼上就好！
            scaled_l2 = image.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pixmap = QPixmap.fromImage(scaled_l2.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
            
            # 第一發射：先讓畫面有圖，並標記是否為最終圖
            self.signals.result.emit(self.file_path, pixmap, not needs_upgrade)
            
            if not needs_upgrade:
                return # M/L 模式在這裡就結束了，極度省電！

        # ==========================================
        #  階段二：背景替換高清大圖 (重炮火力)
        # ==========================================
        if self.is_cancelled:
            self.signals.result.emit(self.file_path, QPixmap(), True)
            return

        try:
            reader = QImageReader(self.file_path)
            orig_size = reader.size()
            if orig_size.isValid():
                scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(scaled_size)
                reader.setAutoTransform(True)
                high_res_image = reader.read()

                # 動態補建 L2 (如果之前沒有的話)
                if not has_l2 and not high_res_image.isNull() and not self.is_cancelled:
                    os.makedirs(cache_dir, exist_ok=True)
                    high_res_image.save(cache_path, "WEBP", 80)

                if self.is_cancelled:
                    self.signals.result.emit(self.file_path, QPixmap(), True)
                    return

                if not high_res_image.isNull():
                    final_pixmap = QPixmap.fromImage(high_res_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
                    #  第二發射：高清原圖覆蓋上去！(is_final = True)
                    self.signals.result.emit(self.file_path, final_pixmap, True)
                else:
                    self.signals.result.emit(self.file_path, QPixmap(), True)
            else:
                self.signals.result.emit(self.file_path, QPixmap(), True)
        except Exception:
            self.signals.result.emit(self.file_path, QPixmap(), True)

class SearchResultsModel(QAbstractListModel):
    """核心 Model：管理搜尋結果列表與圖片快取 (完全原生虛擬化)"""
    def __init__(self, item_size):
        super().__init__()
        #  瘦身 1：只保留唯一的 all_items 陣列
        self.all_items = []  
        self._pending_batch_requests = OrderedDict() # 收集同一幀內的所有讀圖請求
        self._batch_timer_active = False # 確保單幀只啟動一次計時器
        
        self.item_size = item_size 
        self._thumbnail_cache = OrderedDict()
        
        # 快取大小維持 1000 確保回滾流暢
        self.CACHE_SIZE = 1000 
        
        self._loading_set = set() 
        self._active_workers = {} 
        
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(8)

        self._pending_updates = set()
        self.update_timer = QTimer()
        self.update_timer.setInterval(50)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._flush_updates)

    def update_target_size(self, new_size):
        self.item_size = new_size
        
        #  智慧記憶體管理：防止 XL 的高清大圖塞爆記憶體
        # 如果卡片寬度大於 256px (代表是 XL 模式)，快取數量縮小到 250 張
        # 其餘模式維持 1000 張
        if new_size.width() > 256:
            self.CACHE_SIZE = 250
        else:
            self.CACHE_SIZE = 1000
            
        self._thumbnail_cache.clear()
        self._loading_set.clear()

    def set_search_results(self, results_dict_list):
        self.beginResetModel()
        
        for worker in self._active_workers.values():
            worker.is_cancelled = True
        self._active_workers.clear()
        
        self.all_items = []
        self.path_to_row = {}

        self._thumbnail_cache.clear()
        self._loading_set.clear()
        
        for idx, res in enumerate(results_dict_list):
            item = ImageItem(
                path=res['path'],
                filename=res['filename'],
                score=res['score'],
                ocr_text=res.get('ocr_text', ""),
                # 🗑️ 刪除這行： ocr_data=res.get('ocr_data', []),  <-- 就是這行惹的禍！
                mtime=res.get('mtime', 0),
                width=res.get('width', 0),
                height=res.get('height', 0)
            )
            if res.get('is_ocr_match', False):
                item.is_ocr_match = True
            if res.get('is_pinned', False):
                item.is_pinned = True
            self.all_items.append(item)
            self.path_to_row[item.path] = idx
            
        self.endResetModel()

    def sort_items(self, key_func, reverse=False):
        """排序時直接對 all_items 排序，不再需要洗牌第一批"""
        self.beginResetModel()
        self.all_items.sort(key=key_func, reverse=reverse)
        # 排序後必須重建 path_to_row，否則索引與實際位置脫節
        self.path_to_row = {item.path: i for i, item in enumerate(self.all_items)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        #  瘦身 4：解放限制，直接回傳真實總數量
        return len(self.all_items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.all_items)):
            return None

        #  瘦身 5：資料來源改為 all_items
        item = self.all_items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
        elif role == Qt.ItemDataRole.UserRole:
            return item 
        elif role == Qt.ItemDataRole.DecorationRole:
            if item.path in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(item.path)
                return self._thumbnail_cache[item.path]
            
            #  單幀批量攔截：不直接發送任務，而是先丟進「購物車」
            if item.path not in self._loading_set:
                self._pending_batch_requests[item.path] = None
                
                # 如果這一幀還沒叫結帳員，就呼叫他 (0毫秒後也就是這幀結束時觸發)
                if not self._batch_timer_active:
                    self._batch_timer_active = True
                    QTimer.singleShot(0, self._process_batch_requests)
            return None

        return None
    
    def _process_batch_requests(self):
        """單幀結束時瞬間觸發：負責結算並過濾這 16 毫秒內的暴衝請求"""
        self._batch_timer_active = False
        if not self._pending_batch_requests:
            return
            
        # 取得這一幀內累積的所有圖片請求
        paths_to_load = list(self._pending_batch_requests.keys())
        self._pending_batch_requests.clear()
        
        #  核心過濾魔法：判斷是「精確導航」還是「快速拖拽」
        # XL 模式一頁約 15 張，M 模式約 50 張。我們取一個合理的閥值 (例如 40)
        if len(paths_to_load) > 40:
            # 請求數量異常龐大 -> 狂刷中！只取「最後面」的 40 張 (目前顯示在畫面上的)
            target_paths = paths_to_load[-40:]
        else:
            # 請求數量正常 -> WASD 導航！全部保留
            target_paths = paths_to_load
            
        # 正式派發背景任務
        for path in target_paths:
            if path not in self._loading_set: # 雙重檢查
                self.request_thumbnail(path)

    # (以下 request_thumbnail, on_thumbnail_loaded, _flush_updates 保持原樣不變)
    def request_thumbnail(self, file_path):
        self._loading_set.add(file_path)
        loader = ThumbnailLoader(file_path, self.item_size)
        loader.signals.result.connect(self.on_thumbnail_loaded)
        self._active_workers[file_path] = loader
        self.thread_pool.start(loader)

    def on_thumbnail_loaded(self, file_path, pixmap, is_final):
        #  只有收到「最終訊號」，才把任務從活躍佇列中移除
        if is_final:
            if file_path in self._active_workers:
                del self._active_workers[file_path]
            if file_path in self._loading_set:
                self._loading_set.remove(file_path)

        if not pixmap.isNull():
            # 無論是 L2 還是 L3，都存入快取 (L3 來了會直接覆蓋 L2，完美)
            self._thumbnail_cache[file_path] = pixmap
            if len(self._thumbnail_cache) > self.CACHE_SIZE:
                self._thumbnail_cache.popitem(last=False)

            row = getattr(self, 'path_to_row', {}).get(file_path)
            if row is not None:
                self._pending_updates.add(row)
                if not self.update_timer.isActive():
                    self.update_timer.start()

    def _flush_updates(self):
        if not self._pending_updates:
            return
        min_row = min(self._pending_updates)
        max_row = max(self._pending_updates)
        start_idx = self.index(min_row, 0)
        end_idx = self.index(max_row, 0)
        self.dataChanged.emit(start_idx, end_idx, [Qt.ItemDataRole.DecorationRole])
        self._pending_updates.clear()

    def flags(self, index):
        # 取得預設的 flags (通常包含 Selectable 和 Enabled)
        default_flags = super().flags(index) 
        
        if index.isValid():
            #  關鍵：必須告訴 Qt 這個項目「允許被拖拽」
            return default_flags | Qt.ItemFlag.ItemIsDragEnabled
            
        return default_flags

class ImageDelegate(QStyledItemDelegate):
    """負責繪製列表中的每一個項目 (支援動態調整大小)"""
    def __init__(self, card_size, thumb_height, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.padding = 10
        self.radius = 8
        self.font_name = QFont("Segoe UI", 10, QFont.Weight.Medium)
        self.font_score = QFont("Consolas", 9)
        self.font_tag = QFont("Segoe UI", 8, QFont.Weight.Bold)

        self.fm_name = QFontMetrics(self.font_name)
        
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

        # ── 取得主題顏色 ──
        if hasattr(self.main_window, 'theme_manager'):
            colors = self.main_window.theme_manager.current_colors
        else:
            colors = {}

        # ── 狀態旗標 ──
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover    = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # ── 背景色（hover 時換底色，不影響邊框） ──
        bg_color   = QColor(colors.get("bg_card", "#2b2b2b"))
        text_color = QColor(colors.get("text_main", "#ffffff"))
        if text_color.name().lower() == "#ffffff":
            text_color = QColor("#e0e0e0")
        if is_hover and not is_selected:
            bg_color = QColor(colors.get("bg_hover", "#383838"))

        # 1. 只填充背景，不畫邊框（邊框統一在最後繪製）
        path = QPainterPath()
        path.addRoundedRect(QRectF(card_rect), self.radius, self.radius)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
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
            x_off = (img_rect.width() - pixmap.width()) / 2
            y_off = (img_rect.height() - pixmap.height()) / 2
            
            painter.drawPixmap(
                img_rect.left() + int(x_off), 
                img_rect.top() + int(y_off), 
                pixmap
            )
        else:
            min_dim = min(img_rect.width(), img_rect.height())
            icon_size = max(48, int(min_dim * 0.60))
            
            icon_rect = QRect(0, 0, icon_size, icon_size)
            icon_rect.moveCenter(img_rect.center())
            
            painter.setOpacity(0.2)
            self.placeholder_icon.paint(painter, icon_rect)
            painter.setOpacity(1.0)

        painter.setClipping(False)

        # 3. 繪製文字
        painter.setFont(self.font_name)
        painter.setPen(text_color)
        elided_name = item.get_elided_name(self.fm_name, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

        # 4. 繪製分數
        painter.setFont(self.font_score)
        
        if item.score_val > 0.0001:
            if item.score_val > 0.3:
                score_color = colors.get("primary", "#60cdff")
            else:
                score_color = colors.get("text_muted", "#999999")
                
            painter.setPen(QColor(score_color))
            painter.drawText(score_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.score_str)

        # 5. 右下角並列標籤 (PINNED + TEXT)
        tag_h = 16
        tag_y = score_rect.top() + 2
        tag_gap = 4
        pin_tag_w = 45
        ocr_tag_w = 36
        right_edge = card_rect.right() - self.padding

        painter.setFont(self.font_tag)
        painter.setPen(Qt.PenStyle.NoPen)

        if item.is_pinned and item.is_ocr_match:
            # 兩者並列：[PINNED] [TEXT]，TEXT 靠右
            ocr_x = right_edge - ocr_tag_w
            pin_x = ocr_x - tag_gap - pin_tag_w

            pin_rect = QRect(pin_x, tag_y, pin_tag_w, tag_h)
            ocr_rect = QRect(ocr_x, tag_y, ocr_tag_w, tag_h)

            pin_bg = colors.get("accent", colors.get("primary", "#60cdff"))
            painter.setBrush(QBrush(QColor(pin_bg)))
            painter.drawRoundedRect(pin_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(pin_rect, Qt.AlignmentFlag.AlignCenter, "PIN")

            ocr_bg = colors.get("text_success", "#4caf50")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(ocr_bg)))
            painter.drawRoundedRect(ocr_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(ocr_rect, Qt.AlignmentFlag.AlignCenter, "TEXT")

        elif item.is_pinned:
            pin_rect = QRect(right_edge - pin_tag_w, tag_y, pin_tag_w, tag_h)
            pin_bg = colors.get("accent", colors.get("primary", "#60cdff"))
            painter.setBrush(QBrush(QColor(pin_bg)))
            painter.drawRoundedRect(pin_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(pin_rect, Qt.AlignmentFlag.AlignCenter, "PIN")

        elif item.is_ocr_match:
            ocr_rect = QRect(right_edge - ocr_tag_w, tag_y, ocr_tag_w, tag_h)
            ocr_bg = colors.get("text_success", "#4caf50")
            painter.setBrush(QBrush(QColor(ocr_bg)))
            painter.drawRoundedRect(ocr_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(ocr_rect, Qt.AlignmentFlag.AlignCenter, "TEXT")

        # ── 邊框層（由內而外疊加，選取框永遠最頂層） ──
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # 層 A：預設細邊框或 hover 邊框（無任何特殊狀態時）
        if not item.is_pinned and not item.is_ocr_match and not is_selected:
            border_c = colors.get("primary_hover", "#7ce0ff") if is_hover else colors.get("border_main", "#3e3e3e")
            painter.setPen(QPen(QColor(border_c), 1))
            painter.drawPath(path)

        # 層 B：OCR 綠色虛線環
        # 畫在比 card_rect 外擴 2px 的路徑，確保與釘選藍色(Layer C)完全不重疊，兩層同時可見
        if item.is_ocr_match:
            ocr_path = QPainterPath()
            ocr_path.addRoundedRect(
                QRectF(card_rect.adjusted(-2, -2, 2, 2)),
                self.radius + 1, self.radius + 1,
            )
            pen_ocr = QPen(QColor(colors.get("text_success", "#4caf50")), 1.5, Qt.PenStyle.DashLine)
            pen_ocr.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_ocr)
            painter.drawPath(ocr_path)

        # 層 C：釘選藍色實線（2px，畫在 card_rect 位置）
        if item.is_pinned:
            pen_pin = QPen(
                QColor(colors.get("accent", colors.get("primary", "#60cdff"))),
                2, Qt.PenStyle.SolidLine,
            )
            pen_pin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_pin)
            painter.drawPath(path)

        # 層 D：WASD / 滑鼠選取框（3px，永遠最頂層；比釘選線粗一格，差異明顯）
        if is_selected:
            pen_sel = QPen(QColor(colors.get("primary", "#60cdff")), 3, Qt.PenStyle.SolidLine)
            pen_sel.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_sel)
            painter.drawPath(path)

        painter.restore()

from PyQt6.QtCore import QMimeData, QUrl, Qt, QPoint
from PyQt6.QtGui import QDrag, QImage, QPixmap, QPainter, QBrush, QColor, QPen, QFont
from PyQt6.QtWidgets import QListView, QAbstractItemView

class GalleryListView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        #  啟動進階多選與框選模式
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True) # 啟用半透明框選遮罩
        self.setDragEnabled(True)          # 啟用拖拽
        self.setAcceptDrops(False)         # 畫廊本身不接收外部檔案丟入
        #  [新增] 明確宣告這裡「只允許拖出，不允許拖入」
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def startDrag(self, supportedActions):
        """當系統偵測到滑鼠按住並移動超過閥值(約10px)時，會自動觸發此函式"""
        
        selected_indexes = self.selectionModel().selectedIndexes()
        if not selected_indexes:
            return

        # 1. 準備封裝資料 (MIME Data)
        drag = QDrag(self)
        mime_data = QMimeData()
        urls = []

        # 收集所有選中圖片的實體路徑
        for index in selected_indexes:
            item = index.data(Qt.ItemDataRole.UserRole)
            if item and item.path:
                urls.append(QUrl.fromLocalFile(item.path))

        mime_data.setUrls(urls) # 封裝路徑 (支援拖入資料夾、瀏覽器)

        # 2. 根據單選/多選決定視覺鬼影 (Ghost Image) 與附加資料
        if len(selected_indexes) == 1:
            # --- 【單張拖拽】 ---
            item = selected_indexes[0].data(Qt.ItemDataRole.UserRole)
            

            # 製作半透明縮圖鬼影
            pixmap = selected_indexes[0].data(Qt.ItemDataRole.DecorationRole)
            if pixmap and not pixmap.isNull():
                ghost = QPixmap(pixmap.size())
                ghost.fill(Qt.GlobalColor.transparent)
                painter = QPainter(ghost)
                painter.setOpacity(0.7) # 70% 透明度
                painter.drawPixmap(0, 0, pixmap)
                painter.end()
                
                # 將鬼影縮小，避免擋住視線
                scaled_ghost = ghost.scaledToWidth(120, Qt.TransformationMode.SmoothTransformation)
                drag.setPixmap(scaled_ghost)
                drag.setHotSpot(QPoint(scaled_ghost.width() // 2, scaled_ghost.height() // 2))

        else:
            # --- 【多張拖拽】 ---
            # 製作「代表多檔案的通用圖示 + 數量標籤」
            badge_size = 100
            ghost = QPixmap(badge_size, badge_size)
            ghost.fill(Qt.GlobalColor.transparent)
            painter = QPainter(ghost)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 繪製半透明深色底框
            painter.setBrush(QBrush(QColor(40, 40, 40, 220)))
            painter.setPen(QPen(QColor("#60cdff"), 2)) # 主題藍色邊框
            painter.drawRoundedRect(5, 5, badge_size-10, badge_size-10, 10, 10)

            # 繪製數量文字
            painter.setPen(QColor("#ffffff"))
            font = QFont("Segoe UI", 20, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(ghost.rect(), Qt.AlignmentFlag.AlignCenter, f"x{len(selected_indexes)}")
            painter.end()
            
            drag.setPixmap(ghost)
            drag.setHotSpot(QPoint(badge_size // 2, badge_size // 2))

        # 3. 綁定資料並強制執行「複製 (Copy)」操作
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

# ==========================================
#  引擎核心
# ==========================================
class ImageSearchEngine:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.device = "dml" if 'DmlExecutionProvider' in ort.get_available_providers() else "cpu"
        self.is_ready = False
        self.model = None
        self.preprocess = None
        self.tokenizer = None
        
        # [修正] 預先定義 stored_embeddings
        self.stored_embeddings = None 
        self.data_store = []

        self.shared_ocr_engines = {}

        # 1. 初始化資料庫
        print(f"[Engine] Initializing Database...")
        if os.path.exists(self.config.db_path):
            self.load_data_from_db()
        else:
            print(f"[Error] Database file not found: {self.config.db_path}")

    # ==========================================
    # 在 ImageSearchEngine 類別中，載入資料庫向量之後加入這段
    # ==========================================
    def build_faiss_index(self, embeddings_matrix):
        """
        將 Numpy 矩陣轉換為 FAISS 光速索引引擎
        :param embeddings_matrix: shape 為 (N, 1024) 的 Numpy 陣列
        """
        if len(embeddings_matrix) == 0:
            self.faiss_index = None
            return

        dimension = embeddings_matrix.shape[1]
    
        #  由於您的 CLIP 向量在 indexer.py 中已經做過 L2 歸一化，
        # 這裡直接使用 IP (Inner Product 內積)，它在數學上等同於 Cosine Similarity！
    
        # 方案 A：暴力極速版 (適合 10 萬張以下，無損精度)
        self.faiss_index = faiss.IndexFlatIP(dimension)
    
        # 方案 B：HNSW 圖形演算法版 (適合百萬張以上，O(log N) 狂暴速度)
        # self.faiss_index = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)
    
        # 將所有向量加入引擎 (必須是 float32 格式)
        self.faiss_index.add(embeddings_matrix.astype(np.float32))
        print(f"[FAISS] 成功建立 {self.faiss_index.ntotal} 筆向量索引！")

    # ==========================================
    #  [新增] 統一的 WAL 資料庫連線產生器
    # ==========================================
    def get_db_conn(self):
        """建立具備 WAL 模式與高容忍度的資料庫連線"""
        # timeout=15.0 表示如果硬碟真的卡住，前端願意等 15 秒而不直接報錯當機
        conn = sqlite3.connect(self.config.db_path, timeout=15.0)
        # 啟動 WAL 模式 (讀寫分離，前端讀取不阻塞後台寫入)
        conn.execute("PRAGMA journal_mode=WAL;")
        # 設定為 NORMAL，大幅減少硬碟同步等待時間，提升 10 倍以上寫入速度
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def load_ai_models(self):
        try:
            model_name = self.config.get("model_name")
            pretrained = self.config.get("pretrained")

            print(f"[Engine] Loading ONNX CLIP models...")
            self.preprocess = NumpyPreprocess(size=224)

            self.is_hf_tokenizer = ("roberta" in model_name.lower() or "xlm" in model_name.lower())
            
            # ==========================================
            # [離線化修改] 強制讀取本地目錄，完全阻斷 Hugging Face 連線
            # ==========================================
            # [關鍵修改] Tokenizer 改用 huggingface 輕量版
            from transformers import AutoTokenizer, CLIPTokenizer
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
            if self.is_hf_tokenizer:
                tok_path = os.path.join(base_dir, "models", "tokenizers", "xlm-roberta")
                self.tokenizer = AutoTokenizer.from_pretrained(tok_path, local_files_only=True)
                
                # ==========================================
                #  [關鍵修復] 手動補上 pad_token，解決離線載入報錯
                # ==========================================
                if self.tokenizer.pad_token is None:
                    # 如果沒有 pad_token，就借用 eos_token 來當作填充符號
                    self.tokenizer.pad_token = self.tokenizer.eos_token or "<pad>"
                    
            else:
                tok_path = os.path.join(base_dir, "models", "tokenizers", "openai-clip")
                self.tokenizer = CLIPTokenizer.from_pretrained(tok_path, local_files_only=True)
                
                # OpenAI CLIP 通常也會需要確認 pad_token
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token or "<|endoftext|>"

            # 載入 ONNX Sessions
            img_onnx_path = os.path.join(base_dir, "models", "onnx_clip", f"{model_name}_image.onnx")
            txt_onnx_path = os.path.join(base_dir, "models", "onnx_clip", f"{model_name}_text.onnx")
            
            providers = ['DmlExecutionProvider', 'CPUExecutionProvider'] if (self.device == 'dml') else ['CPUExecutionProvider']
            self.clip_image_session = ort.InferenceSession(img_onnx_path, providers=providers)
            self.clip_text_session = ort.InferenceSession(txt_onnx_path, providers=providers)
            
            self.is_ready = True
            print(f"[Engine] ONNX AI Models Loaded. System is fully ready.")
            
        except Exception as e:
            print(f"[Error] AI Model loading failed: {e}")

    def get_all_images_sorted(self):
        """
        [高效能] 取得資料庫中所有圖片，並依時間 (新->舊) 排序。
        用於冷啟動時的瀑布流顯示。
        """
        #  [終極防呆：取得當下的指標快照，防止被雙緩衝覆蓋]
        current_data = getattr(self, 'data_store', [])
        if not current_data:
            return []
        
        print(f"[Engine] Sorting {len(current_data)} images by date...")
        
        # 1. 使用 Python 內建 Timsort 進行快速排序 (mtime 大的排前面)
        sorted_data = sorted(current_data, key=lambda x: x["mtime"], reverse=True)
        
        # 2. 轉換為 UI 需要的格式
        results = []
        for item in sorted_data:
            results.append({
                "score": 0.0, "clip_score": 0.0, "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                "path": item["path"], "filename": item["filename"],
                "mtime": item.get("mtime", 0),
                "width": item.get("width", 0),   
                "height": item.get("height", 0)  
            })
        return self._merge_pinned(results)

    def load_data_from_db(self):
        print(f"[Engine] Connecting to database: {self.config.db_path}...")
        conn = self.get_db_conn()
        cursor = conn.cursor()
        try:
            current_model = self.config.get("model_name")
            
            #  [效能封頂] 拔除了肥大的 JSON 組合，只保留純文字 ocr_text 用於搜尋
            cursor.execute("""
                SELECT f.file_path, e.embedding, f.mtime, f.width, f.height, 
                       GROUP_CONCAT(o.ocr_text, ' ')
                FROM files f
                JOIN embeddings e ON f.id = e.file_id
                LEFT JOIN ocr_results o ON f.id = o.file_id
                WHERE e.model_name = ?
                GROUP BY f.id
            """, (current_model,))
            rows = cursor.fetchall()
            
            temp_data_store = [] 
            temp_embeddings_list = []
            temp_path_map = {}
            
            #  [效能封頂] 迴圈內不再做任何 json.loads()，啟動速度直接起飛！
            for path, blob, mtime, width, height, combined_text in rows:
                if not os.path.exists(path): continue 
                
                emb_array = np.frombuffer(blob, dtype=np.float32)
                temp_embeddings_list.append(emb_array)
                text_content = combined_text if combined_text else ""
                
                temp_data_store.append({
                    "path": path,
                    "filename": os.path.basename(path),
                    "ocr_text": text_content.lower(),
                    "mtime": mtime,
                    "width": width if width else 0,
                    "height": height if height else 0
                })
                
                #  [核心魔法] 將「正規化後的路徑」作為 Key，對應到陣列的 Index
                norm_path = os.path.normpath(path)
                temp_path_map[norm_path] = len(temp_data_store) - 1
            
            if temp_data_store and temp_embeddings_list:
                temp_emb_matrix = np.stack(temp_embeddings_list)
                self.stored_embeddings = temp_emb_matrix
                self.data_store = temp_data_store
                self.path_map = temp_path_map
                self.build_faiss_index(temp_emb_matrix)
                self._reload_pinned_cache()
                print(f"[Engine] Loaded {len(self.data_store)} records for model '{current_model}'.")
            else:
                self.stored_embeddings = None
                self.data_store = []
                self.path_map = {}
                self.pinned_paths = set()
                
        except sqlite3.Error as e:
            print(f"[Error] Database query failed: {e}")
        finally:
            if conn: conn.close()

    # ==========================================
    # 釘選 (Pinning) 功能
    # ==========================================
    def _reload_pinned_cache(self):
        """從 pinned 資料表重新載入所有釘選路徑到記憶體集合。"""
        self.pinned_paths = set()
        if not os.path.exists(self.config.db_path):
            return
        try:
            conn = self.get_db_conn()
            rows = conn.execute("SELECT file_path FROM pinned").fetchall()
            conn.close()
            for (fp,) in rows:
                self.pinned_paths.add(os.path.normpath(fp))
        except Exception as e:
            print(f"[Engine] _reload_pinned_cache error: {e}")

    def toggle_pin(self, file_path: str) -> bool:
        """切換圖片釘選狀態。回傳 True 表示現在已釘選，False 表示已取消。"""
        if not hasattr(self, 'pinned_paths'):
            self._reload_pinned_cache()
        norm = os.path.normpath(file_path)
        try:
            conn = self.get_db_conn()
            if norm in self.pinned_paths:
                conn.execute("DELETE FROM pinned WHERE file_path = ?", (file_path,))
                conn.commit()
                conn.close()
                self.pinned_paths.discard(norm)
                return False
            else:
                conn.execute("INSERT OR IGNORE INTO pinned (file_path) VALUES (?)", (file_path,))
                conn.commit()
                conn.close()
                self.pinned_paths.add(norm)
                return True
        except Exception as e:
            print(f"[Engine] toggle_pin error: {e}")
            return norm in self.pinned_paths

    def is_pinned(self, file_path: str) -> bool:
        """回傳指定路徑是否處於釘選狀態。"""
        if not hasattr(self, 'pinned_paths'):
            self._reload_pinned_cache()
        return os.path.normpath(file_path) in self.pinned_paths

    def _get_pinned_results(self) -> list:
        """將所有釘選圖片轉換為搜尋結果格式（無視資料夾範圍）。"""
        if not hasattr(self, 'pinned_paths') or not self.pinned_paths:
            return []
        results = []
        for item in self.data_store:
            if os.path.normpath(item["path"]) in self.pinned_paths:
                results.append({
                    "score": 0.0, "clip_score": 0.0, "ocr_bonus": 0.0, "name_bonus": 0.0,
                    "is_ocr_match": False, "is_pinned": True,
                    "path": item["path"], "filename": item["filename"],
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                })
        return results

    def _merge_pinned(self, results: list) -> list:
        """將釘選圖片置頂，與搜尋結果合併去重。"""
        pinned = self._get_pinned_results()
        if not pinned:
            return results
        pinned_paths_set = {r["path"] for r in pinned}
        deduped = [r for r in results if r["path"] not in pinned_paths_set]
        return pinned + deduped

    def get_folder_stats(self):
        if not os.path.exists(self.config.db_path): return []
        try:
            conn = self.get_db_conn()
            cursor = conn.cursor()
            # [關鍵修復 2] 根據當前模型去 model_stats 抓取統計
            current_model = self.config.get("model_name")
            cursor.execute("SELECT folder_path, image_count FROM model_stats WHERE model_name = ? ORDER BY folder_path ASC", (current_model,))
            stats = cursor.fetchall()
            conn.close()
            return stats
        except Exception as e:
            print(f"[Error] Failed to get stats: {e}"); return []

    def remove_folder_data(self, folder_path: str) -> bool:
        """
        原子化移除資料夾：同時清理資料庫記錄與記憶體索引。
        :param folder_path: 要移除的資料夾路徑（需與 DB 中的 folder_path 完全一致）
        :return: True 表示成功
        """
        norm_folder = os.path.normpath(folder_path)
        try:
            # --- 1. 資料庫清理（foreign_keys 保護 cascade） ---
            conn = self.get_db_conn()
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("DELETE FROM files WHERE folder_path = ?", (folder_path,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Engine] remove_folder_data DB error: {e}")
            return False

        # --- 2. 記憶體索引同步 ---
        if not self.data_store:
            return True

        # 找出所有屬於此資料夾的索引位置
        keep_mask = [
            os.path.normpath(item["path"]) != norm_folder and
            not os.path.normpath(item["path"]).startswith(norm_folder + os.sep)
            for item in self.data_store
        ]

        new_data_store = [item for item, keep in zip(self.data_store, keep_mask) if keep]
        keep_indices = [i for i, keep in enumerate(keep_mask) if keep]

        if len(new_data_store) == len(self.data_store):
            # 沒有任何項目被移除（路徑可能不符），仍視為成功
            return True

        # 重建 path_map（新索引號與舊不同，需完整重建）
        new_path_map = {}
        for new_idx, item in enumerate(new_data_store):
            new_path_map[os.path.normpath(item["path"])] = new_idx

        # 重建 stored_embeddings 與 FAISS
        if self.stored_embeddings is not None and len(keep_indices) > 0:
            new_emb = self.stored_embeddings[keep_indices]
            self.stored_embeddings = new_emb
            self.build_faiss_index(new_emb)
        else:
            self.stored_embeddings = None
            self.faiss_index = None

        self.data_store = new_data_store
        self.path_map = new_path_map
        print(f"[Engine] remove_folder_data: removed folder '{folder_path}', "
              f"{len(self.data_store)} records remain.")
        return True

    def rename_file(self, old_path, new_name):
        folder = os.path.dirname(old_path); new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path): return False, "Target filename already exists."
        try:
            os.rename(old_path, new_path)
            conn = self.get_db_conn(); cursor = conn.cursor()
            # [關鍵修復 3] 改為更新 files 表
            cursor.execute("UPDATE files SET file_path = ?, filename = ? WHERE file_path = ?", (new_path, new_name, old_path))
            conn.commit(); conn.close()
            for item in self.data_store:
                if item["path"] == old_path:
                    item["path"] = new_path; item["filename"] = new_name; break
                
            #  [新增] 同步更新 Hash Map 字典，維持 O(1) 搜尋的正確性
            if hasattr(self, 'path_map'):
                norm_old = os.path.normpath(old_path)
                norm_new = os.path.normpath(new_path)
                if norm_old in self.path_map:
                    idx = self.path_map.pop(norm_old) # 抽出舊的
                    self.path_map[norm_new] = idx     # 塞入新的
                    
            return True, new_path
        except Exception as e: return False, str(e)

    #  [新增] folder_path 參數
    def search_hybrid(self, query, top_k=50, use_ocr=True, weight_config=None, folder_path=None):
        current_embeddings = self.stored_embeddings
        current_data = self.data_store

        #  防呆檢查：確保 FAISS 引擎已經啟動
        if not self.is_ready or current_embeddings is None or not hasattr(self, 'faiss_index'): 
            return [] 
            
        valid_indices = None
        if folder_path and folder_path != "ALL":
            norm_target = os.path.normpath(folder_path)
            valid_indices = [
                i for i, item in enumerate(current_data) 
                if os.path.normpath(item["path"]).startswith(norm_target)
            ]
            if not valid_indices:
                return []

        query_lower = query.lower()
        try:
            if hasattr(self, 'last_text_query') and self.last_text_query == query and hasattr(self, 'last_text_features'):
                text_features = self.last_text_features
            else:
                inputs = self.tokenizer([query], padding="max_length", max_length=77, truncation=True, return_tensors="np")
                text_tokens = inputs.input_ids.astype(np.int64)
                input_name = self.clip_text_session.get_inputs()[0].name
                text_features = self.clip_text_session.run(None, {input_name: text_tokens})[0]
                text_features = text_features / np.linalg.norm(text_features, axis=-1, keepdims=True)
                
                self.last_text_query = query
                self.last_text_features = text_features
            
            query_vector = text_features.astype(np.float32)
            if len(query_vector.shape) == 1:
                query_vector = np.expand_dims(query_vector, axis=0)

            # ==========================================
            #  [關鍵修復 2] 動態發動 FAISS (支援「完全展開」)
            # 確保最少抓 1000 張當作文字緩衝，但如果 UI 選擇 All (top_k=100000)，就水門全開！
            # ==========================================
            k_results = min(max(1000, top_k), len(current_data))
            top_scores_matrix, top_indices_matrix = self.faiss_index.search(query_vector, k_results)
            top_scores = top_scores_matrix[0]
            top_indices = top_indices_matrix[0]
            
            # 建立 CLIP 分數對照表
            clip_score_map = {int(idx): float(score) for idx, score in zip(top_indices, top_scores)}
            
        except Exception as e:
            print(f"CLIP Search Error: {e}")
            clip_score_map = {}
            top_indices = []

        # ==========================================
        #  混合候選名單篩選 (Hybrid Selection)
        # ==========================================
        candidate_set = set(top_indices)

        # 光速篩選出文字或檔名命中的項目 (把它們也加入候選名單，保證文字搜尋絕對不漏接！)
        if query_lower:
            text_matched_indices = [
                i for i, item in enumerate(current_data)
                if (use_ocr and query_lower in item["ocr_text"]) or (query_lower in item["filename"].lower())
            ]
            candidate_set.update(text_matched_indices)

        # 如果有資料夾過濾，剔除不在該資料夾的圖片
        if valid_indices is not None:
            candidate_set = candidate_set.intersection(set(valid_indices))

        # ==========================================
        #  執行計分迴圈 (只針對幾千張的候選名單，不跑十萬張！)
        # ==========================================
        if weight_config is None:
            weight_config = {"mode": "multiply", "clip_w": 1.0, "ocr_w": 1.0, "name_w": 0.4, "thresh_mode": "auto", "thresh_val": 0.15}
            
        mode = weight_config.get("mode", "multiply")
        clip_w = weight_config.get("clip_w", 1.0)
        ocr_w = weight_config.get("ocr_w", 1.0)
        name_w = weight_config.get("name_w", 0.4)
        thresh_mode = weight_config.get("thresh_mode", "auto")
        thresh_val = weight_config.get("thresh_val", 0.15)

        raw_results = []
        max_score = 0.0

        for original_idx in candidate_set:
            item = current_data[original_idx]
            
            # 從對照表拿 CLIP 分數，沒在 Top 1000 裡的就當作 0 分
            clip_score = clip_score_map.get(original_idx, 0.0)
            
            has_ocr = use_ocr and (query_lower in item["ocr_text"])
            has_name = query_lower in item["filename"].lower()
            
            ocr_bonus = 0.0
            name_bonus = 0.0
            
            #  修復: 只要有文字命中，或者視覺分數及格，就給予加分！
            if clip_score >= 0.08 or has_ocr or has_name:
                if mode == "add":
                    ocr_bonus = (ocr_w / 2.0) if has_ocr else 0.0 
                    name_bonus = (name_w / 2.0) if has_name else 0.0
                else:
                    ocr_bonus = (0.5 * ocr_w) if has_ocr else 0.0
                    name_bonus = (0.5 * name_w) if has_name else 0.0
            
            if mode == "add":
                final_score = clip_score + ocr_bonus + name_bonus
            else:
                final_score = (clip_score * clip_w) + ocr_bonus + name_bonus
                
            if final_score > max_score:
                max_score = final_score
                
            raw_results.append({
                "score": final_score, "clip_score": clip_score, "ocr_bonus": ocr_bonus, "name_bonus": name_bonus,
                "is_ocr_match": has_ocr, "path": item["path"], "filename": item["filename"],
                "mtime": item.get("mtime", 0),
                "width": item.get("width", 0),  
                "height": item.get("height", 0) 
            })

        if thresh_mode == "auto":
            actual_thresh = max_score * 0.5
        else:
            actual_thresh = thresh_val

        results = [r for r in raw_results if r["score"] >= actual_thresh]
        results.sort(key=lambda x: x["score"], reverse=True)
        return self._merge_pinned(results[:top_k])

    #  [修改] 新增 folder_path 參數 (上一階段已加)，並導入「O(1) 快取命中」邏輯
    def search_image(self, image_path, top_k=50, folder_path=None):
        current_embeddings = self.stored_embeddings
        current_data = self.data_store

        # 防呆檢查：確保 FAISS 引擎已經啟動
        if not self.is_ready or current_embeddings is None or not hasattr(self, 'faiss_index'): 
            return []
            
        try:
            query_vector = None
            
            # ==========================================
            #  [效能封頂] 疑問 1 解決方案：記憶體 O(1) 特徵直接提取
            # ==========================================
            # 1. 嘗試在字典中瞬間尋找這張圖片
            target_idx = None
            norm_target_path = os.path.normpath(image_path)
            
            if hasattr(self, 'path_map') and norm_target_path in self.path_map:
                target_idx = self.path_map[norm_target_path]
                    
            if target_idx is not None:
                # 2. 如果找到了！直接從記憶體把算好的向量抽出來 (0 毫秒)
                query_vector = np.expand_dims(current_embeddings[target_idx], axis=0)
            else:
                # 3. 如果找不到 (例如未來支援拖入外部圖片)，才啟動 ONNX 消耗算力
                #print(f"[Engine] 以圖搜圖：外部圖片，啟動 GPU 推論...")
                image = Image.open(image_path).convert('RGB')
                processed_image = np.expand_dims(self.preprocess(image), axis=0)
                
                input_name = self.clip_image_session.get_inputs()[0].name
                image_features = self.clip_image_session.run(None, {input_name: processed_image})[0]
                image_features = image_features / np.linalg.norm(image_features, axis=-1, keepdims=True)
                
                query_vector = image_features.astype(np.float32)

            # ==========================================
            #  發動 FAISS 以圖搜圖 (超額抓取與範圍過濾)
            # ==========================================
            # 為了確保「範圍過濾」後還有足夠的圖片，我們先跟 FAISS 要一大把
            fetch_limit = min(max(2000, top_k), len(current_data))
            top_scores_matrix, top_indices_matrix = self.faiss_index.search(query_vector, fetch_limit)
            
            top_scores = top_scores_matrix[0]
            top_indices = top_indices_matrix[0]
            
            # 準備過濾條件
            norm_target = os.path.normpath(folder_path) if (folder_path and folder_path != "ALL") else None
            
            results = []
            for i in range(fetch_limit):
                idx = top_indices[i]
                item = current_data[idx]
                
                # 如果有指定資料夾，且圖片不在該資料夾內，直接丟棄！
                if norm_target and not os.path.normpath(item["path"]).startswith(norm_target):
                    continue
                    
                score = top_scores[i]
                results.append({
                    "score": float(score), "clip_score": float(score), "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                    "path": item["path"], "filename": item["filename"],  
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),   
                    "height": item.get("height", 0)  
                })
                
                # 收集滿目標數量就可以提早收工
                if len(results) >= top_k:
                    break
                    
            return self._merge_pinned(results)
        except Exception as e:
            print(f"[Error] Image search failed: {e}"); return []
        
    def get_ocr_data_by_path(self, file_path):
        """ [新增] 懶加載通道：只有在預覽時，才去資料庫把這張圖片的座標 JSON 撈出來"""
        conn = self.get_db_conn()
        cursor = conn.cursor()
        ocr_boxes = []
        try:
            cursor.execute("""
                SELECT o.lang, o.ocr_data 
                FROM ocr_results o
                JOIN files f ON o.file_id = f.id
                WHERE f.file_path = ?
            """, (file_path,))
            
            rows = cursor.fetchall()
            for lang, data_json in rows:
                if data_json and data_json != "[]" and data_json != "[NULL]":
                    try:
                        parsed_data = json.loads(data_json)
                        if isinstance(parsed_data, list):
                            for item in parsed_data:
                                item["lang"] = lang
                                ocr_boxes.append(item)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Engine] Lazy load OCR data error: {e}")
        finally:
            conn.close()
        return ocr_boxes
    
    def get_text_vector(self, text):
        """瞬間產生文字的 1024 維特徵 (約 0.05 秒)"""
        if not self.is_ready or not hasattr(self, 'clip_text_session'): return None
        inputs = self.tokenizer([text], padding="max_length", max_length=77, truncation=True, return_tensors="np")
        text_tokens = inputs.input_ids.astype(np.int64)
        input_name = self.clip_text_session.get_inputs()[0].name
        text_features = self.clip_text_session.run(None, {input_name: text_tokens})[0]
        return text_features[0] / np.linalg.norm(text_features[0], axis=-1, keepdims=True)

    # ==========================================
    #  [修復版] 多模態特徵組合搜尋 (Vector Arithmetic)
    # ==========================================
    def search_multi_vector(self, pos_features, neg_features, top_k=50, folder_path=None):
        if not self.is_ready or self.stored_embeddings is None: return []

        def get_vec(feat):
            if feat.vector is not None: return feat.vector # 命中預熱快取！(0毫秒)
            if feat.type == 'image':
                norm_target_path = os.path.normpath(feat.data)
                if hasattr(self, 'path_map') and norm_target_path in self.path_map:
                    feat.vector = self.stored_embeddings[self.path_map[norm_target_path]]
                    return feat.vector
                try:
                    image = Image.open(feat.data).convert('RGB')
                    processed = np.expand_dims(self.preprocess(image), axis=0)
                    input_name = self.clip_image_session.get_inputs()[0].name
                    vec = self.clip_image_session.run(None, {input_name: processed})[0]
                    feat.vector = vec[0] / np.linalg.norm(vec[0], axis=-1, keepdims=True)
                    return feat.vector
                except: return None
            elif feat.type == 'text':
                feat.vector = self.get_text_vector(feat.data)
                return feat.vector

        pos_vecs = [v for f in pos_features if (v := get_vec(f)) is not None]
        neg_vecs = [v for f in neg_features if (v := get_vec(f)) is not None]
        if not pos_vecs and not neg_vecs: return []

        dim = self.stored_embeddings.shape[1]
        v_pos = np.mean(pos_vecs, axis=0) if pos_vecs else np.zeros(dim, dtype=np.float32)
        v_neg = np.mean(neg_vecs, axis=0) if neg_vecs else np.zeros(dim, dtype=np.float32)

        query_vector = v_pos - (0.6 * v_neg)
        if not pos_vecs and neg_vecs: query_vector = -v_neg 
        
        query_vector = np.expand_dims(query_vector, axis=0)
        query_vector = query_vector / np.linalg.norm(query_vector, axis=-1, keepdims=True)
        query_vector = query_vector.astype(np.float32)

        fetch_limit = min(max(2000, top_k), len(self.data_store))
        top_scores, top_indices = self.faiss_index.search(query_vector, fetch_limit)
        
        norm_folder = os.path.normpath(folder_path) if (folder_path and folder_path != "ALL") else None
        results = []
        for i in range(fetch_limit):
            idx = top_indices[0][i]
            item = self.data_store[idx]
            if norm_folder and not os.path.normpath(item["path"]).startswith(norm_folder): continue
                
            results.append({
                "score": float(top_scores[0][i]), "clip_score": float(top_scores[0][i]), "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                "path": item["path"], "filename": item["filename"], "mtime": item.get("mtime", 0),
                "width": item.get("width", 0), "height": item.get("height", 0)
            })
            if len(results) >= top_k: break
        return self._merge_pinned(results)
    
    # ==========================================
    #  [NEW] 虛擬資料夾 (Collections) 管理 API
    # ==========================================

    def _ensure_icon_column(self, conn):
        """冪等遷移：若 collections 尚無 icon 欄位則自動新增。"""
        cols = [row[1] for row in conn.execute("PRAGMA table_info(collections)").fetchall()]
        if "icon" not in cols:
            conn.execute("ALTER TABLE collections ADD COLUMN icon TEXT DEFAULT '🏷️'")
            conn.commit()

    def add_collection(self, name: str, icon: str = "🏷️") -> bool:
        """新增一個虛擬資料夾（含 icon 欄位自動遷移）。"""
        try:
            with self.get_db_conn() as conn:
                self._ensure_icon_column(conn)
                conn.execute(
                    "INSERT INTO collections (name, icon, created_at) VALUES (?, ?, ?)",
                    (name, icon, __import__("time").time()),
                )
            return True
        except Exception as e:
            print(f"[Engine] add_collection error: {e}")
            return False

    def get_collections(self) -> list:
        """回傳 [(id, name, icon, count), ...]，供 UI 載入。"""
        try:
            conn = self.get_db_conn()
            try:
                self._ensure_icon_column(conn)
                rows = conn.execute("""
                    SELECT c.id,
                           c.name,
                           COALESCE(c.icon, '🏷️') AS icon,
                           COUNT(ci.file_path)       AS cnt
                    FROM collections c
                    LEFT JOIN collection_items ci ON c.id = ci.collection_id
                    GROUP BY c.id
                    ORDER BY c.created_at ASC
                """).fetchall()
                return rows
            finally:
                conn.close()
        except Exception as e:
            print(f"[Engine] get_collections error: {e}")
            return []

    def remove_collection(self, collection_id: int) -> bool:
        """刪除虛擬資料夾，並清除所有關聯的 collection_items。"""
        try:
            conn = self.get_db_conn()
            try:
                # 啟用外鍵約束，確保 ON DELETE CASCADE 生效
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
                # 儀式防呆：若 PRAGMA 未生效，手動清理子表
                conn.execute("DELETE FROM collection_items WHERE collection_id = ?", (collection_id,))
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as e:
            print(f"[Engine] remove_collection error: {e}")
            return False

    def create_virtual_folder(self, name):
        """建立新的虛擬資料夾"""
        conn = self.get_db_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO collections (name, created_at) VALUES (?, ?)", (name, time.time()))
            conn.commit()
            return True, cursor.lastrowid
        except sqlite3.IntegrityError:
            return False, "該名稱已存在！"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def get_virtual_folders(self):
        """取得所有虛擬資料夾與其包含的圖片數量"""
        conn = self.get_db_conn()
        try:
            cursor = conn.cursor()
            # 瞬間算出每個虛擬資料夾裡面有幾張圖 (COUNT)
            cursor.execute("""
                SELECT c.id, c.name, COUNT(ci.file_path)
                FROM collections c
                LEFT JOIN collection_items ci ON c.id = ci.collection_id
                GROUP BY c.id
                ORDER BY c.created_at ASC
            """)
            return cursor.fetchall() # 回傳 [(id, name, count), ...]
        except Exception as e:
            print(f"[Engine] get_virtual_folders error: {e}")
            return []
        finally:
            conn.close()

    def add_to_virtual_folder(self, collection_id, file_paths):
        """將多張圖片加入虛擬資料夾 (支援拖曳寫入)"""
        if not file_paths: return False
        conn = self.get_db_conn()
        try:
            cursor = conn.cursor()
            # [防禦] 寫入前統一正規化路徑：os.path.normpath 修正斜線，os.path.abspath 統一大小寫磁碟代號
            normalized = [os.path.normpath(os.path.abspath(p)) for p in file_paths]
            data = [(collection_id, p) for p in normalized]
            # 使用 INSERT OR IGNORE，重複把同一張圖丟進同一個資料夾也不會報錯
            cursor.executemany("INSERT OR IGNORE INTO collection_items (collection_id, file_path) VALUES (?, ?)", data)
            conn.commit()
            return True
        except Exception as e:
            print(f"[Engine] add_to_virtual_folder error: {e}")
            return False
        finally:
            conn.close()
            
    def get_virtual_folder_images(self, collection_id):
        """取得特定虛擬資料夾內的所有圖片，用於顯示在畫廊"""
        conn = self.get_db_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT file_path FROM collection_items WHERE collection_id = ?", (collection_id,))
            raw_paths = [row[0] for row in cursor.fetchall()]
            # [防禦] 建立正規化查詢表：同時收錄原始路徑與正規化路徑，相容歷史舊資料
            paths = set()
            for p in raw_paths:
                paths.add(p)
                paths.add(os.path.normpath(os.path.abspath(p)))

            # 直接從 O(1) 的記憶體 data_store 中把圖片資訊抽出來！極度快速！
            results = []
            for item in self.data_store:
                item_path = item["path"]
                item_path_norm = os.path.normpath(os.path.abspath(item_path))
                if item_path in paths or item_path_norm in paths:
                    results.append({
                        "score": 0.0, "clip_score": 0.0, "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                        "path": item["path"], "filename": item["filename"],
                        "mtime": item.get("mtime", 0),
                        "width": item.get("width", 0),
                        "height": item.get("height", 0)
                    })
            # 按時間排序 (最新修改的排前面)
            results.sort(key=lambda x: x["mtime"], reverse=True)
            return results
        except Exception as e:
            print(f"[Engine] get_virtual_folder_images error: {e}")
            return []
        finally:
            conn.close()

from indexer import IndexerService # 確保引入

class IndexerWorker(QThread):
    """
    背景索引工作者
    階段 1: 掃描檔案 (Scan) -> 回報 scan_finished
    階段 2: 若有新檔案，執行 AI 處理 (Process) -> 回報 progress -> finished
    """
    status_update = pyqtSignal(str)       
    progress_update = pyqtSignal(int, int)
    scan_finished = pyqtSignal(int, int)  
    all_finished = pyqtSignal()           

    # [修改 1] 加入 main_window 參數，以取得主程式的 AI 模型
    def __init__(self, config, main_window):
        super().__init__()
        self.config = config
        self.main_window = main_window 
        self.service = IndexerService(
            db_path=config.db_path,
            model_name=config.get("model_name"),
            pretrained_name=config.get("pretrained"),
            use_gpu_ocr=config.get("use_gpu_ocr"),
            perf_config=config.get("performance", {})
        )
        #直接傳遞包含 use_ocr 屬性的完整字典列表！
        self.folders = config.get("source_folders")

    def run(self):
        # --- 階段 1: 智慧掃描 ---
        self.status_update.emit("Scanning for file changes...")
        try:
            # [修正] 接收新的回傳值
            files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map = self.service.scan_for_new_files(self.folders)
            self.scan_finished.emit(len(files_full) + len(files_emb_only) + len(files_ocr_only), deleted_count)
        except Exception as e:
            print(f"Scan Error: {e}"); self.status_update.emit("Scan failed."); return

        if not files_full and not files_emb_only and not files_ocr_only:
            self.status_update.emit("No new images found."); self.all_finished.emit(); return

        self.status_update.emit("Waiting for main AI Engine to initialize...")
        while not (self.main_window.engine and self.main_window.engine.is_ready): time.sleep(1) 

        total_tasks = len(files_full) + len(files_emb_only) + len(files_ocr_only)
        self.status_update.emit(f"Indexing {total_tasks} images...")
        
        # ==========================================
        # [新增] ETA 預估時間專用變數 (滑動視窗測速)
        # ==========================================
        last_update_time = [time.time()]
        last_current = [0]
        speed_history = []  # 儲存最近 5 次的「每張圖耗時(秒)」

        def callback(current, total, msg):
            now = time.time()
            elapsed = now - last_update_time[0]
            processed = current - last_current[0]
            
            # 1. 紀錄動態速度 (只保留最近 5 次，反映電腦當下真實效能)
            if processed > 0:
                sec_per_item = elapsed / processed
                speed_history.append(sec_per_item)
                if len(speed_history) > 5:
                    speed_history.pop(0) 
                    
            last_update_time[0] = now
            last_current[0] = current
            
            # 去除底層傳來字串結尾的 "..."
            clean_msg = msg.replace("...", "")
            
            # 2. 計算與格式化倒數時間
            if current < total:
                # 收集到至少 2 筆批次資料才開始算，避開模型剛啟動的極端延遲
                if len(speed_history) >= 2: 
                    avg_sec_per_item = sum(speed_history) / len(speed_history)
                    remaining_items = total - current
                    eta_seconds = int(remaining_items * avg_sec_per_item)
                    
                    if eta_seconds > 3600:
                        final_msg = f"{clean_msg} (剩餘時間: > 1 小時)"
                    else:
                        m, s = divmod(eta_seconds, 60)
                        final_msg = f"{clean_msg} (剩餘時間: {m:02d}:{s:02d})"
                else:
                    final_msg = f"{clean_msg} (計算估時中...)"
            else:
                # 3. 完美歸零視覺魔法：100% 瞬間切換文字，安撫寫入硬碟那 1 秒的等待感
                final_msg = f"{clean_msg} (儲存資料庫中...)"

            self.progress_update.emit(current, total)
            self.status_update.emit(final_msg)

        try:
            #  [關鍵修復] 以前這裡是 .engine.model (因為改版變成 None 了)
            # 現在明確指定借用主程式的 clip_image_session！
            shared_model = self.main_window.engine.clip_image_session
            shared_preprocess = self.main_window.engine.preprocess

            shared_ocr_engines = self.main_window.engine.shared_ocr_engines
            
            # [修正] 傳入雙軌參數與 mapping
            self.service.run_ai_processing(
                files_full, files_emb_only, files_ocr_only, folder_ocr_map,
                progress_callback=callback, shared_model=shared_model, shared_preprocess=shared_preprocess,
                shared_ocr_engines=shared_ocr_engines
            )
            self.status_update.emit("Indexing completed."); self.all_finished.emit()
        except Exception as e:
            print(f"Indexing Error: {e}"); self.status_update.emit("Indexing Error.")

class SearchWorker(QThread):
    batch_ready = pyqtSignal(list) 
    finished_search = pyqtSignal(float, int)
    
    def __init__(self, engine, query, top_k, search_mode="text", use_ocr=True, weight_config=None, folder_path=None): 
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.search_mode = search_mode
        self.use_ocr = use_ocr
        self.weight_config = weight_config
        self.folder_path = folder_path

    def run(self):
        start_time = time.time()
        if self.search_mode == "image":
            raw_results = self.engine.search_image(self.query, self.top_k, folder_path=self.folder_path)
        elif self.search_mode == "multi_vector":
            #  [新增] 多向量運算分支
            raw_results = self.engine.search_multi_vector(
                self.query['pos'], self.query['neg'], self.top_k, folder_path=self.folder_path
            )
        else:
            raw_results = self.engine.search_hybrid(
                self.query, self.top_k, self.use_ocr, self.weight_config, folder_path=self.folder_path
            )
            
        self.batch_ready.emit(raw_results)
        self.finished_search.emit(time.time() - start_time, len(raw_results))

from export_clip_onnx import export_to_onnx

class ONNXExportWorker(QThread):
    progress_update = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool)
    
    def __init__(self, model_name, pretrained):
        super().__init__()
        self.model_name = model_name
        self.pretrained = pretrained
        self.save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "onnx_clip")
        
    def run(self):
        try:
            # 傳入 self.progress_update.emit 當作 callback，即時回傳進度
            success = export_to_onnx(
                self.model_name, self.pretrained, self.save_dir, 
                progress_callback=self.progress_update.emit
            )
            self.finished_signal.emit(success)
        except Exception as e:
            self.progress_update.emit(0, f"Error: {str(e)}")
            self.finished_signal.emit(False)

class OCRImportWorker(QThread):
    """[離線版] 從本地的 ZIP 擴充包解壓縮，取代原本的網路下載"""
    progress_update = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str, str) # success, lang_code, message
    
    def __init__(self, lang_code, zip_path):
        super().__init__()
        self.lang_code = lang_code
        self.zip_path = zip_path
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.models_dir = os.path.join(self.base_dir, "models", "ocr")
        
    def run(self):
        try:
            import zipfile
            lang_dir = os.path.join(self.models_dir, self.lang_code)
            common_dir = os.path.join(self.models_dir, "common")
            os.makedirs(lang_dir, exist_ok=True)
            os.makedirs(common_dir, exist_ok=True)
            
            self.progress_update.emit(10, "正在解壓縮本地模型包...")
            
            with zipfile.ZipFile(self.zip_path, 'r') as zip_ref:
                # 簡單的進度模擬
                file_list = zip_ref.namelist()
                total_files = len(file_list)
                for i, file in enumerate(file_list):
                    zip_ref.extract(file, self.models_dir)
                    percent = int(10 + (i / total_files) * 80)
                    self.progress_update.emit(percent, f"解壓縮中... ({percent}%)")
                    
            self.progress_update.emit(100, "模型包匯入完成！")
            self.finished_signal.emit(True, self.lang_code, "本地模型匯入成功！可以開始使用了。")
            
        except Exception as e:
            self.finished_signal.emit(False, self.lang_code, f"匯入發生錯誤:\n{str(e)}")

# ==========================================
#  [NEW] 獨立 UI 圖層：懸浮多語系標籤
# ==========================================
class FloatingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 讓滑鼠點擊可以直接穿透這個標籤，避免擋住底下的紅框
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        
        self.results = []
        self.box_poly = None
        self.cursor_pos = QPoint()
        self.mode = "anchored"


        

    def update_data(self, results, box_poly, cursor_pos, mode):
        self.results = results
        self.box_poly = box_poly
        self.cursor_pos = cursor_pos
        self.mode = mode

        if not results or not self.parent():
            self.hide()
            return

        # --- 計算面板所需尺寸 ---
        font_text = QFont("Microsoft JhengHei", 13, QFont.Weight.Bold)
        fm_text = QFontMetrics(font_text)
        pad_x = 12
        pad_y = 10
        line_spacing = 6
        max_w = 0
        total_h = 0

        for r in results:
            lang_str = f"[{r.get('lang', 'unk').upper()}]"
            text_str = r.get("text", "")
            conf_str = f"({r.get('conf', 0.0):.2f})"
            w = fm_text.boundingRect(f"{lang_str} {text_str} {conf_str} ").width()
            if w > max_w: max_w = w
            total_h += fm_text.height()

        total_h += (len(results) - 1) * line_spacing
        panel_w = max_w + (pad_x * 2)
        panel_h = total_h + (pad_y * 2)

        parent_w = self.parent().width()
        parent_h = self.parent().height()

        # 超長文字防護：不超過父視窗寬度
        max_panel_w = parent_w - 20
        if panel_w > max_panel_w: panel_w = max_panel_w

        # --- 計算動態座標 (兩種模式) ---
        if mode == "anchored" and box_poly and not box_poly.isEmpty():
            rect = box_poly.boundingRect()
            # 優先位置：框的上方對齊左側
            pos_x = rect.left()
            pos_y = rect.top() - panel_h - 8

            # 若上方空間不夠，改放下方
            if pos_y < 10:
                pos_y = rect.bottom() + 8
            # 若下方也超出畫面 (框極大)，浮在框內頂部
            if pos_y + panel_h > parent_h:
                pos_y = rect.top() + 8

            # X 軸邊界防護：超出右邊則對齊右側，超出左邊則鎖死 10px
            if pos_x + panel_w > parent_w:
                pos_x = rect.right() - panel_w
            if pos_x < 10: pos_x = 10
        else:
            # 跟隨游標模式 (Follow)
            pos_x = cursor_pos.x() + 15
            pos_y = cursor_pos.y() + 15
            if pos_x + panel_w > parent_w: pos_x = cursor_pos.x() - panel_w - 10
            if pos_y + panel_h > parent_h: pos_y = cursor_pos.y() - panel_h - 10
            if pos_x < 10: pos_x = 10
            if pos_y < 10: pos_y = 10

        self.resize(panel_w, panel_h)
        self.move(pos_x, pos_y)
        self.show()
        self.update()

    def paintEvent(self, event):
        if not self.results: return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font_text = QFont("Microsoft JhengHei", 13, QFont.Weight.Bold)
        fm_text = QFontMetrics(font_text)
        pad_x = 12
        pad_y = 10
        line_spacing = 6
        panel_rect = self.rect()

        # ==========================================
        # [新增] 1. 預先計算所有語言標籤的「最大寬度」
        # ==========================================
        max_lang_w = 0
        for r in self.results:
            lang_str = f"[{r.get('lang', 'unk').upper()}] "
            w = fm_text.boundingRect(lang_str).width()
            if w > max_lang_w:
                max_lang_w = w

        # 畫背景面板 (深灰色)
        bg_color_str = self.window().theme_manager.current_colors.get("bg_floating", "#f0232323")
        painter.setBrush(QColor(bg_color_str))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)

        current_y = panel_rect.top() + pad_y + fm_text.ascent()

        for r in self.results:
            lang_str = f"[{r.get('lang', 'unk').upper()}] "
            text_str = r.get("text", "")
            conf_str = f" {r.get('conf', 0.0):.2f}"

            #  取得主題顏色
            colors = self.window().theme_manager.current_colors
            
            # 1. 畫語言標籤 (主題主色)
            painter.setPen(QColor(colors.get("primary", "#60cdff")))
            painter.drawText(panel_rect.left() + pad_x, current_y, lang_str)

            # 2. 計算信心度寬度 (靠右對齊用)
            conf_w = fm_text.boundingRect(conf_str).width()

            # 3. 畫辨識文字 (主題主要文字色)
            text_start_x = panel_rect.left() + pad_x + max_lang_w
            text_max_w = panel_rect.width() - (pad_x * 2) - max_lang_w - conf_w
            if text_max_w < 20: text_max_w = 20
            elided_text = fm_text.elidedText(text_str, Qt.TextElideMode.ElideRight, text_max_w)
            
            painter.setPen(QColor(colors.get("text_main", "#ffffff")))
            painter.drawText(text_start_x, current_y, elided_text)

            # 4. 畫信心度 (主題次要文字色)
            painter.setPen(QColor(colors.get("text_muted", "#aaaaaa")))
            painter.drawText(panel_rect.right() - pad_x - conf_w, current_y, conf_str)

            current_y += fm_text.height() + line_spacing

# ==========================================
# 請將這段程式碼完全覆蓋原本的 OCRLabel 類別
# ==========================================
class OCRLabel(QLabel):
    hover_info_changed = pyqtSignal(list, QPolygon, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ocr_data = []
        self.show_ocr_boxes = False
        self.original_size = QSize(0, 0)
        self.search_query = ""
        self.is_precise_mode = False 
        
        # [新增] 1. 開啟滑鼠追蹤，讓游標移動時也能觸發事件
        self.setMouseTracking(True)
        # [新增] 紀錄目前滑鼠懸停踩中的多邊形索引與游標位置
        self.hovered_index = -1
        self.cursor_pos = QPoint(0, 0)


    def set_draw_boxes(self, show):
        self.show_ocr_boxes = show
        if not show:
            self.hovered_index = -1
            self.hover_info_changed.emit([], QPolygon(), QPoint())
        self.update()

    def set_precomputed_ocr_data(self, precomputed_data, orig_w, orig_h, query="", is_precise=False):
        """[極速版] 捨棄所有運算，直接接收背景算好的幾何資料，UI 執行緒只負責繪圖"""
        self.original_size = QSize(orig_w, orig_h)
        self.search_query = query.lower()
        self.is_precise_mode = is_precise
        self.hovered_index = -1
        self.ocr_data = precomputed_data
        self.update()

    def _calculate_ratios(self, full_text, search_query):
        """計算字元權重與起訖比例"""
        start_idx = full_text.find(search_query)
        if start_idx == -1:
            return 0.0, 1.0
            
        def get_weight(char):
            return 2.0 if ord(char) > 255 else 1.0

        total_weight = sum(get_weight(c) for c in full_text)
        if total_weight == 0: 
            return 0.0, 1.0
            
        start_weight = sum(get_weight(c) for c in full_text[:start_idx])
        match_weight = sum(get_weight(c) for c in search_query)
        
        start_ratio = start_weight / total_weight
        end_ratio = (start_weight + match_weight) / total_weight
        
        return start_ratio, end_ratio

    # ==========================================
    # [新增] 滑鼠移動事件：處理座標對齊與碰撞偵測
    # ==========================================
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        
        # 如果沒開紅框，或者沒資料，就不浪費算力
        if not self.show_ocr_boxes or not self.ocr_data or not self.pixmap():
            return
            
        if self.original_size.width() == 0 or self.original_size.height() == 0:
            return

        self.cursor_pos = event.pos()
        
        # 1. 取得目前圖片在畫面上的縮放比例與位移
        displayed_w = self.pixmap().width()
        displayed_h = self.pixmap().height()
        offset_x = (self.width() - displayed_w) / 2
        offset_y = (self.height() - displayed_h) / 2
        scale_x = displayed_w / self.original_size.width()
        scale_y = displayed_h / self.original_size.height()

        # 2. 將滑鼠在螢幕上的座標，逆向還原回圖片的「真實像素座標」
        real_x = (self.cursor_pos.x() - offset_x) / scale_x
        real_y = (self.cursor_pos.y() - offset_y) / scale_y
        real_point = QPoint(int(real_x), int(real_y))

        # 3. 多邊形碰撞測試 (Hit Test)
        new_hovered_index = -1
        for i, item in enumerate(self.ocr_data):
            box = item.get("box")
            if box and len(box) == 4:
                # 建立原尺寸的多邊形
                poly = QPolygon([QPoint(int(pt[0]), int(pt[1])) for pt in box])
                # 測試滑鼠是否踩在裡面
                if poly.containsPoint(real_point, Qt.FillRule.OddEvenFill):
                    new_hovered_index = i
                    break # 找到一個就停，避免重疊時閃爍

        # 4. 如果踩到的目標改變了，或者游標在框內移動(需要更新標籤位置)
        if self.hovered_index != new_hovered_index or new_hovered_index != -1:
            self.hovered_index = new_hovered_index
            self.update()
            
            # [新增] 準備資料並發射給 FloatingWidget
            if self.hovered_index != -1:
                item = self.ocr_data[self.hovered_index]
                results = item.get("results", [])

                sorted_box = item.get("box")
                full_poly_points = []
                for pt in sorted_box:
                    nx = pt[0] * scale_x + offset_x
                    ny = pt[1] * scale_y + offset_y
                    full_poly_points.append(QPoint(int(nx), int(ny)))
                poly = QPolygon(full_poly_points)

                self.hover_info_changed.emit(results, poly, self.cursor_pos)
            else:
                self.hover_info_changed.emit([], QPolygon(), QPoint())

    def paintEvent(self, event):
        super().paintEvent(event)
        
        if self.show_ocr_boxes and self.ocr_data and self.pixmap():
            if self.original_size.width() == 0 or self.original_size.height() == 0:
                return

            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            displayed_w = self.pixmap().width()
            displayed_h = self.pixmap().height()
            offset_x = (self.width() - displayed_w) / 2
            offset_y = (self.height() - displayed_h) / 2
            scale_x = displayed_w / self.original_size.width()
            scale_y = displayed_h / self.original_size.height()

            import math

            # ==========================================
            # 迴圈 1：繪製所有底層紅框 (與精確高亮)
            # ==========================================
            for i, item in enumerate(self.ocr_data):
                sorted_box = item.get("box") 
                if not sorted_box or len(sorted_box) != 4: continue
                
                # 將該框群組內的所有文字串起來檢查是否命中搜尋
                results = item.get("results", [])
                full_text = " ".join([r.get("text", "") for r in results]).lower()
                
                p0, p1, p2, p3 = sorted_box[0], sorted_box[1], sorted_box[2], sorted_box[3]
                highlight_box = sorted_box
            
                if self.search_query and self.search_query in full_text:
                    if self.is_precise_mode:
                        # 找出具體是哪個語言的文字命中了，以此來計算黃色螢光筆的比例
                        match_text = ""
                        for r in results:
                            if self.search_query in r.get("text", "").lower():
                                match_text = r.get("text", "").lower()
                                break
                        if not match_text: match_text = full_text
                        
                        start_ratio, end_ratio = self._calculate_ratios(match_text, self.search_query)
                        margin = 0.015
                        if start_ratio > 0.0: start_ratio = min(start_ratio + margin, 1.0)
                        if end_ratio < 1.0:   end_ratio = max(end_ratio - margin, 0.0)
                        if start_ratio >= end_ratio:
                            center = (start_ratio + end_ratio) / 2.0
                            start_ratio, end_ratio = center - 0.001, center + 0.001

                        width = math.hypot(p0[0] - p1[0], p0[1] - p1[1])
                        height = math.hypot(p0[0] - p3[0], p0[1] - p3[1])
                        
                        if height > width * 1.2:
                            np0 = [p0[0] + (p3[0]-p0[0])*start_ratio, p0[1] + (p3[1]-p0[1])*start_ratio]
                            np3 = [p0[0] + (p3[0]-p0[0])*end_ratio,   p0[1] + (p3[1]-p0[1])*end_ratio]
                            np1 = [p1[0] + (p2[0]-p1[0])*start_ratio, p1[1] + (p2[1]-p1[1])*start_ratio]
                            np2 = [p1[0] + (p2[0]-p1[0])*end_ratio,   p1[1] + (p2[1]-p1[1])*end_ratio]
                        else:
                            np0 = [p0[0] + (p1[0]-p0[0])*start_ratio, p0[1] + (p1[1]-p0[1])*start_ratio]
                            np1 = [p0[0] + (p1[0]-p0[0])*end_ratio,   p0[1] + (p1[1]-p0[1])*end_ratio]
                            np3 = [p3[0] + (p2[0]-p3[0])*start_ratio, p3[1] + (p2[1]-p3[1])*start_ratio]
                            np2 = [p3[0] + (p2[0]-p3[0])*end_ratio,   p3[1] + (p2[1]-p3[1])*end_ratio]
                    
                        highlight_box = [np0, np1, np2, np3]
                
                    poly_points = []
                    for pt in highlight_box:
                        nx = pt[0] * scale_x + offset_x
                        ny = pt[1] * scale_y + offset_y
                        poly_points.append(QPoint(int(nx), int(ny)))
                
                    #  從頂層視窗取得 ThemeManager
                    colors = self.window().theme_manager.current_colors
                    highlight_color = QColor(colors.get("ocr_highlight", "#64ffff00"))
                    
                    painter.setBrush(QBrush(highlight_color)) 
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPolygon(QPolygon(poly_points))
            
                full_poly_points = []
                for pt in sorted_box:
                    nx = pt[0] * scale_x + offset_x
                    ny = pt[1] * scale_y + offset_y
                    full_poly_points.append(QPoint(int(nx), int(ny)))
                    
                #  從主題取得基礎色與懸停色
                colors = self.window().theme_manager.current_colors
                hover_bg = QColor(colors.get("primary", "#60cdff"))
                hover_bg.setAlpha(60) # 加上透明度
                hover_pen = QColor(colors.get("primary", "#60cdff"))
                normal_pen = QColor(colors.get("ocr_box_normal", "#c8ff0000"))

                if i == self.hovered_index:
                    painter.setBrush(QBrush(hover_bg)) 
                    painter.setPen(QPen(hover_pen, 3))
                    painter.drawPolygon(QPolygon(full_poly_points))
                else:
                    painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    painter.setPen(QPen(normal_pen, 2))
                    painter.drawPolygon(QPolygon(full_poly_points))


class PreviewOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        self.setObjectName("PreviewOverlayMask")
        
        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.image_label = OCRLabel()
        self.image_label.hover_info_changed.connect(self.on_hover_info_changed)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: transparent;")
        
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0,0,0, 150))
        self.image_label.setGraphicsEffect(shadow)
        
        self.layout.addWidget(self.image_label)
        
        self.filename_label = QLabel()
        self.filename_label.setObjectName("PreviewOverlayFilename")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.filename_label)
        
        self.ocr_hint = QLabel("Hold SHIFT to view OCR text locations")
        self.ocr_hint.setObjectName("PreviewOverlayHint")
        self.layout.addWidget(self.ocr_hint, alignment=Qt.AlignmentFlag.AlignCenter)

        self.floating_tag = FloatingWidget(self)

        self.current_preview_path = ""
        self.current_preview_worker = None
    
    def on_hover_info_changed(self, results, poly, cursor_pos):
        if not results:
            self.floating_tag.hide()
            return

        # 把 OCRLabel 的區域座標，轉換成 PreviewOverlay (全螢幕) 的絕對座標
        mapped_poly = QPolygon([self.image_label.mapTo(self, pt) for pt in poly])
        mapped_cursor = self.image_label.mapTo(self, cursor_pos)

        # 讀取設定檔決定顯示模式
        ui_state = self.parent().config.get("ui_state", {})
        mode = ui_state.get("ocr_tag_mode", "anchored")

        self.floating_tag.update_data(results, mapped_poly, mapped_cursor, mode)

    def set_ocr_visible(self, visible):
        self.image_label.set_draw_boxes(visible)
        if not visible:
            self.floating_tag.hide()

    def show_image(self, result_data, current_query="", is_precise_mode=False, l1_pixmap=None):
        if isinstance(result_data, ImageItem):
            path = result_data.path
            orig_w, orig_h = result_data.width, result_data.height
        else:
            path = result_data['path']
            screen_size = self.parent().size()
            orig_w = result_data.get('width', int(screen_size.width() * 0.85))
            orig_h = result_data.get('height', int(screen_size.height() * 0.85))

        if not os.path.exists(path): return

        self.current_preview_path = path

        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None

        screen_size = self.parent().size()
        max_w = int(screen_size.width() * 0.85)
        max_h = int(screen_size.height() * 0.85)
        target_size = QSize(max_w, max_h)

        if orig_w == 0 or orig_h == 0:
            orig_w, orig_h = target_size.width(), target_size.height()

        if l1_pixmap and not l1_pixmap.isNull():
            scaled_l1 = l1_pixmap.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_l1)
        else:
            self.image_label.clear()

        
        self.image_label.set_precomputed_ocr_data([], orig_w, orig_h)

        #  將 engine 傳入，讓它在背景自己去撈資料！
        self.current_preview_worker = PreviewLoader(
            path, target_size, self.parent().engine, current_query, is_precise_mode, orig_w, orig_h
        )
        self.current_preview_worker.signals.result.connect(self.on_highres_ready)
        QThreadPool.globalInstance().start(self.current_preview_worker)

        self.filename_label.setText(os.path.basename(path))
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()

    def on_highres_ready(self, path, img, merged_data, orig_w, orig_h, query, is_precise):
        # 確保是目前正在看這張圖
        if path == self.current_preview_path:
            
            # 1.  確保在 UI 執行緒內才把 QImage 轉換為 QPixmap，絕對安全！
            if not img.isNull():
                pixmap = QPixmap.fromImage(img)
                self.image_label.setPixmap(pixmap)
                
            # 2.  就算圖片因為極端原因載入失敗，我們也強制把算好的 OCR 資料塞給畫布
            # 這樣按 Shift 就絕對能看得到紅框！
            self.image_label.set_precomputed_ocr_data(merged_data, orig_w, orig_h, query, is_precise)
            self.image_label.update()

    def set_ocr_visible(self, visible):
        self.image_label.set_draw_boxes(visible)

    def hideEvent(self, event):
        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.hide()

    def mousePressEvent(self, event):
        # 只有點擊圖片以外的區域才關閉
        if not self.image_label.geometry().contains(event.position().toPoint()):
            self.hide()

# HistoryItemWidget 已遷移至 ui/widgets/search_capsule.py

class StatsMenuWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.setFixedWidth(420)
        self.setFixedHeight(500)
        #  1. 主體面板發放身分證
        self.setObjectName("StatsPanel")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)
        
        title_container = QWidget()
        #  2. 標題區塊發放身分證
        title_container.setObjectName("StatsHeader")
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(15, 10, 15, 10)
        title_lbl = QLabel("Indexed Folders")
        title_lbl.setObjectName("StatsTitle")
        title_layout.addWidget(title_lbl)
        self.main_layout.addWidget(title_container)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("InspectorScrollArea")
        
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        footer_container = QWidget()
        #  3. 底部區塊發放身分證
        footer_container.setObjectName("StatsFooter")
        footer_layout = QHBoxLayout(footer_container)
        footer_layout.setContentsMargins(15, 8, 15, 8)
        self.total_label = QLabel("Total: 0 images")
        self.total_label.setObjectName("StatsTotal")
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
            lbl_name.setObjectName("StatsRowName")
            
            
            lbl_count = QLabel(f"{count}")
            lbl_count.setObjectName("StatsRowCount")
            lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            row_layout.addWidget(lbl_name, stretch=1)
            row_layout.addWidget(lbl_count)
            
            #  4. 資料行發放身分證
            row.setObjectName("StatsRow")
            
            self.content_layout.addWidget(row)
            
        self.total_label.setText(f"Total: {total_images:,} images")

class FolderHoverMenu(QWidget):
    """
    [最終修正版] 二級點擊選單
    1. 資料夾顯示：數字索引。
    2. [新增] 重新整理按鈕 (環形箭頭)，位於倒數第二格。
    3. 新增按鈕：位於最右邊。
    """
    folder_clicked = pyqtSignal(str)
    refresh_clicked = pyqtSignal() # [新增] 重新整理訊號
    add_clicked = pyqtSignal()

    mouse_entered = pyqtSignal()
    mouse_left = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # 主佈局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 內部容器
        self.container_frame = QFrame()
        self.container_frame.setObjectName("MenuContainer")
        
        # 容器佈局
        self.container_layout = QHBoxLayout(self.container_frame)
        self.container_layout.setContentsMargins(5, 5, 5, 5) 
        self.container_layout.setSpacing(5)              
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.main_layout.addWidget(self.container_frame)

        

    #  [新增] 覆寫滑鼠進出事件，通知上層 Sidebar
    def enterEvent(self, event):
        self.mouse_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.mouse_left.emit()
        super().leaveEvent(event)

    def update_menu(self, stats, config_folders): 
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        btn_size = 48 
        
        # 把 SQL stats 轉成字典方便查詢 (路徑 -> 數量)
        stats_dict = {os.path.normpath(p): c for p, c in stats}
        
        # 1. 建立資料夾按鈕 (依照 config_folders 的自訂排序)
        for i, f_obj in enumerate(config_folders, 1):
            path = f_obj["path"]
            icon = f_obj.get("icon", "")
            count = stats_dict.get(os.path.normpath(path), 0)
            
            btn = QPushButton()
            btn.setFixedSize(btn_size, btn_size)
            
            # 判斷要顯示表情符號還是數字
            if icon:
                btn.setText(icon)
                # 強制使用表情符號字體並加大
                btn.setStyleSheet(btn.styleSheet() + " font-size: 20px; font-family: 'Segoe UI Emoji';")
            else:
                btn.setText(str(i))
                
            # [修正] 使用 HTML 格式強制鎖定 ToolTip 的字型與大小，打破繼承
            btn.setToolTip(f"<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>{path}<br>({count} 張圖片)</div>")
            btn.clicked.connect(lambda checked, p=path: self.on_folder_click(p))
            self.container_layout.addWidget(btn)

        # 2. [新增] 建立「重新整理按鈕」 (倒數第二格)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setObjectName("RefreshBtn")
        self.btn_refresh.setFixedSize(btn_size, btn_size)
        self.btn_refresh.setToolTip("<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>Rescan all folders (Run AI)</div>")
        self.btn_refresh.clicked.connect(self.on_refresh_click)
        self.container_layout.addWidget(self.btn_refresh)

        # 3. 建立「新增按鈕」 (+) (最右邊)
        self.btn_add = QPushButton("+")
        self.btn_add.setObjectName("AddBtn")
        self.btn_add.setFixedSize(btn_size, btn_size)
        self.btn_add.setToolTip("<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px; font-weight: normal;'>Add new folder source...</div>")
        self.btn_add.clicked.connect(self.on_add_click)
        self.container_layout.addWidget(self.btn_add)

    def on_folder_click(self, path):
        self.folder_clicked.emit(path)
        self.close()

    def on_refresh_click(self):
        self.refresh_clicked.emit()
        self.close()

    def on_add_click(self):
        self.add_clicked.emit()
        self.close()

    def show_at(self, global_pos, height):
        self.container_frame.setFixedHeight(height)
        
        # 計算寬度
        btn_count = self.container_layout.count()
        btn_width = 48
        spacing = 5
        margin = 5
        
        if btn_count > 0:
            total_width = (margin * 2) + (btn_count * btn_width) + ((btn_count - 1) * spacing)
            total_width += 4 
        else:
            total_width = 100
            
        self.resize(total_width, height)
        self.container_frame.setFixedSize(total_width, height)

        self.move(global_pos)
        self.show()

# ==========================================
#  可接收拖曳的虛擬資料夾按鈕
# ==========================================
class DroppableFolderButton(QPushButton):
    """繼承自 QPushButton，具備接收 GalleryListView 拖曳的能力。
    當圖片路徑被拖入並釋放時，透過 files_dropped 訊號往外拋出。
    點擊時透過 collection_selected 訊號向外傳遞 'col:{id}' 格式字串。
    """
    files_dropped = pyqtSignal(int, list)     # (collection_id, [file_paths])
    collection_selected = pyqtSignal(str)     # 'col:{collection_id}'

    def __init__(self, collection_id: int, parent=None):
        super().__init__(parent)
        self._collection_id = collection_id
        self.setAcceptDrops(True)
        # 在此直接連接，self._collection_id 是實例屬性，無閉包問題
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, checked=False):
        self.collection_selected.emit(f"col:{self._collection_id}")

    def _set_drag_hover(self, state: bool):
        self.setProperty("drag_hover", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_hover(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._set_drag_hover(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_hover(False)
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        file_paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if file_paths:
            event.acceptProposedAction()
            self.files_dropped.emit(self._collection_id, file_paths)
        else:
            event.ignore()


class SidebarWidget(QFrame):
    folder_selected = pyqtSignal(str) 
    toggled = pyqtSignal(bool)
    add_folder_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    files_dropped_to_collection = pyqtSignal(int, list)  # (collection_id, [file_paths])

    def __init__(self, parent=None):
        super().__init__(parent)
        self.expanded_width = 240
        self.collapsed_width = 60 
        self.is_expanded = True
        self.stats_cache = []
        
        self.setObjectName("Sidebar")
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 1. 漢堡選單
        self.btn_toggle = QPushButton("≡")
        self.btn_toggle.setObjectName("SidebarToggle")
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
        # [修正] 移除重複的 setObjectName，只保留有效的 "Row1"
        self.btn_all_images.setObjectName("Row1")
        self.btn_all_images.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_all_images.setFixedHeight(60)
        self.btn_all_images.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.icon_folder = QFileIconProvider().icon(QFileInfo("."))
        self.btn_all_images.setIcon(self.icon_folder)
        self.btn_all_images.setIconSize(QSize(24, 24))
        
        self.btn_all_images.clicked.connect(self.on_row1_clicked)

        self.btn_all_images.installEventFilter(self)
        
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self.check_and_hide_menu)

        self.row1_layout.addWidget(self.btn_all_images)
        self.layout.addWidget(self.row1_container)

        # [新建] 實體資料夾分類標題按鈕 (預設隱藏，僅展開模式顯示)
        self.btn_entity_header = QPushButton("  📁 實體資料夾 (Folders)")
        self.btn_entity_header.setObjectName("SidebarSectionHeader")
        self.btn_entity_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_entity_header.setFixedHeight(36)
        self.btn_entity_header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_entity_header.clicked.connect(self._toggle_sub_folders)
        self.btn_entity_header.setVisible(False)  # 收合時隱藏
        self.layout.addWidget(self.btn_entity_header)

        # [新建] 手風琴展開區塊：實體資料夾按鈕列表 (預設隱藏)
        self.sub_folders_container = QFrame()
        self.sub_folders_container.setObjectName("SubFoldersContainer")
        self._sub_folders_layout = QVBoxLayout(self.sub_folders_container)
        self._sub_folders_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_folders_layout.setSpacing(0)
        self.sub_folders_container.setVisible(False)
        self.layout.addWidget(self.sub_folders_container)

        # 3. 初始化二級懸浮選單 (收合模式專用)
        self.hover_menu = FolderHoverMenu(self)
        self.hover_menu.folder_clicked.connect(self.on_sub_folder_clicked)
        self.hover_menu.add_clicked.connect(self.add_folder_requested.emit)

        self.hover_menu.mouse_entered.connect(self.hover_timer.stop)
        self.hover_menu.mouse_left.connect(lambda: self.hover_timer.start(150))

        # ─── Collections 容器（Phase 13）───────────────────────────────
        self._col_separator = QFrame()
        self._col_separator.setFrameShape(QFrame.Shape.HLine)
        self._col_separator.setObjectName("SidebarSeparator")
        self._col_separator.hide()
        self.layout.addWidget(self._col_separator)

        self.btn_col_header = QPushButton("  🏷️ 收資料夾 (Collections)")
        self.btn_col_header.setObjectName("SidebarSectionHeader")
        self.btn_col_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_col_header.setFixedHeight(36)
        self.btn_col_header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_col_header.clicked.connect(self._toggle_col_container)
        self.btn_col_header.setVisible(False)
        self.layout.addWidget(self.btn_col_header)

        self._col_container = QWidget()
        self._col_layout = QVBoxLayout(self._col_container)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.setSpacing(0)
        self._col_container.hide()
        self.layout.addWidget(self._col_container)
        # ────────────────────────────────────────────────────────────────
        
        # ==========================================
        # [新增] 側邊欄底部的設定入口
        # ==========================================
        self.layout.addStretch(1) # 這個伸縮空間會把下面的設定按鈕「推」到最底端
        
        self.btn_settings = QPushButton()
        self.btn_settings.setObjectName("SidebarRow1")
        self.btn_settings.setObjectName("Row1") # 共用 Hover 亮條樣式
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setFixedHeight(60)
        self.btn_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_settings.clicked.connect(self.settings_requested.emit)

        # [關鍵修正] 將表情符號畫成固定大小的圖示 (QIcon)，解決縮放問題
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(QFont("Segoe UI Emoji", 18))
        painter.setPen(QColor("#cccccc")) # 讓齒輪顏色與文字一致
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚙️")
        painter.end()
        
        self.btn_settings.setIcon(QIcon(pixmap))
        self.btn_settings.setIconSize(QSize(24, 24)) # 強制鎖定圖示大小

        self.layout.addWidget(self.btn_settings)

        # [新增] 連接重新整理訊號
        self.hover_menu.refresh_clicked.connect(self.refresh_requested.emit)
        
        self.update_ui_text()
        self.setFixedWidth(self.expanded_width)

    def update_folders(self, stats, config_folders):
        self.stats_cache = stats
        # [不變] 懸浮選單持續同步更新，收合模式依然可用
        self.hover_menu.update_menu(stats, config_folders)
        # [新增] 同步更新手風琴區塊中的按鈕
        self._rebuild_sub_folders(stats, config_folders)
        total = sum(c for _, c in stats)
        self.all_images_text = f"  All Images ({total})"
        self.update_ui_text()

    def _rebuild_sub_folders(self, stats, config_folders):
        """重建手風琴區塊內的實體資料夾按鈕。"""
        # 清空舊按鈕
        while self._sub_folders_layout.count():
            child = self._sub_folders_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        stats_dict = {os.path.normpath(p): c for p, c in stats}

        for i, f_obj in enumerate(config_folders, 1):
            path = f_obj["path"]
            # [防呆] icon 為空字串或 None 時強制給予預設圖示
            icon = f_obj.get("icon", "") or "📁"
            count = stats_dict.get(os.path.normpath(path), 0)

            btn = QPushButton()
            btn.setObjectName("Row1")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(54)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("expanded", True)  # 手風琴區塊永遠為展開狀態

            # 圖示
            if icon:
                px = QPixmap(28, 28)
                px.fill(Qt.GlobalColor.transparent)
                p = QPainter(px)
                p.setFont(QFont("Segoe UI Emoji", 16))
                p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, icon)
                p.end()
                btn.setIcon(QIcon(px))
                btn.setIconSize(QSize(22, 22))

            display_name = os.path.basename(path) or path
            btn.setText(f"  {display_name}  ({count})")
            btn.setToolTip(f"<div style='font-family: \"Segoe UI\", sans-serif; font-size: 14px;'>{path}<br>({count} 張圖片)</div>")
            btn.clicked.connect(lambda checked=False, p=path: self.folder_selected.emit(p))
            self._sub_folders_layout.addWidget(btn)

    def toggle_sidebar(self):
        self.is_expanded = not self.is_expanded
        self.setFixedWidth(self.expanded_width if self.is_expanded else self.collapsed_width)
        # [修正] 切換時清除殘留的懸浮選單
        self.hide_hover_menu()
        # 收合時同步關閉手風琴展開區與標題
        if not self.is_expanded:
            self.btn_entity_header.setVisible(False)
            self.sub_folders_container.setVisible(False)
            self.btn_col_header.setVisible(False)
        self.update_ui_text()
        self.toggled.emit(self.is_expanded)

    def update_ui_text(self):
        if self.is_expanded:
            self.btn_all_images.setText(getattr(self, 'all_images_text', "  All Images"))
            self.btn_settings.setText("  設定 (Settings)")
            # 標題在有實體資料夾時才顯示
            has_folders = self._sub_folders_layout.count() > 0
            self.btn_entity_header.setVisible(has_folders)
        else:
            self.btn_all_images.setText("")
            self.btn_settings.setText("")
            self.btn_entity_header.setVisible(False)

        # Collections header 隨展開狀態顯示/隱藏（有資料才顯示，不依賴容器是否展開）
        has_collections = self._col_layout.count() > 0
        self.btn_col_header.setVisible(self.is_expanded and has_collections)

        # 同步更新所有 collection 按鈕的文字與 expanded 屬性
        for i in range(self._col_layout.count()):
            btn = self._col_layout.itemAt(i).widget()
            if btn is None:
                continue
            # 按鈕 toolTip 存了名稱與 count，從 text 反推太脆，改用 userData (property)
            col_data = btn.property("col_data")
            if col_data and self.is_expanded:
                btn.setText(f"  {col_data[0]}  ({col_data[1]})")
            else:
                btn.setText("")
            btn.setProperty("expanded", self.is_expanded)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        #  終極重構：用屬性 (Property) 驅動 QSS，消滅硬寫的 StyleSheet
        # 通知這兩顆按鈕目前的狀態，QSS 檔裡的 [expanded="true"] 就會自動生效！
        for btn in [self.btn_all_images, self.btn_settings]:
            btn.setProperty("expanded", self.is_expanded)
            # 強制 Qt 重新讀取該元件的樣式
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

    def eventFilter(self, obj, event):
        if obj == self.btn_all_images:
            if event.type() == QEvent.Type.Enter:
                # [邏輯分流] 只有在「收合狀態」下才允許懸停觸發 HoverMenu
                if not self.is_expanded:
                    self.hover_timer.stop()
                    self.show_hover_menu()
            elif event.type() == QEvent.Type.Leave:
                # 收合模式才起動關閉計時，展開模式下不需要
                if not self.is_expanded:
                    self.hover_timer.start(150)
        return super().eventFilter(obj, event)

    #  顯示、隱藏與檢查邏輯
    def show_hover_menu(self):
        sidebar_global_pos = self.mapToGlobal(QPoint(0, 0))
        row1_y = self.btn_toggle.height()
        
        # 往左微調 5px 形成物理重疊，徹底避免滑鼠掉進縫隙
        target_x = sidebar_global_pos.x() + self.width() - 1
        target_y = sidebar_global_pos.y() + row1_y
        self.hover_menu.show_at(QPoint(target_x, target_y), 60)

    def hide_hover_menu(self):
        self.hover_menu.close()

    def check_and_hide_menu(self):
        """ 150ms 倒數結束後的絕對座標防呆檢查"""
        cursor_pos = QCursor.pos()
        
        # 1. 如果滑鼠還在選單上
        if self.hover_menu.isVisible() and self.hover_menu.geometry().contains(cursor_pos):
            return
            
        # 2. 如果滑鼠又回到了主按鈕上
        btn_rect = QRect(self.btn_all_images.mapToGlobal(QPoint(0, 0)), self.btn_all_images.size())
        if btn_rect.contains(cursor_pos):
            return
            
        # 3. 確定滑鼠離開了戰區，收起選單
        self.hide_hover_menu()

    def _toggle_sub_folders(self):
        """btn_entity_header 點擊事件：切換手風琴區塊的顯示/隱藏。"""
        self.sub_folders_container.setVisible(not self.sub_folders_container.isVisible())

    def _toggle_col_container(self):
        """btn_col_header 點擊事件：切換 Collections 區塊的顯示/隱藏。"""
        self._col_container.setVisible(not self._col_container.isVisible())

    def on_row1_clicked(self):
        # 只負責發出 ALL 訊號，手風琴切換由上方的分類標題負責
        self.folder_selected.emit("ALL")
        if not self.is_expanded:
            # 收合模式才需要關閉懸浮選單
            self.hide_hover_menu()

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

    def reload_collections(self, collections: list):
        while self._col_layout.count():
            child = self._col_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not collections:
            self._col_separator.hide()
            self.btn_col_header.hide()
            self._col_container.hide()
            return

        self._col_separator.show()
        self.btn_col_header.setVisible(self.is_expanded)
        self._col_container.show()

        for col_id, name, icon, count in collections:
            btn = DroppableFolderButton(col_id)
            btn.setObjectName("Row1")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(54)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("expanded", self.is_expanded)

            # 渲染 emoji icon
            px = QPixmap(28, 28)
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            p.setFont(QFont("Segoe UI Emoji", 16))
            p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, icon)
            p.end()
            btn.setIcon(QIcon(px))
            btn.setIconSize(QSize(22, 22))

            if self.is_expanded:
                btn.setText(f"  {name}  ({count})")
            btn.setProperty("col_data", (name, count))
            btn.collection_selected.connect(self.folder_selected.emit)
            btn.files_dropped.connect(self.files_dropped_to_collection)
            self._col_layout.addWidget(btn)

# ==========================================
#  [升級] CLIP 專用特徵選取桶 (SolidWorks 風格)
# ==========================================
class ThumbnailSignals(QObject):
    finished = pyqtSignal(QListWidgetItem, QIcon)

# ==========================================
#  [究極升級] 多模態特徵物件與互動式標籤 UI
# ==========================================
class FeatureItem:
    """統一管理圖片與文字的特徵結構"""
    def __init__(self, f_type, data):
        self.type = f_type  # 'image' 或是 'text'
        self.data = data    # 圖片路徑 或是 搜尋字串
        self.vector = None  # 緩存的 1024 維向量 (預熱用)

class TextFeatureWidget(QWidget):
    """直接可在清單內編輯的文字標籤"""
    def __init__(self, feat_item, is_positive, parent_bucket, list_item):
        super().__init__()
        self.feat_item = feat_item
        self.parent_bucket = parent_bucket
        self.list_item = list_item
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 2, 8, 2)
        
        #  重構魔法：核發身分證與極性，視覺全交給 QSS 接管！
        self.setObjectName("TextFeature")
        self.setProperty("polarity", "positive" if is_positive else "negative")
        
        self.lbl_icon = QLabel("[T]")
        # 這裡的 styleSheet 也被我們在 QSS 用 QWidget#TextFeature QLabel 統一處理掉了！
        self.layout.addWidget(self.lbl_icon)
        
        self.edit = QLineEdit(self.feat_item.data)
        self.edit.setPlaceholderText("輸入文字特徵 (Enter確認)...") 
        self.edit.editingFinished.connect(self.on_edit_finished)
        self.edit.returnPressed.connect(self.release_all_focus) 
        
        self.edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.edit.customContextMenuRequested.connect(self.on_custom_context_menu)
        
        #  新增：安裝事件過濾器來捕捉 ESC 鍵
        self.edit.installEventFilter(self)
        
        self.layout.addWidget(self.edit, stretch=1)

    #  新增：專屬的事件過濾器
    def eventFilter(self, obj, event):
        if obj == self.edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                # 完美的 UX：按下 ESC 時，不但取消焦點，還要「還原」為原本的文字
                # (如果是剛點出來的空標籤，還原後會是 ""，失去焦點時就會自動被銷毀！)
                self.edit.setText(self.feat_item.data)
                self.release_all_focus()
                return True # 成功攔截事件
        return super().eventFilter(obj, event)
        
    def release_all_focus(self):
        """徹底解放焦點：連同外層的清單選取狀態一起清除"""
        self.edit.clearFocus()
        self.parent_bucket.list_widget.clearSelection() 
        self.parent_bucket.list_widget.clearFocus()     
        
    def on_custom_context_menu(self, pos):
        if self.edit.hasFocus():
            menu = self.edit.createStandardContextMenu()
            menu.exec(self.edit.mapToGlobal(pos))
        else:
            global_pos = self.edit.mapToGlobal(pos)
            list_pos = self.parent_bucket.list_widget.mapFromGlobal(global_pos)
            self.parent_bucket.show_context_menu(list_pos)

    def on_edit_finished(self):
        new_text = self.edit.text().strip()
        if new_text:
            if self.feat_item.data != new_text: 
                self.feat_item.data = new_text
                self.feat_item.vector = None 
                self.parent_bucket.preheat_text_vector(self.feat_item)
                self.parent_bucket.files_changed.emit()
        else:
            self.parent_bucket.delete_item_by_widget(self.list_item)

class ThumbnailSignals(QObject):
    finished = pyqtSignal(QListWidgetItem, QIcon)

class ThumbnailWorker(QRunnable):
    def __init__(self, item, path, size=QSize(64, 64)):
        super().__init__(); self.item = item; self.path = path; self.size = size; self.signals = ThumbnailSignals()
    def run(self):
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            if reader.size().isValid():
                reader.setScaledSize(reader.size().scaled(self.size, Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull(): self.signals.finished.emit(self.item, QIcon(QPixmap.fromImage(img)))
        except: pass

class FeatureBucketWidget(QFrame):
    files_changed = pyqtSignal() 
    text_dropped = pyqtSignal(str) 

    # 🌟 拔除 idle_color 與 active_color 參數
    def __init__(self, title, is_positive, main_window, parent=None):
        super().__init__(parent)
        self.title = title
        self.is_positive = is_positive
        self.main_window = main_window
        
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus) #  拔除系統焦點，消滅外圍方形虛線
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(2, 2, 2, 2)
        
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("BucketListWidget")
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setIconSize(QSize(56, 56)); self.list_widget.setSpacing(4)
        #  加上終極 outline: none 宣告，連 item 內部的虛線一起殺掉
        
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        # 綁定事件攔截器
        self.list_widget.viewport().installEventFilter(self)
        
        #  重構魔法：核發身分證與預設極性
        self.setObjectName("FeatureBucket")
        self.setProperty("polarity", "positive" if is_positive else "negative")
        
        self.placeholder = QLabel(f"拖曳圖片、文字或「點擊此處」輸入...\n({title})", self)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setObjectName("BucketPlaceholder") # 發放專屬身分證
        self.placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        
        self.layout.addWidget(self.list_widget)
        self.update_visual_state(False)

    def eventFilter(self, source, event):
        if source == self.list_widget.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                item = self.list_widget.itemAt(event.pos())
                if not item: 
                    self.spawn_inline_editor()
                    return True #  攔截事件，防止失焦
        return super().eventFilter(source, event)

    def mousePressEvent(self, event):
        """ 終極防呆：就算點擊在清單邊緣 2px 的縫隙，一樣能觸發輸入"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.spawn_inline_editor()
        super().mousePressEvent(event)

    def spawn_inline_editor(self):
        feat = FeatureItem('text', "")
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 60))
        item.setData(Qt.ItemDataRole.UserRole, feat)
        self.list_widget.addItem(item)
        
        widget = TextFeatureWidget(feat, self.is_positive, self, item)
        self.list_widget.setItemWidget(item, widget)
        self.update_visual_state()
        
        #  延遲 10 毫秒奪取焦點，確保 Qt 渲染完成後游標能順利閃爍
        QTimer.singleShot(10, widget.edit.setFocus)

    def update_visual_state(self, is_hover=False):
        has_items = self.list_widget.count() > 0
        self.placeholder.setVisible(not has_items)
        self.list_widget.setVisible(True) 
        
        #  重構魔法：只改變狀態屬性，讓 Qt 自動去 QSS 找對應的衣服穿！
        self.setProperty("drag_hover", "true" if is_hover else "false")
        
        # 強制 Qt 重新整理這件元件的樣式
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.placeholder.setGeometry(self.rect())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction(); self.update_visual_state(True)

    def dragLeaveEvent(self, event): self.update_visual_state(False)

    def dropEvent(self, event):
        self.update_visual_state(False)
        added_new = False
        if event.mimeData().hasUrls():
            current_paths = [f.data for f in self.get_features() if f.type == 'image']
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = os.path.normpath(url.toLocalFile())
                    if path not in current_paths:
                        self.add_image_item(path); added_new = True
        elif event.mimeData().hasText():
            text = event.mimeData().text().strip()
            if text:
                self.add_text_item(text)
                self.text_dropped.emit(text) 
                added_new = True
        if added_new: self.files_changed.emit()

    def add_image_item(self, path):
        feat = FeatureItem('image', path)
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, feat)
        self.list_widget.addItem(item)
        worker = ThumbnailWorker(item, path)
        worker.signals.finished.connect(self._on_thumbnail_ready)
        QThreadPool.globalInstance().start(worker)
        self.update_visual_state()

    def add_text_item(self, text):
        feat = FeatureItem('text', text)
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 36))
        item.setData(Qt.ItemDataRole.UserRole, feat)
        self.list_widget.addItem(item)
        widget = TextFeatureWidget(feat, self.is_positive, self, item)
        self.list_widget.setItemWidget(item, widget)
        self.preheat_text_vector(feat) 
        self.update_visual_state()

    def preheat_text_vector(self, feat):
        if not hasattr(self, 'main_window') or not self.main_window.engine: return
        engine = self.main_window.engine
        class VectorWorker(QRunnable):
            def run(self):
                try: feat.vector = engine.get_text_vector(feat.data)
                except: pass
        QThreadPool.globalInstance().start(VectorWorker())

    def _on_thumbnail_ready(self, item, icon):
        if item.listWidget() is not None: item.setIcon(icon)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete: self.delete_selected()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_A: self.list_widget.selectAll()
        else: super().keyPressEvent(event)

    def show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        menu = QMenu(self)
        if item:
            action_delete = QAction("🗑️ 刪除 (Delete)", self)
            action_delete.triggered.connect(self.delete_selected)
            menu.addAction(action_delete); menu.addSeparator()
        action_clear = QAction("🚫 清除選擇 (Clear All)", self)
        action_clear.triggered.connect(self.clear_all)
        menu.addAction(action_clear); menu.exec(self.list_widget.mapToGlobal(pos))

    def clear_all(self):
        self.list_widget.clear(); self.update_visual_state(); self.files_changed.emit()

    def get_features(self):
        return [self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_widget.count())]
    
    # ==========================================
    #  徹底銷毀 UI 元件的刪除邏輯
    # ==========================================
    def delete_item_by_widget(self, list_item):
        """清除沒有輸入文字的幽靈框框，或清空現有文字的標籤"""
        row = self.list_widget.row(list_item)
        if row >= 0:
            #  關鍵修復：必須在 takeItem 「之前」先把 Widget 抓出來！
            # 否則脫離清單後，系統就再也認不得這個 UI 了
            widget = self.list_widget.itemWidget(list_item)
            
            # 將資料從清單中拔除
            self.list_widget.takeItem(row)
            
            # 強制從記憶體中把剛剛抓到的 UI 銷毀！
            if widget:
                widget.deleteLater()
                
            self.update_visual_state()
            self.files_changed.emit()

    def delete_selected(self):
        """使用者按 Delete 鍵或右鍵刪除時的邏輯"""
        for item in self.list_widget.selectedItems():
            #  同樣的防呆：先抓 UI，再拔資料，最後銷毀
            widget = self.list_widget.itemWidget(item)
            row = self.list_widget.row(item)
            
            self.list_widget.takeItem(row)
            
            if widget:
                widget.deleteLater()
                
        self.update_visual_state()
        self.files_changed.emit()


from ui.inspector_panel import CollapsibleSection, RangeCalendarWidget, InspectorPanel

class MainWindow(QMainWindow):
    # 定義訊號
    random_data_ready = pyqtSignal(list)
    ai_ready = pyqtSignal()
    db_reloaded = pyqtSignal()

    def __init__(self, config: ConfigManager):
        # [關鍵修正] 這行一定要在第一行，且不能漏掉！
        super().__init__()
        
        self.config = config
        self.setWindowTitle(WINDOW_TITLE)
        

        self.engine = None

        self.search_history = [] 
        self.current_selected_path = None

        self.current_folder_path = self.config.get("ui_state", {}).get("default_startup_folder", "ALL")

        self.is_ocr_locked = False

        self.last_search_results = [] # 儲存最近一次檢索回來的原始資料
        self.active_time_range = None # 目前選取的時間區間 (start_ts, end_ts)

        self.current_image_search_path = None
        self.current_multi_vector_features = None  # (pos_features, neg_features)
        
        # 設定歷史紀錄檔路徑
        self.history_file_path = os.path.join(self.config.app_root, "search_history.json")

        self.taskbar_ctrl = TaskbarController(self.winId())

        self.load_history()
        self.init_ui()

        # NavigationManager 需要在 init_ui() 之後建立 (因為依賴 UI 元件)
        from ui.navigation_manager import NavigationManager
        self.nav = NavigationManager(
            state_snapshot_fn=self._nav_snapshot,
            apply_state_fn=self._nav_apply,
            update_buttons_fn=lambda b, f: (
                self.btn_back.setEnabled(b),
                self.btn_forward.setEnabled(f),
            ),
        )
        
        self.indexer_worker = IndexerWorker(self.config, self)  # 加入 self 參數
        self.indexer_worker.status_update.connect(self.update_status) # 稍微改一下 status label 的用法
        self.indexer_worker.progress_update.connect(self.update_progress)
        self.indexer_worker.scan_finished.connect(self.on_scan_finished)
        self.indexer_worker.all_finished.connect(self.on_indexing_finished)

        self.search_orch = SearchOrchestrator(SearchWorker, parent=self)
        self.search_orch.results_ready.connect(self.set_base_results)
        self.search_orch.search_finished.connect(self.on_finished)

        self.img_actions = ImageActionManager(self, toast_fn=self._show_toast)

        # [修改 2] 連接訊號：當 AI 準備好時，執行 on_ai_loaded
        self.random_data_ready.connect(self.set_base_results)
        self.ai_ready.connect(self.on_ai_loaded)
        self.db_reloaded.connect(self.on_db_reloaded)

        from ui.action_handler import ActionHandler
        self.action_handler = ActionHandler(self)

        # [Signal Relay] ActionHandler 訊號接線
        ah = self.action_handler
        ah.requestEscapeClear.connect(self._on_escape_clear)
        ah.requestOCRShow.connect(self._on_ocr_show)
        ah.requestOCRToggleLock.connect(self._on_ocr_toggle_lock)
        ah.requestNavigate.connect(self._on_navigate)
        ah.requestClosePreview.connect(self._on_close_preview)
        ah.requestPreview.connect(self.toggle_preview)
        ah.requestCopy.connect(self._on_copy_toast)
        ah.requestHistoryToggle.connect(self._on_history_toggle)
        ah.requestFocusGallery.connect(lambda: self.list_view.setFocus())

        # [Signal Relay] SearchCapsule 訊號接線
        self.search_capsule.searchRequested.connect(self._on_search_requested)
        self.search_capsule.errorOccurred.connect(self.status.setText)
        self.search_capsule.set_history(self.search_history)

        QApplication.instance().installEventFilter(self)
        
        # 啟動背景載入 (這裡才會去建立 ImageSearchEngine)
        threading.Thread(target=self.load_engine, daemon=True).start()

        #  原生視窗記憶：精準還原大小、座標與最大化狀態
        from PyQt6.QtCore import QByteArray
        ui_state = self.config.get("ui_state", {})

        # 先設定合理預設尺寸，確保 normalGeometry 在 restoreGeometry() 前不為零值
        # 這樣即使還原為最大化狀態，unmaximize 時也能正確縮回
        self.resize(1280, 900)

        if "geometry" in ui_state and "window_state" in ui_state:
            try:
                ok = self.restoreGeometry(QByteArray.fromHex(ui_state["geometry"].encode('ascii')))
                if ok:
                    self.restoreState(QByteArray.fromHex(ui_state["window_state"].encode('ascii')))
                else:
                    print("[UI] restoreGeometry 回傳 False，使用預設大小")
            except Exception as e:
                print(f"[UI] 視窗狀態還原失敗: {e}")

        if ui_state.get("auto_scan_on_startup", True):
            self.indexer_worker.start()
        else:
            self.status.setText("自動掃描已停用。點擊左側 ⟳ 可手動更新。")

        # 將新的樣式表附加到現有的樣式表後
        current_stylesheet = self.styleSheet()

    def show_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.clip_model_changed.connect(self._on_clip_model_switched)

        # Phase 13: Collections 訊號 Lambda 接線
        fp = dialog._folders_page
        fp.addCollectionRequested.connect(
            lambda name, icon: self._on_add_collection_requested(fp, name, icon)
        )
        fp.removeCollectionRequested.connect(
            lambda col_id: self._on_remove_collection_requested(fp, col_id)
        )

        dialog.exec()

    def _on_add_collection_requested(self, folders_page, name: str, icon: str):
        if not self.engine:
            return
        ok = self.engine.add_collection(name, icon)
        if ok:
            folders_page.refresh_collections()
            self.sidebar.reload_collections(self.engine.get_collections())
        else:
            QMessageBox.warning(self, "新增失敗", f"「{name}」可能名稱重複或資料庫發生錯誤。")

    def _on_remove_collection_requested(self, folders_page, col_id: int):
        if not self.engine:
            return
        self.engine.remove_collection(col_id)
        folders_page.refresh_collections()
        self.sidebar.reload_collections(self.engine.get_collections())

    def _on_clip_model_switched(self, model_id: str):
        """接收 SettingsDialog.clip_model_changed 訊號，顯示友善提示後安全關閉。"""
        reply = QMessageBox.information(
            self,
            "模型切換成功",
            f"已切換至 {model_id}。\n\n為確保記憶體安全釋放，程式即將關閉，請手動重新啟動。",
            QMessageBox.StandardButton.Ok,
        )
        if reply == QMessageBox.StandardButton.Ok:
            QApplication.quit()

    def init_ui(self):
        from ui.main_window_ui import Ui_MainWindow
        ui = Ui_MainWindow()
        ui.setup_ui(
            self,
            GalleryListView=GalleryListView,
            SearchResultsModel=SearchResultsModel,
            ImageDelegate=ImageDelegate,
            InspectorPanel=InspectorPanel,
            SidebarWidget=SidebarWidget,
            PreviewOverlay=PreviewOverlay,
        )

    # ==========================================
    # init_ui() 結束，接下來是 MainWindow 的其他獨立函式
    # ==========================================

    def on_weights_changed(self, weight_config):
        q = self.input.text().strip()
        if q:
            #  [新增] 如果目前是「以圖搜圖」狀態，切換 Limit 時就重跑以圖搜圖
            if q.startswith("[Image]") and getattr(self, "current_image_search_path", None):
                self.start_image_search(self.current_image_search_path)
            else:
                self.start_search(triggered_by_slider=True)

    # ------------------------------------------------------------------
    #  ActionHandler 訊號接收器 (Signal Relay)
    # ------------------------------------------------------------------
    def _on_escape_clear(self):
        self.input.clearFocus()
        self.list_view.clearSelection()

    def _on_ocr_show(self, visible):
        self.preview_overlay.set_ocr_visible(visible)

    def _on_ocr_toggle_lock(self):
        self.is_ocr_locked = not self.is_ocr_locked
        self.preview_overlay.set_ocr_visible(self.is_ocr_locked)

    def _on_navigate(self, key_code):
        from ui.action_handler import ActionHandler
        ActionHandler.send_nav_key(self.list_view, key_code)

    def _on_close_preview(self):
        self.preview_overlay.hide()
        self.is_ocr_locked = False

    def _on_copy_toast(self, count):
        if count == 1:
            self._show_toast("已複製 1 個檔案到剪貼簿")
        else:
            self._show_toast(f"已複製 {count} 個檔案到剪貼簿")

    def _on_files_dropped_to_collection(self, collection_id: int, file_paths: list):
        """接收 SidebarWidget.files_dropped_to_collection，將圖片寫入虛擬資料夾。"""
        if not self.engine:
            return
        ok = self.engine.add_to_virtual_folder(collection_id, file_paths)
        if ok:
            count = len(file_paths)
            self.sidebar.reload_collections(self.engine.get_collections())
            self._show_toast(f"已加入 {count} 張圖片至虛擬資料夾")
        else:
            self._show_toast("加入失敗，請稍後再試")

    def _on_history_toggle(self, show):
        if show:
            self.search_capsule.show_history_popup()
        else:
            self.history_list.hide()

    # ------------------------------------------------------------------
    #  SearchCapsule 訊號接收器 (Signal Relay)
    # ------------------------------------------------------------------
    def _on_search_requested(self, payload: dict):
        """接收 SearchCapsule.searchRequested 訊號並轉發至 start_search"""
        q = payload.get("query", "").strip()
        if not q:
            return
        # 將 payload 中的 use_ocr 暫存，供 start_search 使用
        self._pending_use_ocr = payload.get("use_ocr", True)
        self.start_search()

    # ------------------------------------------------------------------
    #  導航回呼 (供 NavigationManager 呼叫)
    # ------------------------------------------------------------------
    def _nav_snapshot(self):
        """擷取當前頁面的完整快照 (包含滾輪位置)"""
        return {
            "query": self.input.text().strip(),
            "folder_path": self.current_folder_path,
            "breadcrumb": self.breadcrumb_lbl.text(),
            "scroll_pos": self.list_view.verticalScrollBar().value(),
            "image_path": getattr(self, "current_image_search_path", None),
            "multi_vector_features": getattr(self, "current_multi_vector_features", None),
        }

    def _nav_apply(self, state):
        """套用紀錄中的狀態並執行對應的載入"""
        self.current_folder_path = state["folder_path"]
        self.breadcrumb_lbl.setText(state["breadcrumb"])

        mv = state.get("multi_vector_features")
        if mv:
            pos_features, neg_features = mv
            self.start_multi_vector_search(pos_features, neg_features)
        elif state["image_path"]:
            self.start_image_search(state["image_path"])
        elif state["query"]:
            self.input.setText(state["query"])
            self.start_search(triggered_by_slider=False)
        else:
            self.input.setText("")
            self._apply_folder_filter(state["folder_path"])

    def navigate_back(self):
        self.nav.go_back()

    def navigate_forward(self):
        self.nav.go_forward()

    def refresh_sidebar(self):
        """通知側邊欄更新資料夾狀態與排序"""
        if self.engine:
            stats = self.engine.get_folder_stats()
            config_folders = self.config.get("source_folders")
            self.sidebar.update_folders(stats, config_folders)

    # [修復] 加回此函式，讓側邊欄的 + 號能運作，並正確更新畫面
    def on_add_folder_clicked(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            if self.config.add_source_folder(folder):
                # 1. 立即更新側邊欄
                self.refresh_sidebar()
                # 2. 自動觸發一次重新掃描，讓使用者不用再點「⟳」按鈕
                self.on_refresh_clicked() 
            else:
                QMessageBox.warning(self, "重複", "此資料夾已經存在。")

    # [新增] 處理重新整理點擊事件
    def on_refresh_clicked(self):
        # 1. 檢查是否已經在執行中
        if self.indexer_worker.isRunning():
            QMessageBox.warning(self, "Busy", "Indexing is already in progress.")
            return

        raw_folders = self.config.get("source_folders")
        if not raw_folders:
            QMessageBox.information(self, "No Folders", "No source folders configured.")
            return

        # 直接將完整的設定字典交給 Worker
        self.indexer_worker.folders = raw_folders
        
        self.status.setText("Rescanning folders...")
        self.indexer_worker.start()

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
        """用戶主動點擊側邊欄時觸發：記錄導航歷史並顯示"""
        if not self.engine: return
        self.nav.push()
        self._apply_folder_filter(path)

    def _apply_folder_filter(self, path):
        """純顯示邏輯，不操作導航堆疊，供 nav_apply 與 on_folder_filter 共用"""
        if not self.engine: return

        self.current_folder_path = path
        
        #  [修改] 根據側邊欄自動切換下拉選單預設值
        self.inspector_panel.combo_search_scope.blockSignals(True)
        if path == "ALL":
            self.inspector_panel.combo_search_scope.setCurrentIndex(1) # 側邊欄點ALL，右邊自動切到「全域」
        else:
            self.inspector_panel.combo_search_scope.setCurrentIndex(0) # 側邊欄點特定資料夾，右邊自動切到「目前資料夾」
        self.inspector_panel.combo_search_scope.blockSignals(False)
        
        print(f"Filtering by: {path}")

        self.inspector_panel.combo_sort.blockSignals(True)
        self.inspector_panel.combo_sort.setCurrentText("日期")
        self.inspector_panel.btn_sort_order.setText("↓")
        self.inspector_panel.combo_sort.blockSignals(False)
        
        # ==========================================
        # [修改] 還原麵包屑標題，並清空搜尋框的殘留文字
        # ==========================================
        self.input.setText("") 
        
        # 1. 如果是 "ALL"，顯示全部 (依時間排序)
        if path == "ALL":
            self.breadcrumb_lbl.setText("Gallery")
            all_imgs = self.engine.get_all_images_sorted()
            self.set_base_results(all_imgs)
            self.status.setText(f"Showing all {len(all_imgs)} images")
            return

        # 2. 如果是虛擬資料夾 (格式: "col:{id}")
        if path.startswith("col:"):
            try:
                col_id = int(path.split(":", 1)[1])
            except (IndexError, ValueError):
                return
            results = self.engine.get_virtual_folder_images(col_id)
            # 從 collections 取得名稱作為麵包屑
            collections = self.engine.get_collections()
            col_name = next((name for cid, name, *_ in collections if cid == col_id), f"Collection {col_id}")
            self.breadcrumb_lbl.setText(f"Collection: {col_name}")
            self.set_base_results(results)
            self.status.setText(f"Collection: {col_name} ({len(results)} 張圖片)")
            return

        # 3. 篩選特定資料夾
        self.breadcrumb_lbl.setText(f"Folder: {os.path.basename(path)}")
        
        # 這邊簡單用 Python list comprehension 過濾 (高效能做法建議在 Engine 寫 SQL)
        if self.engine.data_store:
            # 正規化路徑並加上分隔符，防止 D:\img 誤匹配 D:\img-backup
            norm_path = os.path.normpath(path)
            prefix = norm_path + os.sep
            filtered = [
                item for item in self.engine.data_store
                if os.path.normpath(item["path"]).startswith(prefix)
            ]
            
            # 轉換格式給 Model
            results = []
            for item in filtered:
                results.append({
                    "score": 0.0,
                    "path": item["path"],
                    "filename": item["filename"],
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),   #  補上
                    "height": item.get("height", 0)  #  補上
                })
            
            # 按時間排序
            results.sort(key=lambda x: x["mtime"], reverse=True)
            
            # 釘選圖無視資料夾範圍：合併至頂端
            results = self.engine._merge_pinned(results)

            self.set_base_results(results)
            self.status.setText(f"Folder: {os.path.basename(path)} ({len(results)} items)")

    def eventFilter(self, obj, event):
        ah = self.action_handler
        cfg = ah.get_config()

        # 1. 鍵盤按下 (KeyPress) — 純分流
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()

            if key == Qt.Key.Key_Escape:
                if ah.handle_escape():
                    return True

            if key == Qt.Key.Key_Shift:
                return ah.handle_shift_press(cfg["ocr_mode"])

            focused_widget = QApplication.focusWidget()
            is_typing = isinstance(focused_widget, QLineEdit)

            if not is_typing and QApplication.activeWindow() == self:
                if key in (Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D):
                    return ah.handle_wasd(key, cfg["nav_mode"])
                elif key == Qt.Key.Key_Space:
                    return ah.handle_space()

            if key == Qt.Key.Key_C and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                result = ah.handle_copy()
                if result:
                    return True

        # 2. 鍵盤放開 (KeyRelease)
        if event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Shift:
                return ah.handle_shift_release(cfg["ocr_mode"])

        # 3. 滑鼠點擊 (MouseButtonPress)
        if event.type() == QEvent.Type.MouseButtonPress:
            ah.handle_mouse_press(obj, event)

        return super().eventFilter(obj, event)

# ==========================================
# 請找到 MainWindow 類別中的 toggle_preview 與 on_selection_changed 函式並替換
# ==========================================

    def toggle_preview(self):
        if self.preview_overlay.isVisible():
            self.preview_overlay.hide()
            self.is_ocr_locked = False 
        else:
            index = self.list_view.currentIndex()
            if index.isValid():
                item = index.data(Qt.ItemDataRole.UserRole)
                if item:
                    self.is_ocr_locked = False
                    current_query = self.input.text().strip()
                    is_precise = self.config.get("ui_state", {}).get("precise_ocr_highlight", False)
                    
                    #  從 Model 取出 L1 快取小圖
                    l1_pixmap = self.model._thumbnail_cache.get(item.path)
                    
                    #  傳遞給顯示層
                    self.preview_overlay.show_image(item, current_query, is_precise, l1_pixmap)
                    self.preview_overlay.set_ocr_visible(False)

    def toggle_inspector(self):
        """控制右側面板的展開與收合"""
        if self.inspector_panel.isVisible():
            self.inspector_panel.hide()
            self.btn_toggle_inspector.setChecked(False)
        else:
            self.inspector_panel.show()
            self.btn_toggle_inspector.setChecked(True)
            
        # 開關面板會改變畫廊寬度，必須通知 QListView 重新計算網格排版
        QTimer.singleShot(0, self.adjust_layout)

    def on_selection_changed(self, current, previous):
        # 1. 更新右側面板資訊 (如果面板存在且有選取項目)
        if hasattr(self, 'inspector_panel') and current.isValid():
            item = current.data(Qt.ItemDataRole.UserRole)
            if item:
                self.inspector_panel.update_info(item)

        # 2. 預覽畫面同步邏輯 (沉浸模式 WASD 切換)
        nav_mode = self.config.get("ui_state", {}).get("preview_wasd_mode", "nav")
        if self.preview_overlay.isVisible() and nav_mode == "sync":
            if current.isValid():
                item = current.data(Qt.ItemDataRole.UserRole)
                if item:
                    # 抓出目前的搜尋字與精確模式狀態
                    current_query = self.input.text().strip()
                    is_precise = self.config.get("ui_state", {}).get("precise_ocr_highlight", False)
                    
                    #  核心修改 1：從 Model 取出 L1 快取小圖
                    l1_pixmap = self.model._thumbnail_cache.get(item.path)
                    
                    #  核心修改 2：完整傳遞給顯示層，實現光速預覽！
                    self.preview_overlay.show_image(item, current_query, is_precise, l1_pixmap)
                    
                    #  [加碼優化] 保持 OCR 鎖定狀態
                    self.preview_overlay.set_ocr_visible(self.is_ocr_locked)

    

    


    def apply_gallery_sort(self):
        """對目前的 Gallery 圖片進行洗牌排序"""
        # 如果目前畫面上沒圖片，就不需要排
        #  [修正] 將 self.model.items 改為 self.model.all_items
        if not hasattr(self, 'model') or not self.model.all_items:
            return

        # 1. 取得使用者的設定狀態
        sort_by = self.inspector_panel.combo_sort.currentText()
        is_descending = (self.inspector_panel.btn_sort_order.text() == "↓")

        import os

        # 2. 根據不同的條件，定義 Python list sort 的 key 函數
        # is_pinned 作為所有排序模式的第一優先鍵，確保釘選圖永遠置頂
        if sort_by == "搜尋相關度":
            key_func = lambda item: (item.is_pinned, item.is_ocr_match, item.score)
        elif sort_by == "日期":
            key_func = lambda item: (item.is_pinned, item.mtime)
        elif sort_by == "名稱":
            key_func = lambda item: (item.is_pinned, item.filename.lower())
        elif sort_by == "類型":
            key_func = lambda item: (item.is_pinned, os.path.splitext(item.filename)[1].lower())
        elif sort_by == "大小":
            def get_size(item):
                try:
                    return item.is_pinned, os.path.getsize(item.path)
                except:
                    return item.is_pinned, 0
            key_func = get_size
        else:
            key_func = lambda item: (item.is_pinned, item.mtime)

        # 3. 呼叫 Model 的排序方法
        self.model.sort_items(key_func, reverse=is_descending)
        
        #  4. 防禦：還原滾輪期間不回頂，其他情況才自動滾回最上方
        if not getattr(self, '_nav_restoring_scroll', False) and self.nav.pending_scroll_pos is None:
            self.list_view.scrollToTop()

    # ==========================================
    #  [NEW] 核心過濾器與資料派發機制
    # ==========================================
    def set_base_results(self, results):
        """所有搜尋或載入資料的統一入口，保存最原始的結果，並自動套用目前的過濾器"""
        self.last_search_results = results
        self.apply_current_filters_and_show()

    def apply_current_filters_and_show(self, test_mode=False):
        """套用時間等過濾器到 self.last_search_results，然後丟給 Model 顯示"""
        filtered = self.last_search_results
        
        # 1. 時間區間過濾
        if self.active_time_range:
            start_ts, end_ts = self.active_time_range
            filtered = [item for item in filtered if start_ts <= item["mtime"] <= end_ts]
            
        # 2. 長寬比過濾 (容差 5%)
        aspect_mode = self.inspector_panel.combo_aspect.currentText()
        if aspect_mode != "不限比例":
            temp_filtered = []
            for item in filtered:
                w, h = item.get("width", 0), item.get("height", 0)
                if w > 0 and h > 0:
                    ratio = w / h
                    if aspect_mode == "橫圖 (Landscape)" and ratio > 1.05:
                        temp_filtered.append(item)
                    elif aspect_mode == "直圖 (Portrait)" and ratio < 0.95:
                        temp_filtered.append(item)
                    elif aspect_mode == "正方形 (Square)" and 0.95 <= ratio <= 1.05:
                        temp_filtered.append(item)
            filtered = temp_filtered
            
        # ==========================================
        #  3. UI 顯示數量限制 (Limit Truncation)
        # 這是實作「超額抓取 + 精準裁切」的最關鍵一步
        # ==========================================
        limit_text = self.inspector_panel.combo_limit_panel.currentText()
        if limit_text != "All":
            limit_val = int(limit_text)
            filtered = filtered[:limit_val]

        if test_mode:
            return len(filtered) 
            
        # 4. 丟給畫面更新
        self.model.set_search_results(filtered)
        
        # 5. 如果有滾輪還原需求，先預先排程（在 sort 之前），避免被 scrollToTop 覆蓋
        if self.nav.pending_scroll_pos is not None:
            pos = self.nav.pending_scroll_pos
            self.nav.pending_scroll_pos = None
            self._nav_restoring_scroll = True
            def _do_restore():
                self.list_view.verticalScrollBar().setValue(pos)
                self._nav_restoring_scroll = False
            QTimer.singleShot(80, _do_restore)

        # 6. 順便套用目前的排序設定
        self.apply_gallery_sort()

        return len(filtered)

    def apply_time_filter_to_gallery(self, start_ts, end_ts):
        """點擊 [套用結果]：測試過濾數量，若為 0 顯示防呆警告，否則套用"""
        # 先暫存原本的時間區間 (為了防呆退回)
        old_range = self.active_time_range
        self.active_time_range = (start_ts, end_ts)
        
        # 進入 Test Mode 測試這刀切下去剩幾張圖
        count = self.apply_current_filters_and_show(test_mode=True)
        
        if count > 0:
            # 成功！正式更新畫面
            self.apply_current_filters_and_show(test_mode=False)
            self.inspector_panel.calendar_widget.set_status(f"✅ 已成功過濾，顯示 {count} 張圖片。", "success")
            self.status.setText(f"Filtered: {count} images")
        else:
            # 防呆啟動：找不到圖，退回上一個狀態並報錯，不收合日曆
            self.active_time_range = old_range
            self.inspector_panel.calendar_widget.set_status(f"⚠️ 您的搜尋結果中，此時間段內沒有圖片。", "error")

    def clear_time_filter(self):
        """點擊 [清除]：移除過濾器並還原畫廊"""
        self.active_time_range = None
        self.apply_current_filters_and_show()
        #  [修正] 將 len(self.model.items) 改為 len(self.model.all_items)
        self.status.setText(f"Time filter cleared. Showing {len(self.model.all_items)} images")

    def search_by_time_range(self, start_ts, end_ts):
        """點擊 [直接搜尋]：忽略關鍵字，直接全域抓出該時段的圖，並加入防呆檢查"""
        if not self.engine: return
        
        # 1. 先暫存目前的畫廊狀態 (為了防呆退回)
        old_results = self.last_search_results
        old_range = self.active_time_range

        # 2. 模擬全域搜尋狀態
        self.last_search_results = self.engine.get_all_images_sorted()
        self.active_time_range = (start_ts, end_ts)
        
        # 3. 進入 Test Mode 測試這刀切下去剩幾張圖 (會連同長寬比等設定一起算)
        count = self.apply_current_filters_and_show(test_mode=True)
        
        if count > 0:
            # 成功！正式更新畫面
            self.input.setText("") # 清空關鍵字搜尋框
            self.apply_current_filters_and_show(test_mode=False)
            
            # 強制切換右側排序選單為「日期」，倒序 (↓) (阻擋訊號以避免重複洗牌)
            self.inspector_panel.combo_sort.blockSignals(True)
            self.inspector_panel.combo_sort.setCurrentText("日期")
            self.inspector_panel.btn_sort_order.setText("↓")
            self.inspector_panel.combo_sort.blockSignals(False)
            self.apply_gallery_sort() # 正式套用排序
            
            self.inspector_panel.calendar_widget.set_status(f"✅ 搜尋完成，已列出 {count} 張圖片。", "success")
            self.status.setText(f"Direct Time Search: {count} items")
        else:
            # 防呆啟動：資料庫中找不到圖，退回上一個狀態並報錯，不變動畫廊
            self.last_search_results = old_results
            self.active_time_range = old_range
            self.inspector_panel.calendar_widget.set_status(f"⚠️ 資料庫中，此時間段內沒有符合的圖片。", "error")

    def on_ai_loaded(self):
        """當 AI 模型載入完成後被呼叫 (會在主執行緒執行)"""
        count = len(self.engine.data_store) if self.engine else 0
        self.status.setText(f"System Ready ({count} images)")
        self.progress.hide()
        
        # [新增] AI 準備好後，關閉工作列的進度條狀態
        self.taskbar_ctrl.set_state(TBPF_NOPROGRESS)
        
        # 這裡會去抓取資料夾統計，並建立二級選單的按鈕
        if self.engine:
            self.refresh_sidebar()
            self.sidebar.reload_collections(self.engine.get_collections())

            self._apply_folder_filter(self.current_folder_path)
    
    def update_status(self, text):
        self.status.setText(text)

    def update_progress(self, current, total):
        self.progress.show()
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        
        # [新增] 同步更新工作列上的進度百分比，並確保狀態為「正常 (綠色進度條)」
        self.taskbar_ctrl.set_state(TBPF_NORMAL)
        self.taskbar_ctrl.set_progress(current, total)

    def on_scan_finished(self, added, deleted):
        if added > 0 or deleted > 0:
            print(f"[Indexer] Scan found {added} new, {deleted} deleted.")
            #  [防呆修復] 移除原本這裡同步呼叫 load_data_from_db 的動作
            # 避免在開始索引前卡死畫面，統一交給 on_indexing_finished 處理！
        else:
            print("[Indexer] No changes detected.")

    def on_indexing_finished(self):
        self.progress.hide()
        
        # [新增] 索引任務結束，關閉工作列進度條
        self.taskbar_ctrl.set_state(TBPF_NOPROGRESS)
        
        self.status.setText("Index Updated.")
        self.trigger_background_db_reload() #  觸發雙緩衝背景載入

    def trigger_background_db_reload(self):
        """ [方案 B：雙緩衝核心] 在背景執行緒讀取資料庫，確保 UI 與搜尋功能不中斷"""
        if not self.engine: return
        self.status.setText("Synchronizing database in background...")
        
        def bg_reload():
            print("[Engine] Reloading engine data in background (Double Buffering)...")
            self.engine.load_data_from_db() # 此處內部已實作 Atomic Swap
            
            #  [關鍵修復] 改為發送空訊號，讓主執行緒自己去撈，徹底杜絕跨執行緒崩潰
            self.db_reloaded.emit()
            
        threading.Thread(target=bg_reload, daemon=True).start()
    
    def on_db_reloaded(self):
        """背景載入完畢，安全跳回主執行緒更新畫面"""
        if not self.engine: return
        
        #  [修正] 不要強制切回 ALL，而是維持目前所在的資料夾並重新整理！
        self._apply_folder_filter(self.current_folder_path)
        self.refresh_sidebar()

    # 右鍵選單邏輯
    def show_context_menu(self, pos):
        index = self.list_view.indexAt(pos)
        if index.isValid():
            item = index.data(Qt.ItemDataRole.UserRole)
            if not item: return
            engine = self.engine
            is_pinned = engine.is_pinned(item.path) if engine else False
            menu = self.img_actions.build_item_menu(
                index, item,
                on_search_similar=self.start_image_search,
                on_toggle_pin=self._on_toggle_pin if engine else None,
                is_pinned=is_pinned,
            )
        else:
            menu = self.img_actions.build_view_menu(
                self, self.current_view_mode, on_change_mode=self.change_view_mode)
        menu.exec(self.list_view.mapToGlobal(pos))

    def _on_toggle_pin(self, file_path: str):
        """切換釘選狀態：僅更新該卡片的 is_pinned 旗標並局部重繪，不重建列表亦不跳頂。"""
        if not self.engine:
            return
        new_state = self.engine.toggle_pin(file_path)
        # 在 model 中找到對應 row，就地更新旗標並發射局部 dataChanged
        row = self.model.path_to_row.get(file_path)
        if row is not None and 0 <= row < len(self.model.all_items):
            self.model.all_items[row].is_pinned = new_state
            idx = self.model.index(row, 0)
            self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.UserRole])
        # 同步更新 last_search_results，維持後續過濾/合併操作的一致性
        for r in self.last_search_results:
            if r.get('path') == file_path:
                r['is_pinned'] = new_state
                break

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

        #  [新增終極鎖定] 直接告訴 ListView 每個網格的絕對大小
        # 網格大小 = 卡片本身大小 + 右邊和下方的間距
        grid_w = self.current_card_size.width() + space
        grid_h = self.current_card_size.height() + space
        self.list_view.setGridSize(QSize(grid_w, grid_h))

    def on_item_clicked(self, index):
        if not index.isValid(): return
        item = index.data(Qt.ItemDataRole.UserRole)
        if item: self.current_selected_path = item.path

    def on_item_double_clicked(self, index):
        if not index.isValid(): return
        item = index.data(Qt.ItemDataRole.UserRole)
        if item:
            self.img_actions.open_file(item.path)

    # ------------------------------------------------------------------
    #  Toast 回饋（供 ImageActionManager callback 使用）
    # ------------------------------------------------------------------
    def _show_toast(self, message: str, duration_ms: int = 1500) -> None:
        if not getattr(self, '_is_toast_active', False):
            self._previous_status_text = self.status.text()
        self._is_toast_active = True
        self.status.setText(message)

        def _restore():
            self.status.setText(getattr(self, '_previous_status_text', 'System Ready'))
            self._is_toast_active = False

        QTimer.singleShot(duration_ms, _restore)

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
        # 同步更新 SearchCapsule 內部歷史快取
        self.search_capsule.set_history(self.search_history)

    def delete_history_item(self, text):
        if text in self.search_history: self.search_history.remove(text); self.save_history_to_file()
        self.search_capsule.set_history(self.search_history)
        self.search_capsule.show_history_popup()
    
    def trigger_history_search(self, text): 
        self.input.setText(text); self.start_search()

    def show_history_popup(self):
        """委派給 SearchCapsule 元件處理"""
        self.search_capsule.show_history_popup()
    
    def load_engine(self):
        try:
            #self.status.setText("Loading Database...")
            
            # [新增] 載入模型時，工作列顯示綠色流光 (跑動條)
            self.taskbar_ctrl.set_state(TBPF_INDETERMINATE)
            
            # 正確建立 Engine 實例
            self.engine = ImageSearchEngine(self.config)
            self.search_orch.engine = self.engine   # 將引擎注入 Orchestrator
            self.img_actions.engine = self.engine   # 將引擎注入 ActionManager
            
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

    # ------------------------------------------------------------------
    #  搜尋 UI 前置：重設進度條 / 狀態列 / 排序下拉
    # ------------------------------------------------------------------
    def _prepare_search_ui(self, status_text: str, breadcrumb_text: str) -> None:
        self.progress.show()
        self.progress.setRange(0, 0)
        self.status.setText(status_text)
        self.breadcrumb_lbl.setText(breadcrumb_text)
        self.inspector_panel.combo_sort.blockSignals(True)
        self.inspector_panel.combo_sort.setCurrentText("搜尋相關度")
        self.inspector_panel.btn_sort_order.setText("↓")
        self.inspector_panel.combo_sort.blockSignals(False)

    def start_search(self, *args, triggered_by_slider=False):
        #  新增：如果是使用者手動按 Enter 搜尋，立刻交出焦點釋放 WASD 快捷鍵
        if not triggered_by_slider:
            self.input.clearFocus()
            
        q = self.input.text().strip()
        if not q or not self.engine: return
        
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', q))
        if has_chinese and not getattr(self.engine, 'is_hf_tokenizer', True):
            if not triggered_by_slider:
                QMessageBox.warning(self, "不支援的語言", "您目前使用的 AI 模型僅支援「英文」搜尋...")
            return
        
        if not triggered_by_slider:

            if not self.nav.is_navigating:
                self.nav.push()

            self.current_image_search_path = None
            self.current_multi_vector_features = None
            self.add_to_history(q)
            self.search_capsule.hide_history()
            self._prepare_search_ui("Searching...", "Search Results")

        # 從 SearchCapsule payload 或按鈕狀態取得 use_ocr
        use_ocr = getattr(self, '_pending_use_ocr', self.btn_ocr_toggle.isChecked())
        self._pending_use_ocr = None  # 消費後清除

        fetch_k, target_folder = self.search_orch.resolve_search_params(
            self.inspector_panel.combo_limit_panel.currentText(),
            self.inspector_panel.combo_search_scope.currentIndex(),
            self.current_folder_path)

        self.search_orch.submit(
            q, search_mode="text",
            use_ocr=use_ocr,
            weight_config=self.inspector_panel.get_weight_config(),
            folder_path=target_folder, fetch_k=fetch_k,
        )

    def start_image_search(self, image_path):
        if not self.engine: return

        if not self.nav.is_navigating:
            self.nav.push()
        self.current_image_search_path = image_path
        self.current_multi_vector_features = None

        self.history_list.hide()
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        self._prepare_search_ui("Searching by Image...", "Similar Images")

        fetch_k, target_folder = self.search_orch.resolve_search_params(
            self.inspector_panel.combo_limit_panel.currentText(),
            self.inspector_panel.combo_search_scope.currentIndex(),
            self.current_folder_path)

        self.search_orch.submit(
            image_path, search_mode="image",
            folder_path=target_folder, fetch_k=fetch_k,
        )

    def start_multi_vector_search(self, pos_features, neg_features):
        if not self.engine: return
        if not self.nav.is_navigating: self.nav.push()

        self.current_image_search_path = None
        self.current_multi_vector_features = (pos_features, neg_features)

        self.history_list.hide()
        self.input.setText(f"[Multi-Vector] Pos:{len(pos_features)} Neg:{len(neg_features)}")
        self._prepare_search_ui("Calculating Vector Math...", "Vector Arithmetic Results")

        fetch_k, target_folder = self.search_orch.resolve_search_params(
            self.inspector_panel.combo_limit_panel.currentText(),
            self.inspector_panel.combo_search_scope.currentIndex(),
            self.current_folder_path)

        self.search_orch.submit(
            {'pos': pos_features, 'neg': neg_features},
            search_mode="multi_vector",
            folder_path=target_folder, fetch_k=fetch_k,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        
        # 隱藏浮動視窗 (加上 hasattr 防呆檢查，避免初始化時崩潰)
        if hasattr(self, 'history_list'):
            self.history_list.hide()
            
        if hasattr(self, 'preview_overlay') and self.preview_overlay.isVisible():
            self.preview_overlay.resize(self.size())
            
        # [關鍵] 視窗大小改變時，Viewport 寬度也會變，必須重算
        QTimer.singleShot(0, self.adjust_layout)

    def showEvent(self, event):
        super().showEvent(event)
        # 延遲觸發，確保 Qt 的幾何運算已經完成
        QTimer.singleShot(10, self.adjust_layout)

    def closeEvent(self, event):
        ui_state = self.config.get("ui_state", {})

        # 視窗幾何（含最大化 + normalGeometry）統一交由 saveGeometry() 處理
        ui_state["geometry"] = self.saveGeometry().toHex().data().decode('ascii')
        ui_state["window_state"] = self.saveState().toHex().data().decode('ascii')

        # 其餘 UI 狀態
        ui_state["sidebar_expanded"] = self.sidebar.is_expanded
        ui_state["view_mode"] = getattr(self, 'current_view_mode', 'large')

        # 清除已被 saveGeometry() 取代的舊欄位，避免 config.json 殘留臟資料
        for old_key in ["window_width", "window_height", "is_maximized"]:
            ui_state.pop(old_key, None)

        # 一次性原子寫入，避免兩次 set 之間的狀態不一致
        self.config.set("ui_state", ui_state)
        super().closeEvent(event)


    def on_finished(self, elapsed, total): self.progress.hide(); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

class OnboardingDialog(QDialog):
    """首次開啟的引導與自動硬體設定面板"""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("EyeSeeMore - Welcome")
        self.setFixedSize(600, 450)
        
        #  重構魔法：核發身分證，背景顏色交給 QSS
        self.setObjectName("OnboardingDialog")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 視覺引導圖示
        lbl_icon = QLabel("🖼️")
        lbl_icon.setStyleSheet("font-size: 80px; background: transparent; margin-bottom: 10px;")
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_icon)

        title = QLabel("尚未加入任何圖片資料夾")
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("讓 EyeSeeMore 透過 AI 幫您理解與檢索所有圖片。\n請先新增一個包含圖片的資料夾來建立索引。")
        subtitle.setStyleSheet("color: #aaaaaa; font-size: 14px; background: transparent;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(30)
        
        # 核心動作按鈕
        btn_add = QPushButton("➕ 立即新增圖片資料夾")
        btn_add.setFixedHeight(50)
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.setStyleSheet("""
            QPushButton { background-color: #005fb8; color: white; font-weight: bold; font-size: 16px; border-radius: 8px; } 
            QPushButton:hover { background-color: #0078d4; }
        """)
        btn_add.clicked.connect(self.on_add_folder_clicked) 
        layout.addWidget(btn_add)

        # 執行背景自動化設定
        self.auto_configure_hardware()

    def auto_configure_hardware(self):
        """在背景默默完成硬體偵測與預設值設定，不干擾使用者"""
        # 1. OCR 預設為關閉 (避免首次啟動偷載模型)
        self.config.set("use_ocr", False)
        
        # 2. GPU 自動化偵測 (DirectML)
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if 'DmlExecutionProvider' in providers:
            self.config.set("use_gpu_ocr", True)
            print("[Auto-Config] Detected DirectML. GPU Acceleration Enabled.")
        else:
            self.config.set("use_gpu_ocr", False)
            print("[Auto-Config] DirectML not found. Fallback to CPU.")

    def on_add_folder_clicked(self):
        from PyQt6.QtWidgets import QFileDialog
        # 直接呼叫作業系統的選擇資料夾視窗
        folder = QFileDialog.getExistingDirectory(self, "選擇要加入的圖片資料夾")
        
        if folder:
            # 將資料夾寫入設定檔
            self.config.add_source_folder(folder)
            # 關閉對話框，這會讓程式自然進入 MainWindow 並觸發掃描
            self.accept()

class TransparentDragListWidget(QListWidget):
    """自訂的 ListWidget，用於在拖曳時產生半透明的視覺效果"""
    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item: return super().startDrag(supportedActions)
        drag = QDrag(self)
        mimeData = self.model().mimeData(self.selectedIndexes())
        drag.setMimeData(mimeData)
        rect = self.visualItemRect(item)
        pixmap = QPixmap(rect.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap, QPoint(), QRegion(rect))
        alpha_pixmap = QPixmap(pixmap.size())
        alpha_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(alpha_pixmap)
        painter.setOpacity(0.5)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        drag.setPixmap(alpha_pixmap)
        mouse_pos = self.viewport().mapFromGlobal(QCursor.pos())
        hotspot = mouse_pos - rect.topLeft()
        drag.setHotSpot(hotspot)
        drag.exec(supportedActions, Qt.DropAction.MoveAction)

class SettingsDialog(QDialog):
    """設定對話框（精簡容器版）— 僅負責 nav ↔ stack 的連結，
    所有頁面邏輯已移至 ui/settings_pages/ 下各自的模組。"""

    clip_model_changed = pyqtSignal(str)   # model_id，由 AIEnginePage 透傳

    def __init__(self, main_window):
        super().__init__(main_window)
        mw = main_window
        trans = mw.config.translator

        self.setWindowTitle(trans.t("settings", "window_title", "設定 (Settings)"))
        self.resize(800, 600)
        self.setObjectName("SettingsDialog")

        # ── 共用上下文：注入到所有子頁面 ──────────────────────────────────
        ctx = {
            "config":             mw.config,
            "translator":         trans,
            "engine":             mw.engine,
            "theme_manager":      mw.theme_manager,
            "change_view_mode":   mw.change_view_mode,
            "reload_index":       mw.trigger_background_db_reload,
            "refresh_sidebar":    mw.refresh_sidebar,
            "on_refresh_clicked": mw.on_refresh_clicked,
            "current_view_mode":  mw.current_view_mode,
            "ocr_worker_class":   OCRImportWorker,
        }

        # ── 跨頁面回呼 hub（在頁面全部建立後填入）─────────────────────────
        hub: dict = {}
        ctx["hub"] = hub

        # ── 建立導覽列 ────────────────────────────────────────────────────
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(200)
        self.nav_list.setObjectName("SettingsNavList")

        nav_labels = [
            trans.t("settings", "nav_folders",     "📁 資料夾管理"),
            trans.t("settings", "nav_ai",           "🧠 AI 引擎設定"),
            trans.t("settings", "nav_appearance",   "🖥️ 介面與顯示"),
            trans.t("settings", "nav_hotkeys",      "⌨️ 操作與快捷鍵"),
            trans.t("settings", "nav_performance",  "⚡ 效能調整"),
            trans.t("settings", "nav_auto_tasks",   "🕒 自動任務"),
            trans.t("settings", "nav_language",     "🌍 語言與翻譯"),
            trans.t("settings", "nav_about",        "ℹ️ 關於與說明"),
        ]
        for label in nav_labels:
            self.nav_list.addItem(label)
        main_layout.addWidget(self.nav_list)

        self.stack = QStackedWidget()
        self.stack.setObjectName("SettingsStack")
        main_layout.addWidget(self.stack, stretch=1)
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        # ── 實例化各頁面並加入 QStackedWidget ────────────────────────────
        from ui.settings_pages.folders_page     import FoldersPage
        from ui.settings_pages.ai_engine_page   import AIEnginePage
        from ui.settings_pages.appearance_page  import AppearancePage
        from ui.settings_pages.hotkeys_page     import HotkeysPage
        from ui.settings_pages.performance_page import PerformancePage
        from ui.settings_pages.auto_tasks_page  import AutoTasksPage
        from ui.settings_pages.language_page    import LanguagePage
        from ui.settings_pages.about_page       import AboutPage

        self._folders_page    = FoldersPage(ctx)
        self._ai_page         = AIEnginePage(ctx)
        self._appearance_page = AppearancePage(ctx)
        self._hotkeys_page    = HotkeysPage(ctx)
        self._perf_page       = PerformancePage(ctx)
        self._auto_page       = AutoTasksPage(ctx)
        self._lang_page       = LanguagePage(ctx)
        self._about_page      = AboutPage(ctx)

        for page in (
            self._folders_page, self._ai_page, self._appearance_page,
            self._hotkeys_page, self._perf_page, self._auto_page,
            self._lang_page, self._about_page,
        ):
            self.stack.addWidget(page)

        # ── 填入跨頁面 hub ────────────────────────────────────────────────
        hub["refresh_ocr_status"]    = self._ai_page.refresh_ocr_status
        hub["refresh_folder_list"]   = self._folders_page.refresh_folder_list
        hub["navigate_to_ai_ocr_tab"] = self._navigate_to_ai_ocr_tab

        # ── 透傳 AIEnginePage 的 clip_model_changed ───────────────────────
        self._ai_page.clip_model_changed.connect(self.clip_model_changed)

        self.nav_list.setCurrentRow(0)

    def _navigate_to_ai_ocr_tab(self):
        """跨頁面跳轉：切換至 AI 引擎頁面的 OCR 分頁。"""
        self.nav_list.setCurrentRow(1)          # AI 引擎 = index 1
        self._ai_page.ai_tabs.setCurrentIndex(1)  # OCR 分頁 = index 1

if __name__ == "__main__":
    app_config = ConfigManager()

    current_lang = app_config.get("ui_state", {}).get("language", "zh_TW")
    app_config.translator = Translator(current_lang)

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        
    app = QApplication(sys.argv)
    
    #  [修改] 棄用寫死的 WIN11_STYLESHEET，改用 ThemeManager
    theme_manager = ThemeManager(app_config)
    theme_manager.apply_theme(app, theme_manager.current_theme_id)

    is_first_run = not app_config.get("source_folders")
    if is_first_run:
        onboarding = OnboardingDialog(app_config)
        onboarding.exec() 

    w = MainWindow(app_config) 
    # 把 theme_manager 存進 main window，方便設定頁面呼叫
    w.theme_manager = theme_manager 
    w.show()
    sys.exit(app.exec())
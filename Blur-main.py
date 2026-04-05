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
import unicodedata
import re

from indexer import IndexerService, NumpyPreprocess

import urllib.request
import tarfile
import subprocess
import shutil

# [New] 引入 OpenCV (給 Grad-CAM 用)
import cv2

# [New] 引入設定管理器
from config_manager import ConfigManager
from theme_manager import ThemeManager # 🌟 [新增] 引入主題引擎

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
                          QFileInfo, QTimer, QAbstractListModel, QRunnable, QThreadPool, QObject, QModelIndex)
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


# ==========================================
#  [NEW] 全域多國語言翻譯器
# ==========================================
class Translator:
    def __init__(self, lang_code):
        self.lang_code = lang_code
        self.translations = {}
        self.load()

    def load(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_dir, "languages", f"{self.lang_code}.json")
        
        # 若找不到指定的語言檔，預設退回繁體中文 (防呆機制)
        if not os.path.exists(file_path):
            file_path = os.path.join(base_dir, "languages", "zh_TW.json")
            
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations = json.load(f)
            except Exception as e:
                print(f"[Translator] 讀取語言檔失敗: {e}")

    def t(self, section, key, default=""):
        """取得翻譯字串的主力函式，使用方式：trans.t('settings', 'window_title', '預設值')"""
        return self.translations.get(section, {}).get(key, default)

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

# ==========================================
#  樣式表
# ==========================================


# ==========================================
#  [NEW] 高效能資料模型與載入器
# ==========================================

class ImageItem:
    """單張圖片的資料結構，統一管理所有屬性"""
    def __init__(self, path, filename, score, ocr_text="", ocr_data=None, mtime=0, width=0, height=0):
        self.path = path
        self.filename = filename
        self.score = score
        self.ocr_text = ocr_text
        self.ocr_data = ocr_data if ocr_data else []
        self.mtime = mtime
        self.width = width
        self.height = height
        self.is_ocr_match = False 

        # 🌟 [Opt 6] 預先格式化與轉換分數，杜絕 paint 迴圈的轉換開銷
        self.score_val = float(score)
        self.score_str = f"{self.score_val:.4f}" if self.score_val > 0.0001 else ""
        
        # 🌟 [Opt 6] 檔名省略 (Elided Text) 快取字典
        self._elided_name_cache = {}

    def get_elided_name(self, fm, width):
        """動態快取省略檔名，相同寬度的卡片只需要計算一次"""
        if width not in self._elided_name_cache:
            self._elided_name_cache[width] = fm.elidedText(self.filename, Qt.TextElideMode.ElideRight, width)
        return self._elided_name_cache[width]

class WorkerSignals(QObject):
    result = pyqtSignal(str, QPixmap, bool) #加入一個布林值 is_final，讓系統知道這是不是最終的高清圖

class PreviewSignals(QObject):
    result = pyqtSignal(str, QPixmap)

class PreviewLoader(QRunnable):
    """專門用於大圖預覽的高清背景讀取器 (支援精確子採樣)"""
    def __init__(self, file_path, target_size):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.signals = PreviewSignals()
        self.is_cancelled = False

    def run(self):
        if self.is_cancelled: return
        try:
            # 🌟 黑科技：使用 QImageReader 進行子採樣，12MB 的圖只解碼出螢幕需要的大小！
            reader = QImageReader(self.file_path)
            reader.setAutoTransform(True)
            orig_size = reader.size()
            
            if orig_size.isValid():
                # 計算適合螢幕的解析度
                scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(scaled_size) # 限制解碼器只輸出這個大小
                img = reader.read()
                
                if self.is_cancelled or img.isNull(): return
                
                # 轉換為顯示卡最愛的 ARGB32 格式，減輕主執行緒負擔
                pixmap = QPixmap.fromImage(img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
                
                # 發射高清圖完成訊號
                self.signals.result.emit(self.file_path, pixmap)
        except Exception as e:
            print(f"Preview Loader Error: {e}")

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

        # 🌟 判定：目標尺寸如果大於 256 (例如 XL 模式)，代表 L2 尺寸不夠，需要升級！
        needs_upgrade = (self.target_size.width() > 256 or self.target_size.height() > 256)

        # ==========================================
        # 🌟 階段一：光速發射 L2 佔位圖 (毫秒級)
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
        # 🌟 階段二：背景替換高清大圖 (重炮火力)
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
                    # 🌟 第二發射：高清原圖覆蓋上去！(is_final = True)
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
        # 🌟 瘦身 1：只保留唯一的 all_items 陣列
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
        
        # 🌟 智慧記憶體管理：防止 XL 的高清大圖塞爆記憶體
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
                ocr_data=res.get('ocr_data', []),
                mtime=res.get('mtime', 0),
                width=res.get('width', 0),
                height=res.get('height', 0)
            )
            if res.get('is_ocr_match', False):
                item.is_ocr_match = True
            self.all_items.append(item)
            self.path_to_row[item.path] = idx
            
        self.endResetModel()
        # 🌟 瘦身 2：拔除 load_more_items 呼叫

    # 🌟 瘦身 3：將原本的 load_more_items 整組刪除

    def sort_items(self, key_func, reverse=False):
        """排序時直接對 all_items 排序，不再需要洗牌第一批"""
        self.beginResetModel()
        self.all_items.sort(key=key_func, reverse=reverse)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        # 🌟 瘦身 4：解放限制，直接回傳真實總數量
        return len(self.all_items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.all_items)):
            return None

        # 🌟 瘦身 5：資料來源改為 all_items
        item = self.all_items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
        elif role == Qt.ItemDataRole.UserRole:
            return item 
        elif role == Qt.ItemDataRole.DecorationRole:
            if item.path in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(item.path)
                return self._thumbnail_cache[item.path]
            
            # 🌟 單幀批量攔截：不直接發送任務，而是先丟進「購物車」
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
        
        # 🌟 核心過濾魔法：判斷是「精確導航」還是「快速拖拽」
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
        # 🌟 只有收到「最終訊號」，才把任務從活躍佇列中移除
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

        # 狀態判斷
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_hover = option.state & QStyle.StateFlag.State_MouseOver
        
        bg_color = QColor("#2b2b2b")
        border_color = QColor("#3b3b3b")
        border_width = 1

        # --- 🌟 動態取得主題顏色 ---
        if hasattr(self.main_window, 'theme_manager'):
            colors = self.main_window.theme_manager.current_colors
        else:
            colors = {} # 防呆

        bg_color = QColor(colors.get("bg_card", "#2b2b2b"))
        border_color = QColor(colors.get("border_main", "#3e3e3e"))
        text_color = QColor(colors.get("text_main", "#ffffff"))
        
        # 🌟 核心視覺優化：避免在畫廊大面積使用純白 (255, 255, 255)
        # 如果主題文字是純白，我們將它柔化為 #e0e0e0 (淡淡的灰白)，減輕刺眼感
        if text_color.name().lower() == "#ffffff":
            text_color = QColor("#e0e0e0")

        # 狀態判斷
        is_selected = option.state & QStyle.StateFlag.State_Selected
        is_hover = option.state & QStyle.StateFlag.State_MouseOver

        if is_selected:
            border_color = QColor(colors.get("primary", "#60cdff"))
            border_width = 2
        elif item.is_ocr_match:
            border_color = QColor(colors.get("text_success", "#4caf50")) # 這裡借用綠色
            border_width = 1
        elif is_hover:
            bg_color = QColor(colors.get("bg_hover", "#383838"))
            border_color = QColor(colors.get("primary_hover", "#7ce0ff"))

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
            # 🌟 [Opt 1] 移除高耗能的 pixmap.scaled(...)
            # 因為 ThumbnailLoader 已經在背景幫我們縮放到完美尺寸了
            # 我們只要做簡單的置中數學運算，然後直接畫上去！
            x_off = (img_rect.width() - pixmap.width()) / 2
            y_off = (img_rect.height() - pixmap.height()) / 2
            
            painter.drawPixmap(
                img_rect.left() + int(x_off), 
                img_rect.top() + int(y_off), 
                pixmap
            )
        else:
            # ==========================================
            # 🌟 [回歸原生] 使用 QIcon.paint() 讓 Qt 底層接管排版與 DPI 縮放
            # ==========================================
            # 1. 取得最短邊，決定圖示比例 (這裡設為 60% 視覺上最剛好)
            min_dim = min(img_rect.width(), img_rect.height())
            icon_size = max(48, int(min_dim * 0.60))
            
            # 2. 打造一個精確的正方形模具 (QRect)
            icon_rect = QRect(0, 0, icon_size, icon_size)
            
            # 3. 將模具的中心點，完美對準圖片區域的中心點
            icon_rect.moveCenter(img_rect.center())
            
            # 4. 設定透明度並繪製
            painter.setOpacity(0.2)
            
            # 🌟 核心魔法：把模具交給 QIcon，它會自動偵測螢幕 DPI 並完美填滿且置中！
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
        
        # 🌟 [Opt 6] 直接使用預先處理好的 float 數值與 string 字串
        if item.score_val > 0.0001:
            if item.score_val > 0.3:
                # 🌟 高分：使用主題的 primary 顏色 (深/淺模式會自動適應)
                score_color = colors.get("primary", "#60cdff")
            else:
                # 🌟 低分：使用主題的 muted 顏色 (柔和的灰色)
                score_color = colors.get("text_muted", "#999999")
                
            painter.setPen(QColor(score_color))
            painter.drawText(score_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.score_str)
        else:
            # 如果分數是 0 (例如剛啟動顯示全部圖片時)，顯示日期可能比較實用，或者留白
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
            # 🌟 標籤背景：使用我們在 JSON 裡新增的 text_success (綠色)
            tag_bg = colors.get("text_success", "#4caf50")
            painter.setBrush(QBrush(QColor(tag_bg)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(tag_rect, 3, 3)
            
            painter.setFont(self.font_tag)
            # 💡 這裡刻意保留純白色 "#ffffff"。
            # 因為無論在深色還是淺色模式，標籤底色都是綠色，白字在綠底上的對比度與閱讀性永遠是最好的。
            painter.setPen(QColor("#ffffff"))
            painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, tag_text)

        painter.restore()
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
                # 🌟 [關鍵修復] 手動補上 pad_token，解決離線載入報錯
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
        # 🌟 [終極防呆：取得當下的指標快照，防止被雙緩衝覆蓋]
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
                "ocr_data": item.get("ocr_data", []), "mtime": item.get("mtime", 0),
                "width": item.get("width", 0),   
                "height": item.get("height", 0)  
            })
        return results

    def load_data_from_db(self):
        print(f"[Engine] Connecting to database: {self.config.db_path}...")
        conn = sqlite3.connect(self.config.db_path)
        cursor = conn.cursor()
        try:
            current_model = self.config.get("model_name")
            
            # [升級 1] SQL 動態 JSON 封裝
            cursor.execute("""
                SELECT f.file_path, e.embedding, f.mtime, f.width, f.height, 
                       GROUP_CONCAT(o.ocr_text, ' '), 
                       '[' || GROUP_CONCAT('{"lang":"' || o.lang || '", "data":' || o.ocr_data || '}', ',') || ']' 
                FROM files f
                JOIN embeddings e ON f.id = e.file_id
                LEFT JOIN ocr_results o ON f.id = o.file_id
                WHERE e.model_name = ?
                GROUP BY f.id
            """, (current_model,))
            rows = cursor.fetchall()
            
            # 🌟 [方案 B：雙緩衝機制] 使用暫存變數進行載入，不干擾主線程的搜尋
            temp_data_store = [] 
            temp_embeddings_list = []
            
            for path, blob, mtime, width, height, combined_text, combined_data_json in rows:
                if not os.path.exists(path): continue 
                
                emb_array = np.frombuffer(blob, dtype=np.float32)
                temp_embeddings_list.append(emb_array)
                text_content = combined_text if combined_text else ""
                
                ocr_boxes = []
                if combined_data_json and combined_data_json != "[]" and combined_data_json != "[NULL]":
                    try:
                        parsed_lists = json.loads(combined_data_json)
                        for lang_group in parsed_lists:
                            if not isinstance(lang_group, dict): continue
                            lang = lang_group.get("lang", "unk")
                            data = lang_group.get("data", [])
                            if isinstance(data, list):
                                for item in data:
                                    item["lang"] = lang  # 關鍵：標記這是哪一國語言抓到的
                                    ocr_boxes.append(item)
                    except Exception as e: 
                        print(f"JSON Parse error: {e}")

                temp_data_store.append({
                    "path": path,
                    "filename": os.path.basename(path),
                    "ocr_text": text_content.lower(),
                    "ocr_data": ocr_boxes,
                    "mtime": mtime,
                    "width": width if width else 0,
                    "height": height if height else 0
                })
            
            # 🌟 [方案 B] 資料準備完成後，進行「極速切換 (Atomic Swap)」
            if temp_data_store and temp_embeddings_list:
                temp_emb_matrix = np.stack(temp_embeddings_list)
                
                # 在 Python 中，物件參照替換是原子操作，搜尋執行緒瞬間拿到新資料，絕不崩潰
                self.stored_embeddings = temp_emb_matrix
                self.data_store = temp_data_store
                print(f"[Engine] Loaded {len(self.data_store)} records for model '{current_model}'.")
            else:
                print(f"[Engine] No records found for model '{current_model}'.")
                self.stored_embeddings = None
                self.data_store = []
                
        except sqlite3.Error as e:
            print(f"[Error] Database query failed: {e}")
        finally:
            if conn: conn.close()

    def get_folder_stats(self):
        if not os.path.exists(self.config.db_path): return []
        try:
            conn = sqlite3.connect(self.config.db_path)
            cursor = conn.cursor()
            # [關鍵修復 2] 根據當前模型去 model_stats 抓取統計
            current_model = self.config.get("model_name")
            cursor.execute("SELECT folder_path, image_count FROM model_stats WHERE model_name = ? ORDER BY folder_path ASC", (current_model,))
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
            # [關鍵修復 3] 改為更新 files 表
            cursor.execute("UPDATE files SET file_path = ?, filename = ? WHERE file_path = ?", (new_path, new_name, old_path))
            conn.commit(); conn.close()
            for item in self.data_store:
                if item["path"] == old_path:
                    item["path"] = new_path; item["filename"] = new_name; break
            return True, new_path
        except Exception as e: return False, str(e)

    # 🌟 [新增] folder_path 參數
    def search_hybrid(self, query, top_k=50, use_ocr=True, weight_config=None, folder_path=None):
        current_embeddings = self.stored_embeddings
        current_data = self.data_store

        if not self.is_ready or current_embeddings is None: 
            return [] 
            
        # ==========================================
        # 🌟 1. 局部矩陣裁切 (Pre-Filter for specific folder)
        # ==========================================
        valid_indices = None
        if folder_path and folder_path != "ALL":
            # 找出所有屬於該資料夾的路徑索引
            norm_target = os.path.normpath(folder_path)
            valid_indices = [
                i for i, item in enumerate(current_data) 
                if os.path.normpath(item["path"]).startswith(norm_target)
            ]
            
            # 如果資料夾裡面沒圖片，直接回傳空陣列
            if not valid_indices:
                return []
                
            # 🌟 Numpy 魔法：只裁出符合條件的特徵向量矩陣，運算速度爆增！
            target_embeddings = current_embeddings[valid_indices]
        else:
            # 全域模式：使用完整矩陣
            target_embeddings = current_embeddings

        results = []; query_lower = query.lower()
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
            
            # 🌟 改用裁切後的 target_embeddings 運算
            scores = np.dot(text_features, target_embeddings.T).squeeze(0)
            
        except Exception as e:
            print(f"CLIP Search Error: {e}")
            scores = np.zeros(len(valid_indices) if valid_indices else len(current_data))

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

        # ==========================================
        # 🌟 2. 局部迴圈 (只處理有被計算的分數)
        # ==========================================
        score_idx = 0
        
        # 決定要跑完整迴圈，還是只跑我們挑選出的 valid_indices
        iter_list = valid_indices if valid_indices is not None else range(len(current_data))

        for original_idx in iter_list:
            item = current_data[original_idx]
            
            # 使用 score_idx 去對應剛剛算出來的縮水版分數陣列
            clip_score = float(scores[score_idx])
            score_idx += 1
            
            has_ocr = use_ocr and (query_lower in item["ocr_text"])
            has_name = query_lower in item["filename"].lower()
            
            ocr_bonus = 0.0
            name_bonus = 0.0
            
            if clip_score >= 0.08:
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
                "ocr_data": item.get("ocr_data", []), "mtime": item.get("mtime", 0),
                "width": item.get("width", 0),  
                "height": item.get("height", 0) 
            })

        if thresh_mode == "auto":
            actual_thresh = max_score * 0.5
        else:
            actual_thresh = thresh_val

        results = [r for r in raw_results if r["score"] >= actual_thresh]
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search_image(self, image_path, top_k=50):
        # 🌟 [終極防呆：取得當下指標快照]
        current_embeddings = self.stored_embeddings
        current_data = self.data_store

        if not self.is_ready or current_embeddings is None: 
            return []
            
        try:
            image = Image.open(image_path).convert('RGB')
            processed_image = np.expand_dims(self.preprocess(image), axis=0)
            
            input_name = self.clip_image_session.get_inputs()[0].name
            image_features = self.clip_image_session.run(None, {input_name: processed_image})[0]
            image_features = image_features / np.linalg.norm(image_features, axis=-1, keepdims=True)
            
            # 這裡也必須使用 current_embeddings
            similarity = np.dot(image_features, current_embeddings.T).squeeze(0)
            
            k = min(top_k, len(current_data))
            indices = np.argsort(similarity)[::-1][:k] 
            values = similarity[indices]
            
            results = []
            for i in range(k):
                idx = indices[i]; item = current_data[idx]; score = values[i]
                results.append({
                    "score": float(score), "clip_score": float(score), "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                    "path": item["path"], "filename": item["filename"], 
                    "ocr_data": item.get("ocr_data", []), 
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),   
                    "height": item.get("height", 0)  
                })
            return results
        except Exception as e:
            print(f"[Error] Image search failed: {e}"); return []

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
            use_gpu_ocr=config.get("use_gpu_ocr") # <--- [新增] 將 GPU 設定傳遞給底層引擎
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
            # 🌟 [關鍵修復] 以前這裡是 .engine.model (因為改版變成 None 了)
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
            # 圖片相似搜尋目前暫不實作範圍過濾
            raw_results = self.engine.search_image(self.query, self.top_k)
        else:
            # 🌟 [修改] 將參數傳遞給底層
            raw_results = self.engine.search_hybrid(
                self.query, 
                self.top_k, 
                self.use_ocr, 
                self.weight_config, 
                folder_path=self.folder_path
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

            # 🌟 取得主題顏色
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

    def set_ocr_data(self, data, orig_w, orig_h, query="", is_precise=False):
        self.original_size = QSize(orig_w, orig_h)
        self.search_query = query.lower()
        self.is_precise_mode = is_precise
        self.hovered_index = -1
        
        # ==========================================
        # [升級] Shapely 群組打包 (Group & Merge)
        # ==========================================
        merged_data = []
        try:
            from shapely.geometry import Polygon as ShapelyPolygon
        except ImportError:
            ShapelyPolygon = None

        if not ShapelyPolygon:
            # 沒有 Shapely 的備用方案：直接轉換格式
            for item in data:
                merged_data.append({
                    "box": item.get("box", []),
                    "results": [{"lang": item.get("lang", "unk"), "text": item.get("text", ""), "conf": item.get("conf", 0.0)}]
                })
        else:
            for item in data:
                box = item.get("box")
                if not box or len(box) != 4: continue
                
                sorted_box = self._sort_points(box)
                try:
                    current_poly = ShapelyPolygon(sorted_box)
                    if not current_poly.is_valid or current_poly.area <= 0: continue
                except: continue
                
                is_merged = False
                for existing in merged_data:
                    existing_poly = existing["poly"]
                    try:
                        if current_poly.intersects(existing_poly):
                            inter_area = current_poly.intersection(existing_poly).area
                            min_area = min(current_poly.area, existing_poly.area)
                            # 如果重疊超過 85%，判定為同一個區塊的不同語言結果，打包在一起！
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
        
        # 移除底層繪圖不需要的 poly 物件，避免記憶體洩漏或錯誤
        for m in merged_data:
            m.pop("poly", None)
            
        self.ocr_data = merged_data

    def set_draw_boxes(self, show):
        self.show_ocr_boxes = show
        if not show:
            self.hovered_index = -1
            self.hover_info_changed.emit([], QPolygon(), QPoint())
        self.update()

    def _sort_points(self, box):
        """將 OpenCV 隨機順序的四個點嚴格定義為 TL, TR, BR, BL"""
        import numpy as np
        pts = np.array(box)
        rect = np.zeros((4, 2), dtype="float32")
        
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)] # TL
        rect[2] = pts[np.argmax(s)] # BR
        
        diff = np.diff(pts, axis=1) 
        rect[1] = pts[np.argmin(diff)] # TR
        rect[3] = pts[np.argmax(diff)] # BL
        
        return rect.tolist()

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
                
                    # 🌟 從頂層視窗取得 ThemeManager
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
                    
                # 🌟 從主題取得基礎色與懸停色
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

    # 🌟 接收來自 MainWindow 的 l1_pixmap
    def show_image(self, result_data, current_query="", is_precise_mode=False, l1_pixmap=None):
        if isinstance(result_data, ImageItem):
            path = result_data.path
            ocr_boxes = result_data.ocr_data
        else:
            path = result_data['path']
            ocr_boxes = result_data.get('ocr_data', [])

        if not os.path.exists(path): return

        self.current_preview_path = path

        # 🌟 防護網：如果有上一張圖的高清任務還在跑，立刻無情撤銷！
        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None

        screen_size = self.parent().size()
        max_w = int(screen_size.width() * 0.85)
        max_h = int(screen_size.height() * 0.85)
        target_size = QSize(max_w, max_h)

        # ==========================================
        # 階段一：0 毫秒光速顯示 (拉伸 L1 小快取)
        # ==========================================
        if l1_pixmap and not l1_pixmap.isNull():
            # 將 220x180 的小圖平滑放大到全螢幕，畫面會瞬間出現 (雖然是模糊的)
            scaled_l1 = l1_pixmap.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_l1)
        else:
            self.image_label.clear()

        # ==========================================
        # 階段二：發射背景高清解碼任務
        # ==========================================
        self.current_preview_worker = PreviewLoader(path, target_size)
        self.current_preview_worker.signals.result.connect(self.on_highres_ready)
        QThreadPool.globalInstance().start(self.current_preview_worker)

        # --- 處理 OCR 標籤與其他 UI ---
        import copy
        processed_boxes = copy.deepcopy(ocr_boxes)
        
        # ==========================================
        # 🌟 [關鍵修復] 修正 OCR 紅框偏移 Bug
        # 不論是否顯示模糊小圖，OCR 坐標必須永遠對齊原始圖片的高清解析度！
        # ==========================================
        if isinstance(result_data, ImageItem):
            # 🌟 [修正] 屬性名稱是 width 和 height
            orig_w, orig_h = result_data.width, result_data.height
        else:
            orig_w = result_data.get('width', target_size.width())
            orig_h = result_data.get('height', target_size.height())
            
        # 🌟 終極防呆：萬一資料庫讀出來的長寬是 0 (例如舊資料庫)，借用螢幕尺寸避免報錯
        if orig_w == 0 or orig_h == 0:
            orig_w, orig_h = target_size.width(), target_size.height()

        self.image_label.set_ocr_data(processed_boxes, orig_w, orig_h, current_query, is_precise_mode)
        
        self.filename_label.setText(os.path.basename(path))
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()

    # ==========================================
    # 階段三：接收高清圖並「直接硬切」
    # ==========================================
    def on_highres_ready(self, path, pixmap):
        # 嚴格防呆：確保這張圖是使用者「現在」正在看的這張
        if path == self.current_preview_path and not pixmap.isNull():
            # 瞬間硬切覆蓋！完成「對焦」的視覺魔法
            self.image_label.setPixmap(pixmap)
            
            self.image_label.update()

    def set_ocr_visible(self, visible):
        self.image_label.set_draw_boxes(visible)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.hide()

    def mousePressEvent(self, event):
        self.hide()

    def hideEvent(self, event):
        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            self.hide() # 這裡只要單純 hide，上面的 hideEvent 就會自動幫我們清垃圾了

    def mousePressEvent(self, event):
        self.hide()

class HistoryItemWidget(QWidget):
    def __init__(self, text, search_callback, delete_callback):
        super().__init__(); self.text = text; self.search_callback = search_callback; self.delete_callback = delete_callback
        layout = QHBoxLayout(self); layout.setContentsMargins(10, 0, 5, 0)
        self.label = QLabel(text); self.label.setStyleSheet("background: transparent;"); self.label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.label.mousePressEvent = self.on_label_clicked
        layout.addWidget(self.label, stretch=1)
        self.del_btn = QPushButton("x")
        self.del_btn.setObjectName("HistoryDelBtn") # 🌟 換成專屬身分證
        self.del_btn.setFixedSize(28, 28)
        self.del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
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
        # 🌟 1. 主體面板發放身分證
        self.setObjectName("StatsPanel")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(1, 1, 1, 1)
        self.main_layout.setSpacing(0)
        
        title_container = QWidget()
        # 🌟 2. 標題區塊發放身分證
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
        # 🌟 3. 底部區塊發放身分證
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
            
            # 🌟 4. 資料行發放身分證
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

        

    # 🌟 [新增] 覆寫滑鼠進出事件，通知上層 Sidebar
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

class SidebarWidget(QFrame):
    folder_selected = pyqtSignal(str) 
    toggled = pyqtSignal(bool)
    add_folder_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    settings_requested = pyqtSignal()

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
        self.btn_all_images.setObjectName("SidebarRow1")
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

        # 3. 初始化二級選單
        self.hover_menu = FolderHoverMenu(self)
        self.hover_menu.folder_clicked.connect(self.on_sub_folder_clicked)
        self.hover_menu.add_clicked.connect(self.add_folder_requested.emit)

        self.hover_menu.mouse_entered.connect(self.hover_timer.stop)
        self.hover_menu.mouse_left.connect(lambda: self.hover_timer.start(150))
        
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

    def update_folders(self, stats, config_folders): # [修改]
        self.stats_cache = stats
        self.hover_menu.update_menu(stats, config_folders) # 把 config 傳遞下去
        total = sum(c for _, c in stats)
        self.all_images_text = f"  All Images ({total})"
        self.update_ui_text()

    def toggle_sidebar(self):
        self.is_expanded = not self.is_expanded
        self.setFixedWidth(self.expanded_width if self.is_expanded else self.collapsed_width)
        self.update_ui_text()
        self.toggled.emit(self.is_expanded)

    def update_ui_text(self):
        if self.is_expanded:
            self.btn_all_images.setText(getattr(self, 'all_images_text', "  All Images"))
            self.btn_settings.setText("  設定 (Settings)")
        else:
            self.btn_all_images.setText("")
            self.btn_settings.setText("")
        
        # 🌟 終極重構：用屬性 (Property) 驅動 QSS，消滅硬寫的 StyleSheet
        # 通知這兩顆按鈕目前的狀態，QSS 檔裡的 [expanded="true"] 就會自動生效！
        for btn in [self.btn_all_images, self.btn_settings]:
            btn.setProperty("expanded", self.is_expanded)
            # 強制 Qt 重新讀取該元件的樣式
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def on_row1_clicked(self):
        self.folder_selected.emit("ALL")
        if self.hover_menu.isVisible():
            self.hover_menu.close()
        else:
            sidebar_global_pos = self.mapToGlobal(QPoint(0, 0))
            row1_y = self.btn_toggle.height()
            target_x = sidebar_global_pos.x() + self.width()
            target_y = sidebar_global_pos.y() + row1_y
            self.hover_menu.show_at(QPoint(target_x, target_y), 60)

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

    # 🌟 [新增] 事件過濾器：攔截主按鈕的進出
    def eventFilter(self, obj, event):
        if obj == self.btn_all_images:
            if event.type() == QEvent.Type.Enter:
                self.hover_timer.stop()
                self.show_hover_menu()
            elif event.type() == QEvent.Type.Leave:
                self.hover_timer.start(150)
        return super().eventFilter(obj, event)
    
    # 🌟 [新增] 顯示、隱藏與檢查邏輯
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
        """🌟 150ms 倒數結束後的絕對座標防呆檢查"""
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

    # 🌟 [修改] 純粹派發訊號，關閉交由 Hover 邏輯處理
    def on_row1_clicked(self):
        self.folder_selected.emit("ALL")
        self.hide_hover_menu()

    def on_sub_folder_clicked(self, path):
        self.folder_selected.emit(path)

    

class CollapsibleSection(QWidget):
    """自定義摺疊區塊，仿 VSCode 樣式 (解決文字跳動問題)"""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 1. 標頭按鈕 (Header) - 這次我們不直接在按鈕上寫字
        self.header = QPushButton()
        self.header.setFixedHeight(36)
        self.header.setCheckable(True)
        self.header.setChecked(True) # 預設展開
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setObjectName("CollapseHeader")
        
        # --- 解決跳動的魔法：在按鈕內部建立專屬 Layout ---
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(12, 8, 12, 8)
        self.header_layout.setSpacing(5) # 箭頭與文字的距離

        # A. 獨立的箭頭標籤
        self.lbl_arrow = QLabel("▼")
        self.lbl_arrow.setFixedWidth(16) # 🔒 鎖死寬度，文字絕對不會亂跑
        self.lbl_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter) # 讓箭頭在 16px 內乖乖置中
        
        # B. 獨立的標題標籤
        self.lbl_title = QLabel(title)
        
        # 統一設定標籤樣式，並讓滑鼠點擊「穿透」標籤，確保按鈕能正常被點擊
        
        self.lbl_arrow.setObjectName("CollapseArrow")
        self.lbl_arrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # 把標籤加入按鈕內部
        self.header_layout.addWidget(self.lbl_arrow)
        self.header_layout.addWidget(self.lbl_title)
        self.header_layout.addStretch(1) # 彈簧把文字往左推
        # ------------------------------------------------

        # 2. 內容容器 (Content)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(20, 15, 20, 15)
        self.content_layout.setSpacing(12)
        
        self.layout.addWidget(self.header)
        self.layout.addWidget(self.content)
        
        # 連結點擊事件
        self.header.clicked.connect(self.toggle_content)

    def toggle_content(self):
        is_expanded = self.header.isChecked()
        self.content.setVisible(is_expanded)
        # 程式碼變乾淨了，直接改獨立箭頭的字就好！
        self.lbl_arrow.setText("▼" if is_expanded else "▶")

    def set_expanded(self, expanded: bool):
        self.header.setChecked(expanded)
        self.content.setVisible(expanded)
        self.lbl_arrow.setText("▼" if expanded else "▶")

    def addWidget(self, widget):
        self.content_layout.addWidget(widget)

    def addLayout(self, layout):
        self.content_layout.addLayout(layout)

    def set_status_active(self, is_active):
        """層級二：控制檢索過濾區塊的動態底線"""
        state_str = "true" if is_active else "false"
        self.header.setProperty("active", state_str)
        self.lbl_title.setProperty("active", state_str)
        
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)
        self.lbl_title.style().unpolish(self.lbl_title)
        self.lbl_title.style().polish(self.lbl_title)

import calendar
from datetime import date, timedelta
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCursor

class RangeCalendarWidget(QWidget):
    """具備控制列與狀態提示的進階區間日曆"""
    apply_requested = pyqtSignal(date, date)   # 點擊套用結果
    search_requested = pyqtSignal(date, date)  # 點擊直接搜尋
    cleared = pyqtSignal()                     # 點擊清除
    selection_started = pyqtSignal()           # 點第一下時觸發

    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.today = date.today()
        self.current_year = self.today.year
        self.current_month = self.today.month
        self.start_date = None
        self.end_date = None
        self.btn_dates_map = {}
        self.setObjectName("RangeCalendar")
        self.init_ui()
        self.update_calendar()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        # 1. 頂部標頭 (年月)
        header_layout = QHBoxLayout()
        self.btn_prev = QPushButton("◀"); self.btn_prev.setFixedSize(28, 28); self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_prev.clicked.connect(self.prev_month)
        self.lbl_month_year = QLabel(""); self.lbl_month_year.setAlignment(Qt.AlignmentFlag.AlignCenter); self.lbl_month_year.setStyleSheet("font-size: 15px;")
        self.btn_next = QPushButton("▶"); self.btn_next.setFixedSize(28, 28); self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_next.clicked.connect(self.next_month)
        header_layout.addWidget(self.btn_prev); header_layout.addWidget(self.lbl_month_year, stretch=1); header_layout.addWidget(self.btn_next)
        main_layout.addLayout(header_layout)

        # 2. 星期標籤
        week_layout = QHBoxLayout()
        for wd in ["日", "一", "二", "三", "四", "五", "六"]:
            lbl = QLabel(wd)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setObjectName("CalendarWeekday")
            week_layout.addWidget(lbl)
        main_layout.addLayout(week_layout)

        # 3. 日期網格
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(2)
        self.day_buttons = []
        for row in range(6):
            for col in range(7):
                btn = QPushButton()
                btn.setFixedSize(28, 28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(self.on_day_clicked)
                self.grid_layout.addWidget(btn, row, col)
                self.day_buttons.append(btn)
        main_layout.addLayout(self.grid_layout)

        # 4. 狀態訊息提示區
        self.lbl_status = QLabel("💡 請點選開始與結束日期...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setObjectName("CalendarStatus")
        self.lbl_status.setProperty("state", "normal")
        main_layout.addWidget(self.lbl_status)

        # 5. 底部控制按鈕區
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 0)
        
        self.btn_clear = QPushButton("清除"); self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setProperty("cssClass", "DangerBtn")
        self.btn_clear.clicked.connect(self.clear_selection)
        
        self.btn_today = QPushButton("今天"); self.btn_today.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_today.setProperty("cssClass", "ActionBtn")
        self.btn_today.clicked.connect(self.go_to_today)

        self.btn_apply = QPushButton("套用結果"); self.btn_apply.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_apply.setProperty("cssClass", "ActionBtn")
        self.btn_apply.clicked.connect(lambda: self.apply_requested.emit(self.start_date, self.end_date))
        self.btn_apply.setEnabled(False)

        self.btn_search = QPushButton("直接搜尋"); self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.setProperty("cssClass", "ActionBtn")
        self.btn_search.clicked.connect(lambda: self.search_requested.emit(self.start_date, self.end_date))
        self.btn_search.setEnabled(False)

        left_h = QHBoxLayout(); left_h.setSpacing(5)
        left_h.addWidget(self.btn_clear); left_h.addWidget(self.btn_today)
        right_h = QHBoxLayout(); right_h.setSpacing(5)
        right_h.addWidget(self.btn_apply); right_h.addWidget(self.btn_search)

        footer_layout.addLayout(left_h); footer_layout.addStretch(1); footer_layout.addLayout(right_h)
        main_layout.addLayout(footer_layout)

    def set_status(self, text, state="normal"):
        """供外部控制訊息區的文字與顏色"""
        self.lbl_status.setText(text)
        self.lbl_status.setProperty("state", state) # 🌟 狀態交給 QSS 判定
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def update_action_buttons(self):
        can_action = bool(self.start_date and self.end_date)
        self.btn_apply.setEnabled(can_action)
        self.btn_search.setEnabled(can_action)
        
        if can_action:
            days = (self.end_date - self.start_date).days + 1
            self.set_status(f"💡 已選取 {days} 天，請選擇動作。", "primary")
        else:
            self.set_status("💡 請點選結束日期...", "normal")

    # ---------------- 內部邏輯與事件 ----------------
    def update_calendar(self):
        self.lbl_month_year.setText(f"{self.current_year} 年 {self.current_month} 月")
        cal = calendar.Calendar(firstweekday=6)
        month_days = cal.monthdatescalendar(self.current_year, self.current_month)
        flat_days = [day for week in month_days for day in week]

        for i, btn in enumerate(self.day_buttons):
            if i < len(flat_days):
                day_obj = flat_days[i]
                btn.setText(str(day_obj.day))
                self.btn_dates_map[btn] = day_obj
                btn.setProperty("is_endpoint", "false"); btn.setProperty("in_range", "false"); btn.setProperty("is_today", "false")

                # 【修改後】改成屬性標記
                is_other = "true" if day_obj.month != self.current_month else "false"
                btn.setProperty("is_other_month", is_other)

                if day_obj == self.today: btn.setProperty("is_today", "true")

                if self.start_date and self.end_date:
                    if day_obj == self.start_date or day_obj == self.end_date: btn.setProperty("is_endpoint", "true")
                    elif self.start_date < day_obj < self.end_date: btn.setProperty("in_range", "true")
                elif self.start_date and day_obj == self.start_date:
                    btn.setProperty("is_endpoint", "true")

                btn.style().unpolish(btn); btn.style().polish(btn)
        
        self.update_action_buttons()

    def on_day_clicked(self):
        btn = self.sender()
        clicked_date = self.btn_dates_map.get(btn)
        if not clicked_date: return

        if self.start_date is None or (self.start_date and self.end_date):
            # 狀態 1：選取第一下 (設定起點)
            self.start_date = clicked_date
            self.end_date = None
            self.selection_started.emit()
        else:
            # 狀態 2：選取第二下 (完成範圍)
            if clicked_date < self.start_date:
                # 🌟 【關鍵修正】如果第二下點得比第一下早，自動反轉起訖日！
                self.end_date = self.start_date
                self.start_date = clicked_date
            else:
                # 正常從早點到晚
                self.end_date = clicked_date
                
        self.update_calendar()

    def clear_selection(self):
        self.start_date = None; self.end_date = None
        self.update_calendar()
        self.set_status("💡 請點選開始與結束日期...", "normal")
        self.cleared.emit()

    def go_to_today(self):
        self.current_year = self.today.year; self.current_month = self.today.month
        self.start_date = self.today; self.end_date = self.today
        self.update_calendar()

    def prev_month(self):
        if self.current_month == 1: self.current_month = 12; self.current_year -= 1
        else: self.current_month -= 1
        self.update_calendar()

    def next_month(self):
        if self.current_month == 12: self.current_month = 1; self.current_year += 1
        else: self.current_month += 1
        self.update_calendar()

from PyQt6.QtWidgets import QSlider  # 確保頂部或這裡有引入 QSlider

class InspectorPanel(QFrame):
    """右側屬性與檢索控制台 (三層分頁架構)"""

    aspect_changed = pyqtSignal()
    sort_changed = pyqtSignal()
    time_filter_applied = pyqtSignal(float, float) 
    time_search_requested = pyqtSignal(float, float)
    time_filter_cleared = pyqtSignal()
    weights_changed = pyqtSignal(dict)
    
    # [新增] 權重改變的訊號
    weights_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent# [新增] 儲存父視窗以便讀寫設定
        self.setFixedWidth(320)

        self.setObjectName("InspectorPanel")
        
        # 專屬的現代化暗色系樣式
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 建立分頁元件
        self.tabs = QTabWidget()

        self.tabs.setObjectName("InspectorTabs")

        self.layout.addWidget(self.tabs)

        # --- 分頁 1: 搜尋控制 ---
        self.tab_search = QWidget()
        self._setup_search_tab()
        self.tabs.addTab(self.tab_search, "🔎 搜尋")

        # ==========================================
        # [新增] 分頁 1.5: CLIP 控制
        # ==========================================
        self.tab_clip = QWidget()
        self._setup_clip_tab()
        self.tabs.addTab(self.tab_clip, "👁️ CLIP")

        # --- 分頁 2: OCR 細節 ---
        self.tab_ocr = QWidget()
        self._setup_ocr_tab()
        self.tabs.addTab(self.tab_ocr, "🔤 OCR")

        # --- 分頁 3: 圖片資訊 ---
        self.tab_info = QWidget()
        self._setup_info_tab()
        self.tabs.addTab(self.tab_info, "ℹ️ 資訊")

        self.hide() # 預設隱藏，等待按鈕觸發

    def _setup_search_tab(self):
        tab_layout = QVBoxLayout(self.tab_search)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("InspectorScrollArea")
        
        container = QWidget()
        container.setObjectName("SearchTabContainer")
        
        self.search_main_layout = QVBoxLayout(container)
        self.search_main_layout.setContentsMargins(0, 0, 0, 0)
        self.search_main_layout.setSpacing(0)
        self.search_main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- 區塊 1: 🔍 檢索過濾 (FILTER) ---
        self.sec_filter = CollapsibleSection("檢索過濾")

        trans = self.main_window.config.translator
        
        self.sec_filter.addWidget(QLabel(trans.t("search_filter", "lbl_search_scope", "搜尋範圍 (Search Scope):")))
        self.combo_search_scope = QComboBox()
        self.combo_search_scope.addItems([
            trans.t("search_filter", "scope_local", "📂 目前資料夾 (Local)"),
            trans.t("search_filter", "scope_global", "🌍 全域搜尋 (Global)")
        ])
        self.combo_search_scope.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_search_scope.setFixedHeight(38)
        self.sec_filter.addWidget(self.combo_search_scope)
        
        line_scope = QFrame()
        line_scope.setFrameShape(QFrame.Shape.HLine)
        line_scope.setStyleSheet("border-top: 1px solid #3c3c3c; margin: 5px 0;")
        self.sec_filter.addWidget(line_scope)
        
        self.btn_time_range = QPushButton("📅 全部時間 (All Time)")
        self.btn_time_range.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_time_range.setCheckable(True)
        self.btn_time_range.setObjectName("TimeRangeBtn")
        self.btn_time_range.clicked.connect(self.toggle_calendar)
        self.sec_filter.addWidget(self.btn_time_range)

        self.calendar_widget = RangeCalendarWidget()
        self.calendar_widget.hide()
        self.calendar_widget.apply_requested.connect(self.on_calendar_apply)
        self.calendar_widget.search_requested.connect(self.on_calendar_search)
        self.calendar_widget.cleared.connect(self.on_calendar_cleared)
        self.calendar_widget.selection_started.connect(self.on_calendar_picking)
        self.sec_filter.addWidget(self.calendar_widget)

        self.lbl_aspect_title = QLabel("視覺規格 (Visual Specs):")
        self.lbl_aspect_title.setObjectName("FilterTitle")
        self.sec_filter.addWidget(self.lbl_aspect_title)
        
        self.combo_aspect = QComboBox()
        self.combo_aspect.addItems(["不限比例", "橫圖 (Landscape)", "直圖 (Portrait)", "正方形 (Square)"])
        
        if not hasattr(self, 'aspect_changed'): self.aspect_changed = pyqtSignal()
        self.combo_aspect.currentIndexChanged.connect(self.on_aspect_changed)
        self.sec_filter.addWidget(self.combo_aspect)
        self.search_main_layout.addWidget(self.sec_filter)

        # --- 區塊 2: ⚙️ 顯示設定 (DISPLAY) ---
        self.sec_display = CollapsibleSection("顯示設定")
        self.sec_display.addWidget(QLabel("顯示數量限制 (Limit):"))
        self.combo_limit_panel = QComboBox()
        self.combo_limit_panel.addItems(["20", "50", "100", "All"])
        self.sec_display.addWidget(self.combo_limit_panel)

        self.sec_display.addWidget(QLabel("Gallery 排序方式 (Sort By):"))
        sort_layout = QHBoxLayout()
        sort_layout.setContentsMargins(0, 0, 0, 0)
        sort_layout.setSpacing(8)
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["搜尋相關度", "日期", "名稱", "類型", "大小"])
        self.combo_sort.currentIndexChanged.connect(lambda: self.sort_changed.emit())
        sort_layout.addWidget(self.combo_sort, stretch=1)

        self.btn_sort_order = QPushButton("↓")
        self.btn_sort_order.setFixedSize(32, 32)
        self.btn_sort_order.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort_order.setObjectName("SortOrderBtn")
        self.btn_sort_order.clicked.connect(self.toggle_sort_order)
        sort_layout.addWidget(self.btn_sort_order)
        
        self.sec_display.addLayout(sort_layout)
        self.search_main_layout.addWidget(self.sec_display)

        # --- 區塊 3: 🧪 進階功能 (ADVANCED) ---
        self.sec_advanced = CollapsibleSection("相關度權重控制")
        
        mode_layout = QHBoxLayout()
        self.combo_calc_mode = QComboBox()
        self.combo_calc_mode.addItems(["乘法模式 (Multiplication)", "加法模式 (Addition)"])
        self.combo_calc_mode.currentIndexChanged.connect(self.on_calc_mode_changed)
        mode_layout.addWidget(self.combo_calc_mode)
        self.sec_advanced.addLayout(mode_layout)

        self.lbl_formula = QLabel()
        self.lbl_formula.setObjectName("FormulaLabel")
        self.sec_advanced.addWidget(self.lbl_formula)

        self.lbl_clip_weight = QLabel()
        self.sec_advanced.addWidget(self.lbl_clip_weight)
        self.slider_clip = QSlider(Qt.Orientation.Horizontal)
        self.slider_clip.setRange(0, 100)
        self.slider_clip.valueChanged.connect(self.update_weight_labels)
        self.slider_clip.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_clip)

        self.lbl_ocr_weight = QLabel()
        self.sec_advanced.addWidget(self.lbl_ocr_weight)
        self.slider_ocr = QSlider(Qt.Orientation.Horizontal)
        self.slider_ocr.setRange(0, 100)
        self.slider_ocr.valueChanged.connect(self.update_weight_labels)
        self.slider_ocr.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_ocr)

        self.lbl_name_weight = QLabel()
        self.sec_advanced.addWidget(self.lbl_name_weight)
        self.slider_name = QSlider(Qt.Orientation.Horizontal)
        self.slider_name.setRange(0, 100)
        self.slider_name.valueChanged.connect(self.update_weight_labels)
        self.slider_name.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_name)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("border-top: 1px solid #3c3c3c; margin: 10px 0;")
        self.sec_advanced.addWidget(line)

        self.sec_advanced.addWidget(QLabel("結果過濾門檻 (Threshold):"))
        self.combo_threshold_mode = QComboBox()
        self.combo_threshold_mode.addItems(["自動 (最高分的一半)", "手動 (自訂最低分)"])
        self.combo_threshold_mode.currentIndexChanged.connect(self.on_threshold_mode_changed)
        self.sec_advanced.addWidget(self.combo_threshold_mode)

        self.lbl_threshold_val = QLabel()
        self.sec_advanced.addWidget(self.lbl_threshold_val)
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_threshold.setRange(1, 50) 
        self.slider_threshold.valueChanged.connect(self.update_weight_labels)
        self.slider_threshold.sliderReleased.connect(self.on_weight_slider_released)
        self.sec_advanced.addWidget(self.slider_threshold)
        
        btn_reset = QPushButton("🔄 重置為預設權重")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setObjectName("ResetWeightBtn")
        btn_reset.clicked.connect(self.reset_weights_to_default)
        self.sec_advanced.addWidget(btn_reset)
        
        self.search_main_layout.addWidget(self.sec_advanced)
        self.sec_advanced.set_expanded(True) # 預設展開

        QTimer.singleShot(0, self.load_weight_settings)

        self.search_main_layout.addStretch(1)
        scroll_area.setWidget(container)
        tab_layout.addWidget(scroll_area)

        self.btn_clear_all = QPushButton("🗑️ 清除所有過濾條件")
        self.btn_clear_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear_all.setObjectName("ClearFilterBtn")
        self.btn_clear_all.clicked.connect(self.clear_all_filters)
        self.btn_clear_all.hide()
        tab_layout.addWidget(self.btn_clear_all)

    def toggle_sort_order(self):
        """切換排序方向 (正序 ↑ / 倒序 ↓)"""
        if self.btn_sort_order.text() == "↓":
            self.btn_sort_order.setText("↑")
            self.btn_sort_order.setToolTip("目前為：正序 (由小到大 / 舊到新)")
        else:
            self.btn_sort_order.setText("↓")
            self.btn_sort_order.setToolTip("目前為：倒序 (由大到小 / 新到舊)")
            
        
        self.sort_changed.emit()

    # ==========================
    # [優化] 抽離重複的按鈕樣式
    # ==========================
    def _create_construction_button(self, text):
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName("WipButton") # 🌟 套用修復的 QSS
        # 🗑️ [刪除] 下面這整段 btn.setStyleSheet("""...""") 全部刪除！
        return btn

    def _setup_clip_tab(self):
        # 修正：確保 layout 綁定在正確的 tab 上
        layout = QVBoxLayout(self.tab_clip)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 25, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 使用統一的樣式產生按鈕
        self.btn_test_clip = self._create_construction_button("🚧 施工中：進階 CLIP 向量過濾")
        layout.addWidget(self.btn_test_clip)

        layout.addStretch(1)

    def _setup_ocr_tab(self):
        # 修正：原代碼誤寫為 self.tab_clip，現已改回 self.tab_ocr
        layout = QVBoxLayout(self.tab_ocr) 
        layout.setSpacing(15)
        layout.setContentsMargins(20, 25, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 修正：使用正確的按鈕變數名稱
        self.btn_test_ocr = self._create_construction_button("🚧 施工中：進階 OCR 屬性分析")
        layout.addWidget(self.btn_test_ocr)

        layout.addStretch(1)

    def _setup_info_tab(self):
        layout = QVBoxLayout(self.tab_info)
        layout.setSpacing(15); layout.setContentsMargins(20, 25, 20, 20)

        # 頂部圖片預覽
        self.preview_lbl = QLabel("尚未選取圖片")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setMinimumHeight(180)
        self.preview_lbl.setObjectName("PreviewImage")
        layout.addWidget(self.preview_lbl)

        # 檔案名稱
        self.filename_lbl = QLabel("尚未選取檔案")
        self.filename_lbl.setWordWrap(True)
        self.filename_lbl.setStyleSheet("font-size: 15px; font-weight: bold; background: transparent;")
        layout.addWidget(self.filename_lbl)

        # 開啟資料夾按鈕
        self.btn_open_folder = QPushButton("📂 開啟檔案位置")
        self.btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_folder.setProperty("cssClass", "ActionBtn")
        layout.addWidget(self.btn_open_folder)

        # 🌟 [修正 1] 新增一個變數來記住現在點到哪張圖，並只在初始化時綁定一次訊號！
        self.current_info_path = ""
        self.btn_open_folder.clicked.connect(self._on_open_folder_clicked)

        # 詳細屬性網格
        self.grid = QGridLayout()
        self.grid.setVerticalSpacing(10); self.grid.setHorizontalSpacing(10)
        self.fields = {}
        properties = ["類型", "大小", "修改日期", "AI 相關度"]
        
        for i, key in enumerate(properties):
            lbl_key = QLabel(key)
            lbl_key.setObjectName("InfoLabelKey")
            lbl_value = QLabel("-")
            lbl_value.setObjectName("InfoLabelValue")
            lbl_value.setWordWrap(True)
            self.grid.addWidget(lbl_key, i, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(lbl_value, i, 1, Qt.AlignmentFlag.AlignTop)
            self.fields[key] = lbl_value

        layout.addLayout(self.grid)
        layout.addStretch(1)

    def update_info(self, item):
        """當主畫面點擊圖片時，呼叫此函式更新第三分頁的資料"""
        import os, datetime
        from PyQt6.QtGui import QImageReader, QPixmap
        from PyQt6.QtCore import QSize, Qt
        
        self.filename_lbl.setText(item.filename)
        
        # 智慧縮放預覽圖
        reader = QImageReader(item.path)
        reader.setAutoTransform(True)
        img_size = reader.size()
        if img_size.isValid():
            scaled_size = img_size.scaled(QSize(260, 180), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(scaled_size)
            img = reader.read()
            if not img.isNull():
                self.preview_lbl.setPixmap(QPixmap.fromImage(img))
                self.preview_lbl.setStyleSheet("background-color: transparent; border: none;")

        # 🌟 [修正 2] 拔掉原本的 disconnect() 和 lambda，改為單純更新路徑變數
        self.current_info_path = item.path
        
        

        # 更新文字屬性
        try:
            file_stat = os.stat(item.path)
            ext = os.path.splitext(item.filename)[1].upper()
            self.fields["類型"].setText(f"{ext} 檔案" if ext else "未知")
            self.fields["大小"].setText(f"{file_stat.st_size / (1024 * 1024):.2f} MB")
            dt = datetime.datetime.fromtimestamp(item.mtime)
            self.fields["修改日期"].setText(dt.strftime("%Y/%m/%d %H:%M"))
            self.fields["AI 相關度"].setText(f"{item.score:.4f}" if item.score > 0 else "N/A")
        except: pass
    
    # 🌟 [新增] 專門處理按鈕點擊的函式
    def _on_open_folder_clicked(self):
        if self.current_info_path:
            self.open_in_explorer(self.current_info_path)

    def open_in_explorer(self, path):
        import subprocess, os
        if os.name == 'nt':
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    
    def toggle_calendar(self):
        """絕對由 📅 時間按鈕控制日曆的展開與收合"""
        is_checked = self.btn_time_range.isChecked()
        self.calendar_widget.setVisible(is_checked)
        
        if is_checked and "全部時間" in self.btn_time_range.text():
            self.btn_time_range.setText("📅 自訂區間 (等待操作)...")
    
    def on_calendar_picking(self):
        """點了第一下，只更新日曆內的文字，不干擾主按鈕"""
        pass # UI 回饋已經由 RangeCalendarWidget 的 lbl_status 負責了

    def on_date_range_selected(self, start_date, end_date):
        """選取完畢，更新按鈕文字 (不自動收合)"""
        if start_date == end_date:
             date_str = f"📅 {start_date.strftime('%Y/%m/%d')}"
        else:
             date_str = f"📅 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"
        self.btn_time_range.setText(date_str)

    def on_calendar_cleared(self):
        """使用者按下清除日期"""
        self.btn_time_range.setText("📅 全部時間 (All Time)")
        self.time_filter_cleared.emit()

        self.check_filters_active()

    def on_calendar_apply(self, start_date, end_date):
        """點擊 [套用結果]：轉換為 Timestamp 並發送訊號"""
        date_str = f"📅 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"
        self.btn_time_range.setText(date_str)
        
        # 將日期轉為 Unix Timestamp (包含當天的 00:00:00 到 23:59:59)
        from datetime import datetime, time as dt_time
        start_ts = datetime.combine(start_date, dt_time.min).timestamp()
        end_ts = datetime.combine(end_date, dt_time.max).timestamp()
        
        self.time_filter_applied.emit(start_ts, end_ts)

        self.check_filters_active()

    def on_calendar_search(self, start_date, end_date):
        """點擊 [直接搜尋]：轉換為 Timestamp 並發送訊號 (狀態交由 MainWindow 判定)"""
        date_str = f"📅 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')}"
        self.btn_time_range.setText(date_str)
        
        from datetime import datetime, time as dt_time
        start_ts = datetime.combine(start_date, dt_time.min).timestamp()
        end_ts = datetime.combine(end_date, dt_time.max).timestamp()
        
        # 發送訊號讓 MainWindow 去要資料並驗證
        self.time_search_requested.emit(start_ts, end_ts)
        
        self.check_filters_active()

    # ==========================================
    # 🌟 神經中樞：過濾狀態檢查與清除
    # ==========================================
    def on_aspect_changed(self):
        """長寬比改變時，觸發狀態檢查，並通知 MainWindow 洗牌"""
        self.check_filters_active()
        self.aspect_changed.emit()

    def check_filters_active(self):
        """檢查是否有任何過濾器正在運作，並更新 UI 狀態 (包含分頁計數徽章)"""
        is_time_filtered = ("全部時間" not in self.btn_time_range.text() and "等待操作" not in self.btn_time_range.text())
        is_aspect_filtered = (self.combo_aspect.currentText() != "不限比例")
        
        # 🌟 計算啟用的過濾條件數量
        active_count = 0
        if is_time_filtered: active_count += 1
        if is_aspect_filtered: active_count += 1
        
        any_active = (active_count > 0)

        # 1. 層級三：屬性控制 (交由 QSS 處理顏色)
        time_state = "true" if is_time_filtered else "false"
        aspect_state = "true" if is_aspect_filtered else "false"
        
        self.lbl_time_title.setProperty("active", time_state)
        self.lbl_aspect_title.setProperty("active", aspect_state)
        
        self.lbl_time_title.style().unpolish(self.lbl_time_title)
        self.lbl_time_title.style().polish(self.lbl_time_title)
        self.lbl_aspect_title.style().unpolish(self.lbl_aspect_title)
        self.lbl_aspect_title.style().polish(self.lbl_aspect_title)

        # 2. 層級二：檢索過濾區塊底線
        self.sec_filter.set_status_active(any_active)

        # 🌟 3. 層級一：分頁標籤數字計數徽章 (Badge Count)
        # 取代原本容易衝突的底線做法，直接動態修改分頁文字
        if active_count > 0:
            self.tabs.setTabText(0, f"🔎 搜尋 ({active_count})")
        else:
            self.tabs.setTabText(0, "🔎 搜尋")

        # 4. 底部：顯示/隱藏置底的清除按鈕
        self.btn_clear_all.setVisible(any_active)

    def clear_all_filters(self):
        """一鍵清除所有過濾狀態"""
        # 1. 靜默重置長寬比 (不觸發訊號)
        self.combo_aspect.blockSignals(True)
        self.combo_aspect.setCurrentText("不限比例")
        self.combo_aspect.blockSignals(False)
        
        # 2. 重置日曆
        self.btn_time_range.setText("📅 全部時間 (All Time)")
        self.calendar_widget.clear_selection()
        
        # 3. 發送訊號給 MainWindow 執行還原
        self.time_filter_cleared.emit()
        
        # 4. 自我更新 UI 底線狀態
        self.check_filters_active()

# ==========================================
    # 🌟 相關度權重控制邏輯 (放在 InspectorPanel 底部)
    # ==========================================
    def load_weight_settings(self):
        ui_state = self.main_window.config.get("ui_state", {})
        mode = ui_state.get("search_calc_mode", "multiply")
        self.combo_calc_mode.setCurrentIndex(0 if mode == "multiply" else 1)
        
        self.slider_clip.setValue(ui_state.get("search_weight_clip", 100))
        self.slider_ocr.setValue(ui_state.get("search_weight_ocr", 100))
        self.slider_name.setValue(ui_state.get("search_weight_name", 40))
        
        thresh_mode = ui_state.get("search_thresh_mode", "auto")
        self.combo_threshold_mode.setCurrentIndex(0 if thresh_mode == "auto" else 1)
        self.slider_threshold.setValue(int(ui_state.get("search_thresh_val", 15)))
        
        self.update_weight_labels()
        self.on_calc_mode_changed(self.combo_calc_mode.currentIndex(), save=False)
        self.on_threshold_mode_changed(self.combo_threshold_mode.currentIndex(), save=False)

    def reset_weights_to_default(self):
        self.combo_calc_mode.setCurrentIndex(0)
        self.slider_clip.setValue(100)
        self.slider_ocr.setValue(100)
        self.slider_name.setValue(40)
        self.combo_threshold_mode.setCurrentIndex(0)
        self.slider_threshold.setValue(15)
        self.on_weight_slider_released()

    def on_calc_mode_changed(self, index, save=True):
        is_add = (index == 1)
        if is_add:
            self.slider_clip.setEnabled(False)
        else:
            self.slider_clip.setEnabled(True)
            
        # 🌟 把公式文字的更新移交給 update_weight_labels 統一處理
        self.update_weight_labels()
        if save: self.on_weight_slider_released()

    def on_threshold_mode_changed(self, index, save=True):
        is_manual = (index == 1)
        self.lbl_threshold_val.setVisible(is_manual)
        self.slider_threshold.setVisible(is_manual)
        if save: self.on_weight_slider_released()

    def update_weight_labels(self):
        is_add = (self.combo_calc_mode.currentIndex() == 1)
        
        # 取得實際滑桿的浮點數值
        clip_v = self.slider_clip.value() / 100.0
        ocr_v = self.slider_ocr.value() / 100.0
        name_v = self.slider_name.value() / 100.0
        
        # 加法模式的實際加分 (0.0 ~ 0.5)
        ocr_add = self.slider_ocr.value() / 200.0
        name_add = self.slider_name.value() / 200.0

        if is_add:
            self.lbl_clip_weight.setText("視覺權重 (CLIP 固定為原始分數)")
            self.lbl_ocr_weight.setText(f"文字加分 (OCR Bonus): +{ocr_add:.2f}")
            self.lbl_name_weight.setText(f"名稱加分 (Filename Bonus): +{name_add:.2f}")
            # 移除「公式:」並顯示動態數字
            self.lbl_formula.setText(f"CLIP分數 + (OCR命中? +{ocr_add:.2f}) + (檔名命中? +{name_add:.2f})")
        else:
            self.lbl_clip_weight.setText(f"視覺權重 (CLIP Weight): x{clip_v:.2f}")
            self.lbl_ocr_weight.setText(f"文字權重 (OCR Bonus): x{ocr_v:.2f}")
            self.lbl_name_weight.setText(f"名稱權重 (Filename Bonus): x{name_v:.2f}")
            # 計算基準乘法分數並顯示
            ocr_calc = 0.5 * ocr_v
            name_calc = 0.5 * name_v
            self.lbl_formula.setText(f"(CLIP × {clip_v:.2f}) + (OCR命中? {ocr_calc:.2f}) + (檔名命中? {name_calc:.2f})")
            
        self.lbl_threshold_val.setText(f"手動門檻值: {self.slider_threshold.value() / 100:.2f}")

    def on_weight_slider_released(self):
        """放開滑桿時，儲存設定並觸發 MainWindow 重新搜尋"""
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["search_calc_mode"] = "add" if self.combo_calc_mode.currentIndex() == 1 else "multiply"
        ui_state["search_weight_clip"] = self.slider_clip.value()
        ui_state["search_weight_ocr"] = self.slider_ocr.value()
        ui_state["search_weight_name"] = self.slider_name.value()
        ui_state["search_thresh_mode"] = "manual" if self.combo_threshold_mode.currentIndex() == 1 else "auto"
        ui_state["search_thresh_val"] = self.slider_threshold.value()
        self.main_window.config.set("ui_state", ui_state)
        self.weights_changed.emit(self.get_weight_config())

    def get_weight_config(self):
        """產生提供給 AI 引擎的參數包"""
        return {
            "mode": "add" if self.combo_calc_mode.currentIndex() == 1 else "multiply",
            "clip_w": self.slider_clip.value() / 100.0,
            "ocr_w": self.slider_ocr.value() / 100.0,
            "name_w": self.slider_name.value() / 100.0,
            "thresh_mode": "manual" if self.combo_threshold_mode.currentIndex() == 1 else "auto",
            "thresh_val": self.slider_threshold.value() / 100.0
        }

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
        
        # 設定歷史紀錄檔路徑
        self.history_file_path = os.path.join(self.config.app_root, "search_history.json")

        self.taskbar_ctrl = TaskbarController(self.winId())

        self.load_history()
        self.init_ui()
        
        self.indexer_worker = IndexerWorker(self.config, self)  # 加入 self 參數
        self.indexer_worker.status_update.connect(self.update_status) # 稍微改一下 status label 的用法
        self.indexer_worker.progress_update.connect(self.update_progress)
        self.indexer_worker.scan_finished.connect(self.on_scan_finished)
        self.indexer_worker.all_finished.connect(self.on_indexing_finished)

        # [修改 2] 連接訊號：當 AI 準備好時，執行 on_ai_loaded
        self.random_data_ready.connect(self.set_base_results)
        self.ai_ready.connect(self.on_ai_loaded)
        self.db_reloaded.connect(self.on_db_reloaded)

        QApplication.instance().installEventFilter(self)
        
        # 啟動背景載入 (這裡才會去建立 ImageSearchEngine)
        threading.Thread(target=self.load_engine, daemon=True).start()

        self.indexer_worker.start()

        # 將新的樣式表附加到現有的樣式表後
        current_stylesheet = self.styleSheet()

    def show_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.exec()

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

        #連接側邊欄的重新整理訊號
        self.sidebar.refresh_requested.connect(self.on_refresh_clicked)

        self.sidebar.settings_requested.connect(self.show_settings_dialog)

        main_layout.addWidget(self.sidebar)
        
        # --- 右側 ---
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setSpacing(0)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # ---------- 從這裡開始選取並覆蓋 ----------
        # ==========================================
        # 全新 Top Bar：極簡搜尋樞紐架構
        # ==========================================
        top_bar = QFrame()
        top_bar.setFixedHeight(60) 
        top_bar.setObjectName("TopBar")
        header_layout = QHBoxLayout(top_bar)
        header_layout.setContentsMargins(20, 0, 20, 0)
        header_layout.setSpacing(15)
        
        # 1. 左側：標題與模式導覽 (Identity & Breadcrumbs)
        self.breadcrumb_lbl = QLabel("Gallery") 
        self.breadcrumb_lbl.setObjectName("Breadcrumb")
        header_layout.addWidget(self.breadcrumb_lbl)
        header_layout.addStretch(1) 
        
        # 2. 置中：膠囊式搜尋樞紐 (Search Capsule)
        search_capsule = QFrame()
        # ==========================================
        # [修改 2] 設定最大與最小寬度，不再無限拉伸
        # ==========================================
        search_capsule.setMaximumWidth(550) # 限制最寬不超過 550px
        search_capsule.setMinimumWidth(300) # 視窗縮小時最窄保持 300px
        search_capsule.setFixedHeight(38)
        search_capsule.setObjectName("SearchCapsule")
        capsule_layout = QHBoxLayout(search_capsule)
        capsule_layout.setContentsMargins(15, 0, 5, 0)
        capsule_layout.setSpacing(5)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Search images...")
        self.input.setStyleSheet("QLineEdit { background: transparent; border: none; font-size: 14px; }")
        self.input.returnPressed.connect(self.start_search)
        capsule_layout.addWidget(self.input, stretch=1)

        # 內嵌 OCR 開關指示
        self.btn_ocr_toggle = QPushButton("[T]")
        self.btn_ocr_toggle.setCheckable(True)
        self.btn_ocr_toggle.setChecked(True)
        self.btn_ocr_toggle.setFixedSize(30, 30)
        self.btn_ocr_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ocr_toggle.setToolTip("啟用/停用 OCR 文字檢索")
        self.btn_ocr_toggle.setObjectName("OcrToggle")
        capsule_layout.addWidget(self.btn_ocr_toggle)
        
        # ==========================================
        # [修改 3] 拿掉原本的 stretch=1，讓搜尋框維持我們設定的寬度
        # ==========================================
        header_layout.addWidget(search_capsule) 
        
        # ==========================================
        # [修改 4] 加入右側彈簧，把搜尋框夾在正中央
        # ==========================================
        header_layout.addStretch(1)
        
        # 3. 右側：系統資訊與控制面板開關 (Global Actions)
        right_actions_layout = QHBoxLayout()
        right_actions_layout.setSpacing(15)

        # 系統訊息顯示
        self.status = QLabel("Initializing...")
        self.status.setObjectName("StatusBarText")
        right_actions_layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignVCenter)

        # 右側面板開關
        self.btn_toggle_inspector = QPushButton("📊")
        self.btn_toggle_inspector.setCheckable(True) # 允許有 checked 狀態
        self.btn_toggle_inspector.setFixedSize(36, 36)
        self.btn_toggle_inspector.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_inspector.setObjectName("InspectorToggle")
        self.btn_toggle_inspector.clicked.connect(self.toggle_inspector)
        right_actions_layout.addWidget(self.btn_toggle_inspector)

        header_layout.addLayout(right_actions_layout)

        right_layout.addWidget(top_bar)
        
        self.progress = QProgressBar(); self.progress.hide(); right_layout.addWidget(self.progress)
        
        # ==========================================
        # 使用 QSplitter 來完美分割左畫廊與右面板
        # ==========================================
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("MainSplitter")

        # List View (畫廊)
        self.list_view = QListView()
        self.list_view.setViewMode(QListView.ViewMode.IconMode)
        self.list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.list_view.setUniformItemSizes(True) 
        self.list_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setSpacing(MIN_SPACING)
        self.list_view.setMouseTracking(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setObjectName("GalleryList")

        


        self.current_card_size = QSize(CARD_SIZE[0], CARD_SIZE[1])
        self.current_thumb_size = QSize(CARD_SIZE[0], THUMBNAIL_SIZE[1])
        self.current_view_mode = "large"

        self.model = SearchResultsModel(self.current_thumb_size)
        self.delegate = ImageDelegate(self.current_card_size, THUMBNAIL_SIZE[1], self)
        
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)

        # 實例化分頁式右側面板
        self.inspector_panel = InspectorPanel(self)

        self.inspector_panel.sort_changed.connect(self.apply_gallery_sort)

        self.inspector_panel.time_filter_applied.connect(self.apply_time_filter_to_gallery)
        self.inspector_panel.time_search_requested.connect(self.search_by_time_range)
        self.inspector_panel.time_filter_cleared.connect(self.clear_time_filter)
        self.inspector_panel.aspect_changed.connect(self.apply_current_filters_and_show)
        self.inspector_panel.weights_changed.connect(self.on_weights_changed)

        # 將畫廊與右側面板加入 Splitter
        self.main_splitter.addWidget(self.list_view)
        self.main_splitter.addWidget(self.inspector_panel)
        self.main_splitter.setStretchFactor(0, 1) # 讓畫廊彈性佔據剩餘空間
        self.main_splitter.setStretchFactor(1, 0) # 讓面板保持固定寬度

        # [關鍵] 將 splitter 放入 right_layout
        right_layout.addWidget(self.main_splitter)
        
        # ==========================================
        # 狀態載入與事件綁定
        # ==========================================
        ui_state = self.config.get("ui_state", {})
        
        saved_mode = ui_state.get("view_mode", "large")
        if saved_mode != "large":
            self.change_view_mode(saved_mode)

        saved_expanded = ui_state.get("sidebar_expanded", True)
        if not saved_expanded:
            self.sidebar.toggle_sidebar() 

        self.resize(ui_state.get("window_width", 1280), ui_state.get("window_height", 900))
        if ui_state.get("is_maximized", False):
            self.showMaximized()
        
        self.list_view.clicked.connect(self.on_item_clicked)
        self.list_view.doubleClicked.connect(self.on_item_double_clicked)
        self.list_view.selectionModel().currentChanged.connect(self.on_selection_changed)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        main_layout.addWidget(right_container)
        
        # 其他浮動元件
        self.history_list = QListWidget(self);self.history_list.setObjectName("HistoryList"); self.history_list.hide(); self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(20); shadow.setColor(QColor(0, 0, 0, 100)); shadow.setOffset(0, 4); self.history_list.setGraphicsEffect(shadow)
        self.preview_overlay = PreviewOverlay(self)

    # ==========================================
    # init_ui() 結束，接下來是 MainWindow 的其他獨立函式
    # ==========================================

    def on_weights_changed(self, weight_config):
        q = self.input.text().strip()
        if q and not q.startswith("[Image]"):
            self.start_search(triggered_by_slider=True)

    

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
        if not self.engine: return
        self.current_folder_path = path
        
        # 🌟 [修改] 根據側邊欄自動切換下拉選單預設值
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

        # 2. 篩選特定資料夾
        self.breadcrumb_lbl.setText(f"Folder: {os.path.basename(path)}")
        
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
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),   # 🌟 補上
                    "height": item.get("height", 0)  # 🌟 補上
                })
            
            # 按時間排序
            results.sort(key=lambda x: x["mtime"], reverse=True)
            
            self.set_base_results(results)
            self.status.setText(f"Folder: {os.path.basename(path)} ({len(results)} items)")

        # [修改] MainWindow.eventFilter
    def eventFilter(self, obj, event):
        # 從設定檔讀取操作模式
        ui_state = self.config.get("ui_state", {})
        ocr_mode = ui_state.get("ocr_shift_mode", "hold")      # 預設為長按
        nav_mode = ui_state.get("preview_wasd_mode", "nav")    # 預設為單純移動

        # 1. 處理鍵盤按下 (KeyPress)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
        
            # --- Shift 鍵邏輯：查看 OCR ---
            if key == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible():
                    if ocr_mode == "toggle":
                        # 切換模式：反轉目前的鎖定狀態
                        self.is_ocr_locked = not self.is_ocr_locked
                        self.preview_overlay.set_ocr_visible(self.is_ocr_locked)
                    else:
                        # 長按模式：按下即顯示
                        self.preview_overlay.set_ocr_visible(True)
                return True 

            # --- W/A/S/D 方向鍵邏輯 ---
            if not self.input.hasFocus() and QApplication.activeWindow() == self:
                if key in (Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D):
                    # 判斷預覽視窗是否開啟
                    is_preview_active = self.preview_overlay.isVisible()
                
                    # 如果是「模式 1：關閉預覽」，且預覽正開啟時按下 WASD
                    if is_preview_active and nav_mode == "close":
                        self.preview_overlay.hide()
                        self.is_ocr_locked = False
                
                    # 執行底層移動
                    self.list_view.setFocus()
                    if key == Qt.Key.Key_W: self.send_nav_key(Qt.Key.Key_Up)
                    elif key == Qt.Key.Key_S: self.send_nav_key(Qt.Key.Key_Down)
                    elif key == Qt.Key.Key_A: self.send_nav_key(Qt.Key.Key_Left)
                    elif key == Qt.Key.Key_D: self.send_nav_key(Qt.Key.Key_Right)
                    return True
                
                elif key == Qt.Key.Key_Space:
                    self.toggle_preview()
                    return True
    
        # 2. 處理鍵盤放開 (KeyRelease) -> 關閉紅框 (僅限 Hold 模式)
        if event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Shift:
                if self.preview_overlay.isVisible():
                    # 只有在「長按模式」下，放開按鍵才會隱藏紅框
                    if ocr_mode != "toggle":
                        self.preview_overlay.set_ocr_visible(False)
                return True

        # 3. 處理滑鼠點擊 (MouseButtonPress) -> 顯示/隱藏歷史紀錄
        if event.type() == QEvent.Type.MouseButtonPress:
            click_pos = event.globalPosition().toPoint()
            
            # 點擊外部關閉歷史紀錄
            if self.history_list.isVisible():
                input_rect = QRect(self.input.mapToGlobal(QPoint(0, 0)), self.input.size())
                list_rect = QRect(self.history_list.mapToGlobal(QPoint(0, 0)), self.history_list.size())
                if not input_rect.contains(click_pos) and not list_rect.contains(click_pos): 
                    self.history_list.hide()

            # 點擊搜尋框彈出歷史紀錄
            if obj == self.input: 
                self.show_history_popup()

        # 最後確保所有未攔截的事件正常傳遞給父層
        return super().eventFilter(obj, event)

    # [新增] 輔助函式：發送模擬按鍵給 ListView
    def send_nav_key(self, key_code):
        from PyQt6.QtGui import QKeyEvent
        press_event = QKeyEvent(QEvent.Type.KeyPress, key_code, Qt.KeyboardModifier.NoModifier)
        release_event = QKeyEvent(QEvent.Type.KeyRelease, key_code, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.list_view, press_event)
        QApplication.sendEvent(self.list_view, release_event)

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
                    
                    # 🌟 從 Model 取出 L1 快取小圖
                    l1_pixmap = self.model._thumbnail_cache.get(item.path)
                    
                    # 🌟 傳遞給顯示層
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
                    
                    # 🌟 核心修改 1：從 Model 取出 L1 快取小圖
                    l1_pixmap = self.model._thumbnail_cache.get(item.path)
                    
                    # 🌟 核心修改 2：完整傳遞給顯示層，實現光速預覽！
                    self.preview_overlay.show_image(item, current_query, is_precise, l1_pixmap)
                    
                    # 🌟 [加碼優化] 保持 OCR 鎖定狀態
                    self.preview_overlay.set_ocr_visible(self.is_ocr_locked)

    

    


    def apply_gallery_sort(self):
        """對目前的 Gallery 圖片進行洗牌排序"""
        # 如果目前畫面上沒圖片，就不需要排
        # 🌟 [修正] 將 self.model.items 改為 self.model.all_items
        if not hasattr(self, 'model') or not self.model.all_items:
            return

        # 1. 取得使用者的設定狀態
        sort_by = self.inspector_panel.combo_sort.currentText()
        is_descending = (self.inspector_panel.btn_sort_order.text() == "↓")

        import os

        # 2. 根據不同的條件，定義 Python list sort 的 key 函數
        if sort_by == "搜尋相關度":
            # 🌟 複合鍵排序：第一優先比 is_ocr_match (True=1, False=0)，第二優先比 AI 分數
            key_func = lambda item: (item.is_ocr_match, item.score)
        elif sort_by == "日期":
            key_func = lambda item: item.mtime
        elif sort_by == "名稱":
            key_func = lambda item: item.filename.lower() # 轉小寫讓 a 和 A 視為相同
        elif sort_by == "類型":
            # 取得副檔名並轉小寫，例如 '.png', '.jpg'
            key_func = lambda item: os.path.splitext(item.filename)[1].lower()
        elif sort_by == "大小":
            # 動態取得檔案大小 (加上 try-except 防呆，以防檔案剛好被刪除)
            def get_size(item):
                try:
                    return os.path.getsize(item.path)
                except:
                    return 0
            key_func = get_size
        else:
            key_func = lambda item: item.mtime # 防呆預設

        # 3. 呼叫 Model 的排序方法
        self.model.sort_items(key_func, reverse=is_descending)
        
        # 4. 排序完後，自動將視窗滾動回到最上方，體驗更好
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
            
        # ==========================================
        # 🌟 2. 長寬比過濾 (容差 5%)
        # ==========================================
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

        if test_mode:
            return len(filtered) 
            
        # 3. 丟給畫面更新
        self.model.set_search_results(filtered)
        
        # 4. 順便套用目前的排序設定
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
        # 🌟 [修正] 將 len(self.model.items) 改為 len(self.model.all_items)
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

            self.on_folder_filter(self.current_folder_path)
    
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
            # 🌟 [防呆修復] 移除原本這裡同步呼叫 load_data_from_db 的動作
            # 避免在開始索引前卡死畫面，統一交給 on_indexing_finished 處理！
        else:
            print("[Indexer] No changes detected.")

    def on_indexing_finished(self):
        self.progress.hide()
        
        # [新增] 索引任務結束，關閉工作列進度條
        self.taskbar_ctrl.set_state(TBPF_NOPROGRESS)
        
        self.status.setText("Index Updated.")
        self.trigger_background_db_reload() # 🌟 觸發雙緩衝背景載入

    def trigger_background_db_reload(self):
        """🌟 [方案 B：雙緩衝核心] 在背景執行緒讀取資料庫，確保 UI 與搜尋功能不中斷"""
        if not self.engine: return
        self.status.setText("Synchronizing database in background...")
        
        def bg_reload():
            print("[Engine] Reloading engine data in background (Double Buffering)...")
            self.engine.load_data_from_db() # 此處內部已實作 Atomic Swap
            
            # 🌟 [關鍵修復] 改為發送空訊號，讓主執行緒自己去撈，徹底杜絕跨執行緒崩潰
            self.db_reloaded.emit()
            
        threading.Thread(target=bg_reload, daemon=True).start()
    
    def on_db_reloaded(self):
        """背景載入完畢，安全跳回主執行緒更新畫面"""
        if not self.engine: return
        
        # 🌟 [修正] 不要強制切回 ALL，而是維持目前所在的資料夾並重新整理！
        self.on_folder_filter(self.current_folder_path)
        self.refresh_sidebar()

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

        # 🌟 [新增終極鎖定] 直接告訴 ListView 每個網格的絕對大小
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
        
        # --- 修正 1: 標題項目空間 ---
        title_item = QListWidgetItem()
        title_widget = QLabel(" Recent Searches")
        # 移除內層多餘的 padding，稍微加大字體並設為粗體，確保乾淨清晰
        title_widget.setStyleSheet("color: #888888; font-size: 13px; font-weight: bold; background: transparent;")
        title_item.setFlags(Qt.ItemFlag.NoItemFlags)
        # 給予足夠的高度 (36px)，才不會被外層的 padding 擠壓切斷
        title_item.setSizeHint(QSize(0, 36))
        self.history_list.addItem(title_item)
        self.history_list.setItemWidget(title_item, title_widget)
        
        for text in self.search_history:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 44))
            widget = HistoryItemWidget(text, search_callback=self.trigger_history_search, delete_callback=self.delete_history_item)
            self.history_list.addItem(item); self.history_list.setItemWidget(item, widget)
            
        # --- 修正 2: 精準計算選單展開高度 ---
        input_pos = self.input.mapTo(self, QPoint(0, 0))
        # 標題高度(36) + (歷史紀錄數量 * 每個項目高度44) + 底部邊距緩衝(10)
        list_height = min(320, 36 + (len(self.search_history) * 44) + 10)
        
        self.history_list.setGeometry(input_pos.x(), input_pos.y() + self.input.height() + 8, self.input.width(), list_height)
        self.history_list.show()
        self.history_list.raise_()
    
    def load_engine(self):
        try:
            #self.status.setText("Loading Database...")
            
            # [新增] 載入模型時，工作列顯示綠色流光 (跑動條)
            self.taskbar_ctrl.set_state(TBPF_INDETERMINATE)
            
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
        
    def on_weights_changed(self, weight_config):
        q = self.input.text().strip()
        if q and not q.startswith("[Image]"):
            self.start_search(triggered_by_slider=True)

    def start_search(self, *args, triggered_by_slider=False):
        q = self.input.text().strip()
        if not q or not self.engine: return
        
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', q))
        if has_chinese and not getattr(self.engine, 'is_hf_tokenizer', True):
            if not triggered_by_slider:
                QMessageBox.warning(self, "不支援的語言", "您目前使用的 AI 模型僅支援「英文」搜尋...")
            return
        
        if not triggered_by_slider:
            self.add_to_history(q)
            self.history_list.hide()
            self.progress.show()
            self.progress.setRange(0, 0)
            self.status.setText("Searching...")
            self.breadcrumb_lbl.setText("Search Results")
            
            self.inspector_panel.combo_sort.blockSignals(True)
            self.inspector_panel.combo_sort.setCurrentText("搜尋相關度")
            self.inspector_panel.btn_sort_order.setText("↓")
            self.inspector_panel.combo_sort.blockSignals(False)

        limit = self.inspector_panel.combo_limit_panel.currentText()
        k = 100000 if limit == "All" else int(limit)
        
        # ==========================================
        # 🌟 [完美修復] 執行緒收容與 C++ 幽靈物件防護
        # ==========================================
        try:
            if getattr(self, 'worker', None):
                # 1. 切斷舊的訊號：避免你拉滑桿太快，舊的結果算完跑出來蓋掉新的畫面
                self.worker.batch_ready.disconnect()
                self.worker.finished_search.disconnect()
                
                # 2. 如果舊的還在跑，把它丟進收容所讓它跑完自然消滅
                if self.worker.isRunning():
                    if not hasattr(self, '_retained_workers'): self._retained_workers = []
                    self._retained_workers.append(self.worker)
                    self.worker.finished.connect(lambda w=self.worker: self._retained_workers.remove(w) if w in self._retained_workers else None)
        except (RuntimeError, TypeError):
            # 捕捉到幽靈物件！C++ 底層已被 deleteLater 刪除，安全忽略
            pass
        
        target_folder = None
        is_local_mode = (self.inspector_panel.combo_search_scope.currentIndex() == 0)
        
        # 只有當選單是「目前資料夾」(Index 0) 且側邊欄真的不是「ALL」時，才鎖定路徑
        if is_local_mode and self.current_folder_path != "ALL":
            target_folder = self.current_folder_path

        weight_config = self.inspector_panel.get_weight_config()
        self.worker = SearchWorker(self.engine, q, k, search_mode="text", 
                                   use_ocr=self.btn_ocr_toggle.isChecked(), 
                                   weight_config=weight_config,
                                   folder_path=target_folder)
        self.worker.batch_ready.connect(self.set_base_results)
        self.worker.finished_search.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def start_image_search(self, image_path):
        if not self.engine: return
        self.history_list.hide(); self.progress.show(); self.progress.setRange(0, 0)
        self.status.setText("Searching by Image...")
        self.input.setText(f"[Image] {os.path.basename(image_path)}")
        
        self.breadcrumb_lbl.setText("Similar Images")
        
        self.inspector_panel.combo_sort.blockSignals(True)
        self.inspector_panel.combo_sort.setCurrentText("搜尋相關度")
        self.inspector_panel.btn_sort_order.setText("↓")
        self.inspector_panel.combo_sort.blockSignals(False)
        
        limit = self.inspector_panel.combo_limit_panel.currentText()
        k = 100000 if limit == "All" else int(limit)
        
        # ==========================================
        # 🌟 [完美修復] 執行緒收容與 C++ 幽靈物件防護
        # ==========================================
        try:
            if getattr(self, 'worker', None):
                self.worker.batch_ready.disconnect()
                self.worker.finished_search.disconnect()
                if self.worker.isRunning():
                    if not hasattr(self, '_retained_workers'): self._retained_workers = []
                    self._retained_workers.append(self.worker)
                    self.worker.finished.connect(lambda w=self.worker: self._retained_workers.remove(w) if w in self._retained_workers else None)
        except (RuntimeError, TypeError):
            pass
        
        self.worker = SearchWorker(self.engine, image_path, k, search_mode="image")
        self.worker.batch_ready.connect(self.set_base_results)
        self.worker.finished_search.connect(self.on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

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

    # [新增] 攔截視窗關閉事件，儲存 UI 狀態
    # [新增] 攔截視窗關閉事件，儲存 UI 狀態
    def closeEvent(self, event):
        is_max = self.isMaximized()
        
        # 如果視窗被最大化，我們存 normalGeometry 的大小，這樣下次打開縮小時才不會變成 0x0
        if is_max:
            rect = self.normalGeometry()
            w, h = rect.width(), rect.height()
        else:
            w, h = self.width(), self.height()
            
        # ==========================================
        # [關鍵修復] 必須先取得「現有」的 ui_state，不能直接宣告新的空字典
        # 否則會把設定面板裡存好的快捷鍵和 OCR 設定全部洗掉！
        # ==========================================
        ui_state = self.config.get("ui_state", {})
        
        # 使用 dict.update() 只更新視窗相關的欄位，保留其他所有設定
        ui_state.update({
            "window_width": w,
            "window_height": h,
            "is_maximized": is_max,
            "sidebar_expanded": self.sidebar.is_expanded,
            "view_mode": getattr(self, 'current_view_mode', 'large')
        })
        
        # 寫入設定檔
        self.config.set("ui_state", ui_state)
        super().closeEvent(event)


    def on_finished(self, elapsed, total): self.progress.hide(); self.status.setText(f"Found {total} items ({elapsed:.2f}s)")

class OnboardingDialog(QDialog):
    """首次開啟的引導與自動硬體設定面板"""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config 
        self.setWindowTitle("歡迎使用 EyeSeeMore")
        self.setFixedSize(550, 420)
        self.setStyleSheet("background-color: #1e1e1e;")
        
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
    """常駐的主設定面板"""
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window 

        self.trans = self.main_window.config.translator
        self.setWindowTitle(self.trans.t("settings", "window_title", "設定 (Settings)"))

        self.resize(800, 600)
        self.setObjectName("SettingsDialog")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)

        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(200)
        self.nav_list.setObjectName("SettingsNavList")
        
        tabs = [
            self.trans.t("settings", "nav_folders", "📁 資料夾管理"),
            self.trans.t("settings", "nav_ai", "🧠 AI 引擎設定"),
            self.trans.t("settings", "nav_appearance", "🖥️ 介面與顯示"),
            self.trans.t("settings", "nav_hotkeys", "⌨️ 操作與快捷鍵"),
            self.trans.t("settings", "nav_performance", "⚡ 效能調整"), # NEW
            self.trans.t("settings", "nav_auto_tasks", "🕒 自動任務"), # NEW
            self.trans.t("settings", "nav_language", "🌍 語言與翻譯"),
            self.trans.t("settings", "nav_about", "ℹ️ 關於與說明")
        ]

        for tab in tabs:
            self.nav_list.addItem(tab)
            
        main_layout.addWidget(self.nav_list)
        self.stack = QStackedWidget()
        self.stack.setObjectName("SettingsStack")
        main_layout.addWidget(self.stack, stretch=1)
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        self.init_page_folders()
        self.init_page_ai()
        self.init_page_appearance()
        self.init_page_hotkeys()
        self.init_page_performance() # 🌟 加入呼叫
        self.init_page_auto_tasks()  # 🌟 加入呼叫
        self.init_page_language() # 語言設定頁面
        self.init_page_about()
        self.nav_list.setCurrentRow(0)

    def _create_page_container(self, title_text):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("PageHLine")
        layout.addWidget(line)
        line.setObjectName("PageHLine")
        layout.addWidget(line)
        return page, layout
    
    def _create_construction_button(self, text):
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setObjectName("WipButton") 
        return btn

    def init_page_folders(self):
        # 🌟 套用翻譯
        page, layout = self._create_page_container(self.trans.t("folders", "page_title", "📁 資料夾管理 (Folders)"))
        
        # 🌟 套用翻譯
        lbl_hint = QLabel(self.trans.t("folders", "hint", "提示：拖曳列表項目可改變排序。在項目上「點擊右鍵」可設定語系標記與圖示。"))
        lbl_hint.setObjectName("SettingsHint")
        layout.addWidget(lbl_hint)
        
        self.folder_list = TransparentDragListWidget()
        self.folder_list.setObjectName("FolderSettingsList")
        self.folder_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.folder_list.model().rowsMoved.connect(self.on_folder_order_changed)
        
        self.folder_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.show_folder_context_menu)
        
        layout.addWidget(self.folder_list)
        
        btn_layout = QHBoxLayout()
        # 🌟 套用翻譯
        self.btn_add = QPushButton(self.trans.t("folders", "btn_add", "+ 新增資料夾"))
        self.btn_del = QPushButton(self.trans.t("folders", "btn_remove", "- 移除選取"))
        
        self.btn_add.setProperty("cssClass", "ActionBtn")
        self.btn_del.setProperty("cssClass", "DangerBtn")
        
        self.btn_add.clicked.connect(self.on_add_folder)
        self.btn_del.clicked.connect(self.on_remove_folder)
        
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch(1)
        layout.addLayout(btn_layout)
        
        self.refresh_folder_list()
        self.stack.addWidget(page)

    def refresh_folder_list(self):
        self.folder_list.clear()
        config_folders = self.main_window.config.get("source_folders")
        stats = []
        if self.main_window.engine:
            stats = self.main_window.engine.get_folder_stats()
        stats_dict = {os.path.normpath(p): c for p, c in stats}
        
        for i, f in enumerate(config_folders, 1):
            path = f["path"]
            icon = f.get("icon", "")
            enabled_langs = f.get("enabled_langs", [])
            count = stats_dict.get(os.path.normpath(path), 0)
            
            display_icon = f"[{icon}]" if icon else f"[{i}]"
            base_name = os.path.basename(path)
            
            # 1. 建立底層的 List Item
            item = QListWidgetItem()
            item.setToolTip(path) 
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setSizeHint(QSize(0, 48)) # 設定固定的完美行高
            
            # 2. 建立自訂的列元件 (Row Widget)
            row_widget = QWidget()
            # 💡 讓滑鼠點擊「穿透」這個 Widget，右鍵選單跟拖曳排序才能正常運作
            row_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            
            # 3. 使用水平佈局 (QHBoxLayout) 達成像檔案總管一樣的欄位對齊
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(15, 0, 20, 0) # 左、上、右、下 邊距
            row_layout.setSpacing(10)
            
            # --- 欄位 A: 資料夾名稱 (加上 stretch=1 讓它像彈簧一樣佔滿剩餘空間) ---
            lbl_name = QLabel(f"{display_icon}   {base_name}")
            lbl_name.setStyleSheet("font-size: 15px; font-weight: 500; background: transparent;")
            row_layout.addWidget(lbl_name, stretch=1)
            
            # --- 欄位 B: 圖片數量 (固定寬度，靠右對齊) ---
            lbl_count = QLabel(f"({count})")
            lbl_count.setFixedWidth(60)
            lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_count.setObjectName("FolderCountLabel")
            row_layout.addWidget(lbl_count)
            
            # 與標籤區保持一段距離
            row_layout.addSpacing(20)
            
            # --- 欄位 C, D, E: 語系標籤 (固定寬度，確保直向對齊) ---
            for lang_code, display_text in [("ch", "CH"), ("jp", "JP"), ("kr", "KR")]:
                is_active = lang_code in enabled_langs
                lbl_tag = QLabel(f"[{display_text}]" if is_active else "")
                lbl_tag.setFixedWidth(40)  # 鎖死標籤寬度
                lbl_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
                
                lbl_tag.setObjectName("FolderTagLabel") # 🌟 發放身分證
                
                if is_active:
                    lbl_tag.setProperty("active", "true")
                else:
                    lbl_tag.setProperty("active", "false")
                    
                row_layout.addWidget(lbl_tag)
                
            # 將我們做好的列元件塞進清單中
            self.folder_list.addItem(item)
            self.folder_list.setItemWidget(item, row_widget)

    def show_folder_context_menu(self, pos):
        item = self.folder_list.itemAt(pos)
        if not item: return
        
        path = item.data(Qt.ItemDataRole.UserRole)
        config_folders = self.main_window.config.get("source_folders")
        
        # 找出該資料夾目前啟用的語系
        current_langs = []
        for f in config_folders:
            if os.path.normpath(f["path"]) == os.path.normpath(path):
                current_langs = f.get("enabled_langs", [])
                break
                
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 14px; } QMenu::item { padding: 8px 30px; }")
        
        # 1. 編輯圖示
        action_edit = QAction("✏️ 編輯圖示", self)
        action_edit.triggered.connect(self.on_edit_icon)
        menu.addAction(action_edit)
        
        menu.addSeparator()
        
        # 2~4. 多語系標記切換
        langs_map = [("ch", "中文"), ("jp", "日文"), ("kr", "韓文")]
        for lang_code, lang_name in langs_map:
            if lang_code in current_langs:
                action_lang = QAction(f"❌ 取消 {lang_name} OCR 標記", self)
            else:
                action_lang = QAction(f"✅ 添加 {lang_name} OCR 標記", self)
            
            # [修改] 將 lang_name (n=lang_name) 也傳遞給後面的判斷函式
            action_lang.triggered.connect(lambda checked, p=path, l=lang_code, n=lang_name: self.on_toggle_lang(p, l, n))
            menu.addAction(action_lang)
            
        menu.exec(self.folder_list.mapToGlobal(pos))

    def on_toggle_lang(self, path, lang_code, lang_name):
        # 1. 先找出該資料夾目前的狀態
        config_folders = self.main_window.config.get("source_folders")
        current_langs = []
        for f in config_folders:
            if os.path.normpath(f["path"]) == os.path.normpath(path):
                current_langs = f.get("enabled_langs", [])
                break
        
        # 2. 檢查實體模型是否存在
        is_adding = lang_code not in current_langs
        if is_adding:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            models_dir = os.path.join(base_dir, "models", "ocr")
            rec_path = os.path.join(models_dir, lang_code, "rec.onnx")
            dict_path = os.path.join(models_dir, lang_code, "dict.txt")
            
            is_installed = os.path.exists(rec_path) and os.path.exists(dict_path)
            
            # 3. 若未安裝，觸發跳轉
            if not is_installed:
                reply = QMessageBox.question(
                    self, "語言包未安裝", f"尚未安裝【{lang_name}】語言包。\n\n是否前往「AI 引擎設定」進行下載？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.nav_list.setCurrentRow(1)
                    self.ai_tabs.setCurrentIndex(1)
                return 

        # 4. 正常切換標記並更新畫面
        self.main_window.config.toggle_folder_lang(path, lang_code)
        self.refresh_folder_list()
        self.refresh_ocr_status()

        # ==========================================
        # [新增] 5. 避免「後續加上沒有偵測」的防呆引導
        # ==========================================
        if is_adding:
            reply = QMessageBox.question(
                self, 
                "標記已添加", 
                f"已成功對資料夾添加【{lang_name}】標記。\n\n是否要立即重新掃描此資料夾，為現有的圖片補跑 {lang_name} 的文字辨識？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.main_window.on_refresh_clicked()

    def on_folder_order_changed(self):
        ordered_paths = []
        for i in range(self.folder_list.count()):
            ordered_paths.append(self.folder_list.item(i).data(Qt.ItemDataRole.UserRole))
        self.main_window.config.update_folder_order(ordered_paths)
        self.main_window.refresh_sidebar() 

    def on_add_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            if self.main_window.config.add_source_folder(folder):
                self.refresh_folder_list()
                self.main_window.refresh_sidebar()
                QMessageBox.information(self, "Success", "加入成功！請點擊側邊欄的「⟳」按鈕進行掃描。")
            else:
                QMessageBox.warning(self, "重複", "此資料夾已經存在。")

    def on_remove_folder(self):
        item = self.folder_list.currentItem()
        if not item: return
        
        path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(self, '確認移除', f"確定要移除此資料夾的索引嗎？\n\n{path}\n\n(這只會從軟體中移除，不會刪除電腦裡的實體照片)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.main_window.config.remove_source_folder(path)
            if self.main_window.engine:
                try:
                    conn = sqlite3.connect(self.main_window.config.db_path)
                    conn.execute("PRAGMA foreign_keys = ON;") 
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM files WHERE folder_path = ?", (path,))
                    conn.commit()
                    conn.close()
                    
                    # 🌟 改為觸發背景雙緩衝載入
                    self.main_window.trigger_background_db_reload()
                except Exception as e:
                    print(f"Delete DB error: {e}")
            self.refresh_folder_list()
            # sidebar 的 refresh 會交由 db_reloaded 訊號統一處理

    def on_edit_icon(self):
        item = self.folder_list.currentItem()
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        
        icon, ok = QInputDialog.getText(self, "編輯圖示", "請輸入 1 個 Emoji (或最多 2 個英數字)：\n建議按 Win + . 叫出表情符號小鍵盤")
        if ok:
            icon = icon.strip()
            if len(icon) > 4: icon = icon[:4]
            self.main_window.config.update_folder_icon(path, icon)
            self.refresh_folder_list()
            self.main_window.refresh_sidebar()

    def init_page_ai(self):
        # 🌟 套用翻譯：主標題
        page, layout = self._create_page_container(self.trans.t("ai_engine", "page_title", "🧠 AI 引擎設定 (AI Engine)"))
        
        line = layout.itemAt(1).widget()
        if isinstance(line, QFrame):
            line.hide()
            
        self.dl_status_container = QWidget()
        dl_layout = QVBoxLayout(self.dl_status_container)
        dl_layout.setContentsMargins(0, 0, 0, 0)
        dl_layout.setSpacing(5)
        
        self.dl_status_label = QLabel("")
        self.dl_status_label.setObjectName("DlStatusLabel")
        self.dl_status_label.hide()
        
        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setValue(0)
        self.dl_progress.setTextVisible(False)
        self.dl_progress.setFixedHeight(2)
        self.dl_progress.setObjectName("DownloadProgress")
        
        dl_layout.addWidget(self.dl_status_label)
        dl_layout.addWidget(self.dl_progress)
        layout.insertWidget(1, self.dl_status_container)
        
        self.ai_tabs = QTabWidget()
        self.ai_tabs.setObjectName("AITabs")
        
        tab_clip = QWidget()
        clip_layout = QVBoxLayout(tab_clip)
        clip_layout.setContentsMargins(20, 20, 20, 20)
        clip_layout.setSpacing(15)
        
        # 🌟 套用翻譯：CLIP 群組標題
        group_clip = QGroupBox(self.trans.t("ai_engine", "grp_clip_title", "語意搜尋模型 (Semantic Models)"))
        clip_list_layout = QVBoxLayout(group_clip)
        clip_list_layout.setSpacing(10)
        
        current_model = self.main_window.config.get("model_name")
        # 🌟 套用翻譯：CLIP 模型清單與描述
        mock_clips = [
            {"name": self.trans.t("ai_engine", "model_std_name", "🟢 標準模式 (ViT-B-32)"), "id": "ViT-B-32", "pre": "laion2b_s34b_b79k", "desc": self.trans.t("ai_engine", "model_std_desc", "速度極快，佔用極低")},
            {"name": self.trans.t("ai_engine", "model_acc_name", "🔵 精準模式 (ViT-H-14)"), "id": "ViT-H-14", "pre": "laion2b_s32b_b79k", "desc": self.trans.t("ai_engine", "model_acc_desc", "準確度高，細節辨識佳")},
            {"name": self.trans.t("ai_engine", "model_multi_name", "🟣 多語系模式 (xlm-roberta)"), "id": "xlm-roberta-large-ViT-H-14", "pre": "frozen_laion5b_s13b_b90k", "desc": self.trans.t("ai_engine", "model_multi_desc", "支援中文等多國語言搜尋")}
        ]
        
        for item in mock_clips:
            row = QHBoxLayout()
            
            # 🌟 1. 動態取得主題顏色注入 HTML
            muted_color = self.main_window.theme_manager.current_colors.get("text_muted", "#888888")
            lbl_name = QLabel(f"{item['name']}<br><span style='color:{muted_color}; font-size:12px;'>{item['desc']}</span>")
            lbl_name.setFixedWidth(240)
            lbl_name.setTextFormat(Qt.TextFormat.RichText)
            
            is_active = (item['id'] == current_model)
            if is_active:
                status_text = self.trans.t("ai_engine", "status_running", "✅ 運行中")
                state_val = "running"  # 🌟 改用狀態標記
                btn_text = self.trans.t("ai_engine", "btn_in_use", "目前使用中")
                btn_enabled = False
            else:
                status_text = self.trans.t("ai_engine", "status_installed", "💾 已安裝")
                state_val = "installed" # 🌟 改用狀態標記
                btn_text = self.trans.t("ai_engine", "btn_switch", "切換並重啟")
                btn_enabled = True
                
            lbl_status = QLabel(status_text)
            lbl_status.setObjectName("ModelStatusLabel") # 🌟 發放身分證
            lbl_status.setProperty("state", state_val)   # 🌟 設定狀態
            
            btn_action = QPushButton(btn_text)
            btn_action.setFixedWidth(100)
            btn_action.setEnabled(btn_enabled)
            
            btn_action.setProperty("cssClass", "ActionBtn")
            if btn_enabled:
                # 正確綁定切換模型的事件，並把模型的 id 與 pre 傳過去
                btn_action.clicked.connect(lambda checked, m_id=item['id'], pre=item['pre']: self.on_switch_clip_model(m_id, pre))
            
            row.addWidget(lbl_name)
            row.addWidget(lbl_status)
            row.addStretch(1)
            row.addWidget(btn_action)
            clip_list_layout.addLayout(row)
            
            line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setObjectName("SolidLine")
            clip_list_layout.addWidget(line)
            
        clip_layout.addWidget(group_clip)
        clip_layout.addStretch(1)
        # 🌟 套用翻譯：CLIP 分頁標籤
        self.ai_tabs.addTab(tab_clip, self.trans.t("ai_engine", "tab_clip", "👁️ CLIP 語意模型"))
        
        tab_ocr = QWidget()
        ocr_layout = QVBoxLayout(tab_ocr)
        ocr_layout.setContentsMargins(20, 20, 20, 20)
        ocr_layout.setSpacing(15)
        
        # 🌟 套用翻譯：OCR 群組標題
        group_lang = QGroupBox(self.trans.t("ai_engine", "grp_ocr_title", "語系擴充包 (Language Packs)"))
        self.lang_layout = QVBoxLayout(group_lang)
        self.lang_layout.setSpacing(10)
        
        ocr_layout.addWidget(group_lang)
        ocr_layout.addStretch(1)
        # 🌟 套用翻譯：OCR 分頁標籤
        self.ai_tabs.addTab(tab_ocr, self.trans.t("ai_engine", "tab_ocr", "📝 OCR 文字辨識"))
        
        layout.addWidget(self.ai_tabs, stretch=1)
        self.stack.addWidget(page)
        
        self.lang_ui_elements = {}
        self.refresh_ocr_status()

    # ==========================================
    #  OCR 動態狀態判斷與下載邏輯
    # ==========================================
    def refresh_ocr_status(self):
        while self.lang_layout.count():
            item = self.lang_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub_item = item.layout().takeAt(0)
                    if sub_item.widget(): sub_item.widget().deleteLater()
                item.layout().deleteLater()
            
        base_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.path.join(base_dir, "models", "ocr")
        
        active_langs = set()
        for f in self.main_window.config.get("source_folders", []):
            active_langs.update(f.get("enabled_langs", []))
            
        # 🌟 套用翻譯
        langs = [
            ("ch", self.trans.t("ai_engine", "lang_ch", "🇨🇳 中文 (通用)")),
            ("jp", self.trans.t("ai_engine", "lang_jp", "🇯🇵 日文 (日本語)")),
            ("kr", self.trans.t("ai_engine", "lang_kr", "🇰🇷 韓文 (한국어)")),
            ("en", self.trans.t("ai_engine", "lang_en", "🇬🇧 英文 (English)"))
        ]
        
        self.lang_ui_elements.clear()
        
        for lang_code, name in langs:
            rec_path = os.path.join(models_dir, lang_code, "rec.onnx")
            dict_path = os.path.join(models_dir, lang_code, "dict.txt")
            is_installed = os.path.exists(rec_path) and os.path.exists(dict_path)
            is_running = lang_code in active_langs
            
            # 🌟 換成狀態指派，拔除寫死的 color
            if is_running and is_installed:
                status = self.trans.t("ai_engine", "status_running", "✅ 運行中")
                state_val = "running"
                btn_text = self.trans.t("ai_engine", "btn_enabled", "已啟用")
                btn_enabled = False
            elif is_installed:
                status = self.trans.t("ai_engine", "status_installed", "💾 已安裝")
                state_val = "installed"
                btn_text = self.trans.t("ai_engine", "btn_apply", "套用")
                btn_enabled = True
            else:
                status = self.trans.t("ai_engine", "status_not_installed", "📥 未安裝")
                state_val = "missing"
                btn_text = self.trans.t("ai_engine", "btn_import", "匯入")
                btn_enabled = True
                
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 5, 0, 5)
            
            lbl_name = QLabel(name)
            lbl_name.setFixedWidth(160)
            lbl_name.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")
            
            lbl_status = QLabel(status)
            lbl_status.setObjectName("ModelStatusLabel") # 🌟 發放身分證
            lbl_status.setProperty("state", state_val)   # 🌟 設定狀態
            
            btn_action = QPushButton(btn_text)
            btn_action.setFixedWidth(90)
            btn_action.setEnabled(btn_enabled)
            
            if btn_enabled and not is_installed:
                btn_action.setProperty("cssClass", "ActionBtn")
                btn_action.clicked.connect(lambda checked, l=lang_code: self.start_download_ocr(l))
            elif btn_enabled and is_installed:
                btn_action.setProperty("cssClass", "SuccessBtn")
                btn_action.clicked.connect(lambda checked: QMessageBox.information(self, "提示", "此語言包已就緒！..."))
            else:
                btn_action.setProperty("cssClass", "ActionBtn")
            
            row.addWidget(lbl_name)
            row.addWidget(lbl_status)
            row.addStretch(1)
            row.addWidget(btn_action)
            
            self.lang_layout.addWidget(row_widget)
            self.lang_ui_elements[lang_code] = {"status": lbl_status, "btn": btn_action}
            
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setObjectName("SolidLine")
            self.lang_layout.addWidget(line)

    def start_download_ocr(self, lang_code):
        from PyQt6.QtWidgets import QFileDialog
        # [離線版] 不再連網，改為讓使用者選擇已下載的 ZIP 模型包
        zip_path, _ = QFileDialog.getOpenFileName(self, f"選擇 {lang_code.upper()} 語言模型包 (ZIP)", "", "ZIP Files (*.zip)")
        
        if not zip_path:
            return # 使用者取消選擇

        self.dl_progress.setFixedHeight(12) 
        self.dl_progress.setValue(0)
        self.dl_status_label.setText(f"準備匯入 {lang_code.upper()} 語言包...")
        self.dl_status_label.show()
        
        # 鎖定所有下載按鈕，防止重複點擊
        for elems in self.lang_ui_elements.values():
            elems["btn"].setEnabled(False)
            
        # 啟動本地解壓縮 Worker
        self.dl_worker = OCRImportWorker(lang_code, zip_path)
        self.dl_worker.progress_update.connect(self.update_download_progress)
        self.dl_worker.finished_signal.connect(self.on_download_finished)
        self.dl_worker.start()

    def on_switch_clip_model(self, model_id, pretrained):
        # [離線版] 不再使用 ONNXExportWorker 轉換，改為直接檢查本地檔案
        base_dir = os.path.dirname(os.path.abspath(__file__))
        img_onnx_path = os.path.join(base_dir, "models", "onnx_clip", f"{model_id}_image.onnx")
        txt_onnx_path = os.path.join(base_dir, "models", "onnx_clip", f"{model_id}_text.onnx")
        
        if os.path.exists(img_onnx_path) and os.path.exists(txt_onnx_path):
            # 檔案存在，直接更新設定檔並提示重啟
            self.main_window.config.set("model_name", model_id)
            self.main_window.config.set("pretrained", pretrained)
            
            QMessageBox.information(
                self, 
                "切換成功", 
                "AI 模型已在本地找到並切換成功！\n\n為了確保記憶體安全釋放，程式將會關閉，請您手動重新啟動。"
            )
            QApplication.quit()
        else:
            # 檔案不存在，請使用者手動放入
            QMessageBox.warning(
                self, 
                "模型缺失", 
                f"在本地找不到 {model_id} 的 ONNX 檔案。\n\n請先將對應的模型檔案放入 `models/onnx_clip/` 資料夾中，或透過安裝包匯入。"
            )

    def update_download_progress(self, percent, msg):
        self.dl_progress.setValue(percent)
        self.dl_status_label.setText(msg)

    def on_download_finished(self, success, lang_code, msg):
        # 恢復變形：縮回 2px 的一般分隔線
        self.dl_progress.setFixedHeight(2)
        self.dl_progress.setValue(0)
        self.dl_status_label.hide()
        
        if success:
            QMessageBox.information(self, "下載成功", msg)
        else:
            QMessageBox.critical(self, "下載失敗", msg)
            
        # 重新掃描狀態並解鎖按鈕
        self.refresh_ocr_status()



# ==========================================
#  [NEW] 在設定介面加入快捷鍵設定區塊
# ==========================================
# 請將這段程式碼覆蓋回 SettingsDialog 的 init_page_appearance 方法

    def init_page_appearance(self):
        # 🌟 套用翻譯
        page, layout = self._create_page_container(self.trans.t("appearance", "page_title", "🖥️ 介面與顯示 (Appearance)"))
        ui_state = self.main_window.config.get("ui_state", {}) 

        

        # ==========================================
        # 🌟 [新增] 軟體主題切換
        # ==========================================
        layout.addWidget(QLabel("軟體主題配色 (Theme):"))
        self.combo_theme = QComboBox()
        self.combo_theme.setFixedHeight(38)
        

        # 從 ThemeManager 動態抓取可用的主題
        themes = self.main_window.theme_manager.get_available_themes()
        for i, theme in enumerate(themes):
            self.combo_theme.addItem(theme["name"], theme["id"])
            if theme["id"] == self.main_window.theme_manager.current_theme_id:
                self.combo_theme.setCurrentIndex(i)
                
        self.combo_theme.currentIndexChanged.connect(self.on_theme_changed)
        layout.addWidget(self.combo_theme)
        layout.addSpacing(10)

        layout.addWidget(QLabel(self.trans.t("appearance", "lbl_startup", "啟動時預設顯示的資料夾：")))
        self.combo_startup = QComboBox()
        self.combo_startup.setFixedHeight(38)

        # 1. 綁定「全部圖片」選項 (ID 固定為 "ALL")
        self.combo_startup.addItem(self.trans.t("appearance", "startup_all", "全部圖片 (All Images)"), "ALL")

        # 2. 動態載入使用者目前設定的實體資料夾
        source_folders = self.main_window.config.get("source_folders", [])
        for f in source_folders:
            path = f["path"]
            
            # 🌟 修復：嚴格檢查圖示，如果是空字串就給預設的資料夾符號
            icon = f.get("icon", "")
            if not icon:
                icon = "📁"
                
            folder_name = os.path.basename(path)
            
            # 🌟 拿掉醜醜的括號，直接顯示圖示與名稱，多加一個空格讓排版更透氣
            self.combo_startup.addItem(f"{icon}  {folder_name}", path)

        # 3. 讀取並套用目前的設定值
        startup_path = ui_state.get("default_startup_folder", "ALL")
        index_to_set = self.combo_startup.findData(startup_path)
        if index_to_set >= 0:
            self.combo_startup.setCurrentIndex(index_to_set)

        self.combo_startup.currentIndexChanged.connect(self.on_startup_folder_changed)
        layout.addWidget(self.combo_startup)
        layout.addSpacing(10)

        # 🌟 套用翻譯
        layout.addWidget(QLabel(self.trans.t("appearance", "lbl_size", "預設圖片顯示大小：")))
        self.combo_size = QComboBox()
        self.combo_size.setFixedHeight(38)
        
        
        # 🌟 套用翻譯到下拉選項
        self.combo_size.addItems([
            self.trans.t("appearance", "size_xl", "超大圖示 (Extra Large)"), 
            self.trans.t("appearance", "size_l", "大圖示 (Large)"), 
            self.trans.t("appearance", "size_m", "中圖示 (Medium)")
        ])
    
        mode_map = {"xl": 0, "large": 1, "medium": 2}
        self.combo_size.setCurrentIndex(mode_map.get(self.main_window.current_view_mode, 1))
        self.combo_size.currentIndexChanged.connect(self.on_view_mode_changed)
        layout.addWidget(self.combo_size)
        
        layout.addSpacing(10)
        # 🌟 套用翻譯
        layout.addWidget(QLabel(self.trans.t("appearance", "lbl_tag_mode", "OCR 懸浮標籤顯示方式：")))
        
        self.combo_tag_mode = QComboBox()
        self.combo_tag_mode.setFixedHeight(38) 
        
        
        # 🌟 套用翻譯到下拉選項
        self.combo_tag_mode.addItems([
            self.trans.t("appearance", "tag_anchored", "選項 A：固定在 OCR 框邊緣 (Anchored) - 推薦"), 
            self.trans.t("appearance", "tag_follow", "選項 B：跟隨滑鼠游標 (Follow Mouse)")
        ])
        
        tag_mode = ui_state.get("ocr_tag_mode", "anchored")
        self.combo_tag_mode.setCurrentIndex(0 if tag_mode == "anchored" else 1)
        self.combo_tag_mode.currentIndexChanged.connect(self.on_tag_mode_changed)
        layout.addWidget(self.combo_tag_mode)

        layout.addStretch(1)
        self.stack.addWidget(page)

    def on_theme_changed(self, index):
        theme_id = self.combo_theme.itemData(index)
        app = QApplication.instance()
        self.main_window.theme_manager.apply_theme(app, theme_id)

    # [新增] 儲存設定事件
    def on_tag_mode_changed(self, index):
        mode = "anchored" if index == 0 else "follow"
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["ocr_tag_mode"] = mode
        self.main_window.config.set("ui_state", ui_state)

    # [新增] 儲存啟動資料夾設定
    def on_startup_folder_changed(self, index):
        # 取得我們剛剛偷偷藏在選項背後的 Data (即 "ALL" 或 "實際路徑")
        selected_path = self.combo_startup.itemData(index)
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["default_startup_folder"] = selected_path
        self.main_window.config.set("ui_state", ui_state)

    def init_page_hotkeys(self):
        # 🌟 套用翻譯
        page, layout = self._create_page_container(self.trans.t("hotkeys", "page_title", "⌨️ 操作與快捷鍵 (Hotkeys)"))
        ui_state = self.main_window.config.get("ui_state", {})

        

        # 🌟 套用翻譯
        group_nav = QGroupBox(self.trans.t("hotkeys", "grp_nav_title", "預覽導覽行為"))
        layout_nav = QVBoxLayout(group_nav)
        layout_nav.setSpacing(10)
        lbl_nav = QLabel(self.trans.t("hotkeys", "lbl_nav", "空白鍵預覽時，按下 W/A/S/D 的反應："))
        lbl_nav.setObjectName("SettingsHint")
        layout_nav.addWidget(lbl_nav)
    
        self.combo_wasd = QComboBox()
        
        self.combo_wasd.setFixedHeight(38)
        self.combo_wasd.addItems([
            self.trans.t("hotkeys", "nav_opt_a", "選項 A：移動背景游標並保持預覽 (預設)"),
            self.trans.t("hotkeys", "nav_opt_b", "選項 B：關閉預覽圖 (快速偷瞄模式)"),
            self.trans.t("hotkeys", "nav_opt_c", "選項 C：切換預覽圖 (沉浸看圖模式)")
        ])
        nav_map = {"nav": 0, "close": 1, "sync": 2}
        self.combo_wasd.setCurrentIndex(nav_map.get(ui_state.get("preview_wasd_mode", "nav"), 0))
        self.combo_wasd.currentIndexChanged.connect(self.on_wasd_mode_changed)
        layout_nav.addWidget(self.combo_wasd)
        layout.addWidget(group_nav)

        # 🌟 套用翻譯
        group_ocr = QGroupBox(self.trans.t("hotkeys", "grp_ocr_title", "OCR 檢視方式"))
        layout_ocr = QVBoxLayout(group_ocr)
        layout_ocr.setSpacing(10)
        lbl_ocr = QLabel(self.trans.t("hotkeys", "lbl_ocr", "預覽圖片時，Shift 鍵的觸發邏輯："))
        lbl_ocr.setObjectName("SettingsHint")
        layout_ocr.addWidget(lbl_ocr)
    
        self.combo_ocr = QComboBox()
        
        self.combo_ocr.setFixedHeight(38)
        self.combo_ocr.addItems([
            self.trans.t("hotkeys", "ocr_opt_hold", "模式 A：長按 Shift 顯示紅框，放開隱藏 (Hold)"),
            self.trans.t("hotkeys", "ocr_opt_toggle", "模式 B：按一下 Shift 切換顯示 / 隱藏 (Toggle)")
        ])
        ocr_mode = ui_state.get("ocr_shift_mode", "hold")
        self.combo_ocr.setCurrentIndex(1 if ocr_mode == "toggle" else 0)
        self.combo_ocr.currentIndexChanged.connect(self.on_ocr_mode_changed)
        layout_ocr.addWidget(self.combo_ocr)
        layout.addWidget(group_ocr)

        # 🌟 套用翻譯
        group_visual = QGroupBox(self.trans.t("hotkeys", "grp_visual_title", "進階視覺效果 (Advanced Visuals)"))
        layout_visual = QVBoxLayout(group_visual)
        layout_visual.setSpacing(12)

        self.chk_precise_ocr = QCheckBox(self.trans.t("hotkeys", "chk_precise", "啟用精確文字高亮 (僅著色關鍵字部分)"))
        is_precise = ui_state.get("precise_ocr_highlight", False)
        self.chk_precise_ocr.setChecked(is_precise)
        
        self.chk_margin_comp = QCheckBox(self.trans.t("hotkeys", "chk_margin", "↳ 啟用邊緣縮減補償 (Margin Compensation)"))
        self.chk_margin_comp.setObjectName("SubCheckBox")
        is_margin = ui_state.get("margin_compensation", True) 
        self.chk_margin_comp.setChecked(is_margin)
        self.chk_margin_comp.setEnabled(is_precise)

        self.chk_precise_ocr.stateChanged.connect(self.on_precise_highlight_changed)
        self.chk_margin_comp.stateChanged.connect(self.on_margin_comp_changed)

        self.chk_dedup = QCheckBox(self.trans.t("hotkeys", "chk_dedup", "啟用多語系重疊防護 (Deduplication)"))
        is_dedup = ui_state.get("ocr_deduplication", True)
        self.chk_dedup.setChecked(is_dedup)
        self.chk_dedup.stateChanged.connect(self.on_dedup_changed)

        layout_visual.addWidget(self.chk_precise_ocr)
        layout_visual.addWidget(self.chk_margin_comp)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("DashedLine")
        layout_visual.addWidget(line)
        
        layout_visual.addWidget(self.chk_dedup)
        layout.addWidget(group_visual)
        
        layout.addStretch(1)
        self.stack.addWidget(page)

    def init_page_performance(self):
        page, layout = self._create_page_container(self.trans.t("performance", "page_title", "⚡ 效能調整 (Performance)"))
        
        # 🌟 呼叫公用函式，自動套用 QSS 樣式
        btn_wip = self._create_construction_button(self.trans.t("performance", "wip_text", "🚧 施工中：動畫效果與系統資源控制"))
        layout.addWidget(btn_wip)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def init_page_auto_tasks(self):
        # 1. 建立頁面容器與主佈局
        page, layout = self._create_page_container(self.trans.t("auto_tasks", "page_title", "🕒 自動任務 (Automated Tasks)"))
        
        # 移除頂部的分隔線，保持與 AI 引擎頁面一致的乾淨外觀
        line = layout.itemAt(1).widget()
        if isinstance(line, QFrame):
            line.hide()

        # 2. 建立分頁標籤 (仿照 self.ai_tabs)
        self.auto_tabs = QTabWidget()
        self.auto_tabs.setObjectName("AutoTabs")
        
        # ==========================================
        # 分頁 1: OCR 任務資料夾
        # ==========================================
        tab_ocr_tasks = QWidget()
        ocr_tasks_layout = QVBoxLayout(tab_ocr_tasks)
        ocr_tasks_layout.setContentsMargins(20, 20, 20, 20)
        ocr_tasks_layout.setSpacing(15)
        
        # 群組標題 (仿照 AI 引擎的 QGroupBox)
        group_ocr = QGroupBox(self.trans.t("auto_tasks", "grp_ocr_folders", "資料夾 OCR 任務綁定 (Folder OCR Tasks)"))
        group_ocr_layout = QVBoxLayout(group_ocr)
        group_ocr_layout.setSpacing(10)
        
        # 頂部說明文字
        lbl_desc = QLabel(self.trans.t("auto_tasks", "lbl_ocr_desc", "為資料夾指定背景自動辨識的語系。當系統偵測到新圖片時，將自動執行對應的文字萃取任務。"))
        lbl_desc.setObjectName("SettingsHint")
        group_ocr_layout.addWidget(lbl_desc)
        
        # 建立一個專屬容器用來放動態列表，方便未來刷新 (Clear & Redraw)
        self.ocr_tasks_container = QWidget()
        self.ocr_tasks_list_layout = QVBoxLayout(self.ocr_tasks_container)
        self.ocr_tasks_list_layout.setContentsMargins(0, 5, 0, 0)
        self.ocr_tasks_list_layout.setSpacing(5)
        group_ocr_layout.addWidget(self.ocr_tasks_container)
        
        ocr_tasks_layout.addWidget(group_ocr)
        ocr_tasks_layout.addStretch(1)
        
        # 加入分頁
        self.auto_tabs.addTab(tab_ocr_tasks, self.trans.t("auto_tasks", "tab_ocr_mapping", "📝 OCR 任務綁定"))
        
        # ==========================================
        # 分頁 2: 背景排程 (預留施工中)
        # ==========================================
        tab_schedule = QWidget()
        schedule_layout = QVBoxLayout(tab_schedule)
        schedule_layout.setContentsMargins(20, 20, 20, 20)
        
        btn_wip = self._create_construction_button(self.trans.t("auto_tasks", "wip_schedule", "🚧 施工中：背景定時掃描與效能限制"))
        schedule_layout.addWidget(btn_wip)
        schedule_layout.addStretch(1)
        
        self.auto_tabs.addTab(tab_schedule, self.trans.t("auto_tasks", "tab_schedule", "⏳ 排程與控制"))
        
        # 將 TabWidget 加入主畫面
        layout.addWidget(self.auto_tabs, stretch=1)
        self.stack.addWidget(page)
        
        # 初始化載入畫面
        self.refresh_ocr_task_list()

    def refresh_ocr_task_list(self):
        """動態生成 OCR 任務資料夾的 UI 列表"""
        # 1. 清空舊的 UI 元件
        while self.ocr_tasks_list_layout.count():
            item = self.ocr_tasks_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub_item = item.layout().takeAt(0)
                    if sub_item.widget(): sub_item.widget().deleteLater()
                item.layout().deleteLater()

        # 2. 讀取設定檔中的資料夾
        config_folders = self.main_window.config.get("source_folders", [])
        
        if not config_folders:
            lbl_empty = QLabel("目前沒有任何圖片資料夾，請先前往「資料夾管理」新增。")
            lbl_empty.setObjectName("SettingsWarning")
            self.ocr_tasks_list_layout.addWidget(lbl_empty)
            return

        # 3. 仿照 AI 引擎列表的風格逐一繪製
        for i, f in enumerate(config_folders):
            path = f.get("path", "")
            
            # 🌟 修正：嚴格檢查圖示，如果是空字串就給預設的資料夾符號
            icon = f.get("icon", "")
            if not icon:
                icon = "📁"
                
            enabled_langs = f.get("enabled_langs", [])
            
            row_widget = QWidget()
            row_widget.setObjectName("OcrTaskRow")
            
            # 🌟 關鍵魔法：啟用背景繪製能力
            row_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            
            # 🌟 動態取得主題的 Hover 顏色，寫入區域 QSS
            bg_hover = self.main_window.theme_manager.current_colors.get("bg_hover", "#383838")
            row_widget.setStyleSheet(f"""
                QWidget#OcrTaskRow {{
                    background-color: transparent;
                    border-radius: 8px;
                }}
                QWidget#OcrTaskRow:hover {{
                    background-color: {bg_hover};
                }}
            """)
            
            # 設定手型游標，暗示這整列未來可以點擊互動
            row_widget.setCursor(Qt.CursorShape.PointingHandCursor)

            row = QHBoxLayout(row_widget)
            # 🌟 把上下左右稍微撐開一點 (原本是 0,5,0,5)，讓 Hover 的色塊包覆得更漂亮
            row.setContentsMargins(10, 8, 10, 8) 
            
            # --- 左側：圖示與路徑 (RichText 雙層顯示) ---
            folder_name = os.path.basename(path)
            muted_color = self.main_window.theme_manager.current_colors.get("text_muted", "#888888")
            lbl_name = QLabel(f"<span style='font-size:15px; font-weight:bold;'>{icon}  {folder_name}</span><br><span style='color:{muted_color}; font-size:12px;'>{path}</span>")
            lbl_name.setFixedWidth(260)
            lbl_name.setTextFormat(Qt.TextFormat.RichText)
            
            # --- 中間：狀態與語系標籤 ---
            tags_layout = QHBoxLayout()
            tags_layout.setSpacing(5)
            tags_layout.setContentsMargins(10, 0, 0, 0)
            
            if enabled_langs:
                for lang in enabled_langs:
                    lbl_tag = QLabel(f"[{lang.upper()}]")
                    lbl_tag.setObjectName("FolderTagLabel")
                    lbl_tag.setProperty("active", "true") # 套用綠色/藍色高亮標籤樣式
                    lbl_tag.setFixedWidth(42)
                    lbl_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    tags_layout.addWidget(lbl_tag)
                
            tags_layout.addStretch(1)
            
            # 將元件加入主列中
            row.addWidget(lbl_name)
            row.addLayout(tags_layout, stretch=1)
            
            self.ocr_tasks_list_layout.addWidget(row_widget)
            
            # 加入分隔線
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setObjectName("SolidLine")
            self.ocr_tasks_list_layout.addWidget(line)

    def on_precise_highlight_changed(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        
        # [防呆連動] 如果主開關被關閉，強制取消勾選子開關，並將其變為不可用
        if not is_checked:
            self.chk_margin_comp.setChecked(False)  # 這裡會自動觸發 on_margin_comp_changed 進行存檔
            
        self.chk_margin_comp.setEnabled(is_checked)

        # 存入 config.json
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["precise_ocr_highlight"] = is_checked
        self.main_window.config.set("ui_state", ui_state)

    def on_margin_comp_changed(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        
        # 存入 config.json
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["margin_compensation"] = is_checked
        self.main_window.config.set("ui_state", ui_state)

    def on_dedup_changed(self, state):
        is_checked = (state == Qt.CheckState.Checked.value)
        
        # 存入 config.json
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["ocr_deduplication"] = is_checked
        self.main_window.config.set("ui_state", ui_state)

    def on_wasd_mode_changed(self, index):
        wasd_map = {0: "nav", 1: "close", 2: "sync"}
        selected_mode = wasd_map.get(index, "nav")
        
        # 存入 config.json
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["preview_wasd_mode"] = selected_mode
        self.main_window.config.set("ui_state", ui_state)

    def on_ocr_mode_changed(self, index):
        # 0 是 Hold, 1 是 Toggle
        mode = "toggle" if index == 1 else "hold"
        
        # 存入 config.json
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["ocr_shift_mode"] = mode
        self.main_window.config.set("ui_state", ui_state)

    def on_view_mode_changed(self, index):
        # 將 index (0,1,2) 轉回對應的字串代號
        mode_map = {0: "xl", 1: "large", 2: "medium"}
        selected_mode = mode_map.get(index, "large")
        self.main_window.change_view_mode(selected_mode)

    def init_page_language(self):
        # 🌟 套用翻譯：主標題
        page, layout = self._create_page_container(self.trans.t("language_page", "page_title", "🌍 語言與翻譯 (Language)"))
        ui_state = self.main_window.config.get("ui_state", {})
        current_lang = ui_state.get("language", "zh_TW") 

        # 🌟 套用翻譯：群組標題
        group_lang = QGroupBox(self.trans.t("language_page", "grp_lang_title", "顯示語言 (Display Language)"))
        layout_lang = QVBoxLayout(group_lang)
        layout_lang.setSpacing(10)

        # 🌟 套用翻譯：說明文字
        lbl_desc = QLabel(self.trans.t("language_page", "lbl_desc", "請選擇軟體的顯示語言。系統將會從 languages/ 資料夾讀取對應的翻譯檔。\n(變更語言後，將於下次啟動程式時生效)"))
        lbl_desc.setObjectName("SettingsHint")
        layout_lang.addWidget(lbl_desc)

        self.combo_lang = QComboBox()
        self.combo_lang.setFixedHeight(38)
        
        
        self.lang_options = []
        base_dir = os.path.dirname(os.path.abspath(__file__))
        lang_dir = os.path.join(base_dir, "languages")

        if os.path.exists(lang_dir):
            for filename in os.listdir(lang_dir):
                if filename.endswith(".json"):
                    code = filename[:-5]
                    file_path = os.path.join(lang_dir, filename)
                    display_name = code
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            display_name = data.get("metadata", {}).get("display_name", code)
                    except Exception as e:
                        print(f"解析 {filename} 失敗: {e}")
                    self.lang_options.append({"name": display_name, "code": code})
        
        if not self.lang_options:
            self.lang_options = [{"name": "系統預設 (zh_TW)", "code": "zh_TW"}]
        
        for item in self.lang_options:
            self.combo_lang.addItem(item["name"], item["code"])

        for i, item in enumerate(self.lang_options):
            if item["code"] == current_lang:
                self.combo_lang.setCurrentIndex(i)
                break

        self.combo_lang.currentIndexChanged.connect(self.on_language_changed)
        layout_lang.addWidget(self.combo_lang)

        # 🌟 套用翻譯：重啟提示
        self.lbl_lang_restart_hint = QLabel(self.trans.t("language_page", "restart_hint", "⚠️ 語言已變更！請手動重新啟動程式以套用新語言。"))
        self.lbl_lang_restart_hint.setObjectName("SettingsWarning")
        self.lbl_lang_restart_hint.hide() 
        layout_lang.addWidget(self.lbl_lang_restart_hint)

        layout.addWidget(group_lang)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def on_language_changed(self, index):
        # 取得隱藏的語言代碼 (例如 "zh_TW")
        selected_code = self.combo_lang.itemData(index)
        
        # 存入 config.json
        ui_state = self.main_window.config.get("ui_state", {})
        ui_state["language"] = selected_code
        self.main_window.config.set("ui_state", ui_state)
        
        # 顯示重啟提示
        self.lbl_lang_restart_hint.show()

    def init_page_about(self):
        # 🌟 套用翻譯：主標題
        page, layout = self._create_page_container(self.trans.t("about_page", "page_title", "ℹ️ 關於與說明 (Help & About)"))

        title_label = QLabel("<h2>EyeSeeMore</h2>")
        layout.addWidget(title_label)

        # 🌟 套用翻譯：版本號
        version_info = QLabel(self.trans.t("about_page", "version_lbl", "<b>版本號：</b> V0.5.0-alpha<br><b>建置日期：</b> 2026-03-18"))
        layout.addWidget(version_info)

        # 🌟 套用翻譯：HTML 核心技術區塊 (透過字串拼接)
        tech_text = (
            self.trans.t("about_page", "tech_title", "<h3>技術致敬 (Core Technologies)</h3><p>本軟體由以下優秀的開源生態系驅動：</p>") +
            "<ul>" +
            self.trans.t("about_page", "tech_ui", "<li><b>介面開發：</b> Python & PyQt6</li>") +
            self.trans.t("about_page", "tech_ai", "<li><b>AI 推理引擎：</b> ONNX Runtime</li>") +
            self.trans.t("about_page", "tech_ocr", "<li><b>文字辨識 (OCR)：</b> ONNX-OCR</li>") +
            self.trans.t("about_page", "tech_img", "<li><b>影像與資料處理：</b> OpenCV, Pillow (PIL), NumPy</li>") +
            self.trans.t("about_page", "tech_db", "<li><b>資料存儲：</b> SQLite3</li>") +
            self.trans.t("about_page", "tech_perf", "<li><b>系統監控：</b> psutil (效能優化)</li>") +
            "</ul>"
        )
        tech_label = QLabel(tech_text)
        layout.addWidget(tech_label)

        # 🌟 套用翻譯：連結與版權
        link_color = self.main_window.theme_manager.current_colors.get("text_link", "#00aaff")
        link_html = f'<a href="https://github.com/Magnesiumnuclear/EyeSeeMore" style="color: {link_color}; text-decoration: none;">🌐 專案 GitHub 主頁 (回報問題與建議)</a>'
        link_label = QLabel(self.trans.t("about_page", "github_link", link_html))
        link_label.setOpenExternalLinks(True) 
        layout.addWidget(link_label)

        copyright_label = QLabel(self.trans.t("about_page", "copyright", "<br><small>© 2026 HO99 Licensed under GPL v3.</small>"))
        layout.addWidget(copyright_label)

        layout.addStretch(1) 
        self.stack.addWidget(page)

if __name__ == "__main__":
    app_config = ConfigManager()

    current_lang = app_config.get("ui_state", {}).get("language", "zh_TW")
    app_config.translator = Translator(current_lang)

    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        
    app = QApplication(sys.argv)
    
    # 🌟 [修改] 棄用寫死的 WIN11_STYLESHEET，改用 ThemeManager
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
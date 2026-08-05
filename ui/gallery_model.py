"""
SearchResultsModel & GalleryListView
=====================================
從 Blur-main.py 抽離的畫廊 Model 與 View：
  • SearchResultsModel  – QAbstractListModel，管理搜尋結果與縮圖快取
  • GalleryListView     – QListView，支援多選框選與拖拽匯出
"""

from __future__ import annotations

from collections import OrderedDict

from PyQt6.QtCore import (
    QAbstractListModel, QMimeData, QModelIndex, QPoint, QSize,
    Qt, QTimer, QThreadPool, QUrl,
)
from PyQt6.QtGui import QBrush, QColor, QDrag, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QListView

from ui.widgets.image_delegate import ThumbnailLoader
from ui.widgets.image_delegate import FunnelCardItem, ImageItem


class SearchResultsModel(QAbstractListModel):
    """核心 Model：管理搜尋結果列表與圖片快取 (完全原生虛擬化)"""
    def __init__(self, item_size, perf_config=None):
        super().__init__()
        self.all_items = []
        self._pending_batch_requests = OrderedDict()
        self._batch_timer_active = False

        self.item_size = item_size
        self._thumbnail_cache = OrderedDict()

        cfg = perf_config or {}
        self._base_cache_size = int(cfg.get("thumbnail_cache_size", 1000))
        self.CACHE_SIZE = self._base_cache_size

        self._loading_set = set()
        self._active_workers = {}

        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(int(cfg.get("thumbnail_thread_count", 8)))

        self._pending_updates = set()
        self.update_timer = QTimer()
        self.update_timer.setInterval(50)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._flush_updates)

    def update_target_size(self, new_size):
        self.item_size = new_size

        # XL 模式（卡片寬 > 256px）將快取縮減至設定值的 1/4，至少保留 100 張
        if new_size.width() > 256:
            self.CACHE_SIZE = max(100, self._base_cache_size // 4)
        else:
            self.CACHE_SIZE = self._base_cache_size

        self._thumbnail_cache.clear()
        self._loading_set.clear()

    def set_search_results(self, results_dict_list):
        self.beginResetModel()

        for worker in self._active_workers.values():
            worker.is_cancelled = True
        self._active_workers.clear()

        # 舊結果的待更新列號必須一併作廢：否則舊清單第 300 列的縮圖回報
        # 會對只剩 100 列的新 Model 發出越界的 dataChanged (整個 viewport 空轉重繪)
        self.update_timer.stop()
        self._pending_updates.clear()
        # 購物車裡的舊路徑同樣丟棄；_batch_timer_active 不動，
        # 因為已排程的 singleShot 仍會觸發並自行歸零，重設反而會排到第二顆計時器
        self._pending_batch_requests.clear()

        self.all_items = []
        self.path_to_row = {}

        self._thumbnail_cache.clear()
        self._loading_set.clear()

        for idx, res in enumerate(results_dict_list):
            # 漏斗卡片特殊處理
            if res.get('__funnel_card__'):
                item = FunnelCardItem(
                    raw_count=res['raw_count'],
                    after_date=res['after_date'],
                    after_aspect=res['after_aspect'],
                    final_count=res['final_count'],
                )
                self.all_items.append(item)
                self.path_to_row[item.path] = idx
                continue

            item = ImageItem(
                path=res['path'],
                filename=res['filename'],
                score=res['score'],
                ocr_text=res.get('ocr_text', ""),
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
        """排序時直接對 all_items 排序，不再需要洗牌第一批。
        漏斗卡片永遠緊跟在所有釘選圖之後，不參與一般排序邏輯。"""
        self.layoutAboutToBeChanged.emit()

        # 洗牌前先記下每個 persistent index 當時指向的「項目本身」。
        # rowCount 沒變，Qt 不會自己搬動這些索引 —— 若不重新對應，
        # 選取／currentIndex 會黏在舊列號上（指到另一張圖），
        # 導致 Inspector 顯示 A、高亮卻是 B，拖曳匯出更會抓到錯的檔案。
        old_indexes = self.persistentIndexList()
        anchored_items = []
        for idx in old_indexes:
            row = idx.row()
            anchored_items.append(self.all_items[row] if 0 <= row < len(self.all_items) else None)

        # 抽出漏斗卡片（只有 0 或 1 張）
        funnel_items = [it for it in self.all_items if getattr(it, 'is_funnel_card', False)]
        other_items  = [it for it in self.all_items if not getattr(it, 'is_funnel_card', False)]

        # 對一般圖片排序
        other_items.sort(key=key_func, reverse=reverse)

        # 找到第一張非釘選圖的位置，將漏斗卡片插在釘選圖後、其他圖前
        insert_pos = sum(1 for it in other_items if it.is_pinned)
        for f in funnel_items:
            other_items.insert(insert_pos, f)

        self.all_items = other_items
        self.path_to_row = {item.path: i for i, item in enumerate(self.all_items)}

        # 直接沿用剛重建的 path_to_row 查新列號（漏斗卡片有固定虛擬路徑，一樣查得到）；
        # 查不到的項目一律換成無效索引，讓 Qt 自行丟棄該筆選取
        new_indexes = []
        for idx, item in zip(old_indexes, anchored_items):
            new_row = self.path_to_row.get(item.path) if item is not None else None
            if new_row is None:
                new_indexes.append(QModelIndex())
            else:
                new_indexes.append(self.index(new_row, idx.column()))
        self.changePersistentIndexList(old_indexes, new_indexes)

        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return len(self.all_items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.all_items)):
            return None

        item = self.all_items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return item.filename
        elif role == Qt.ItemDataRole.UserRole:
            return item
        elif role == Qt.ItemDataRole.DecorationRole:
            # 漏斗卡片不需要縮圖，直接略過讀取
            if getattr(item, 'is_funnel_card', False):
                return None

            if item.path in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(item.path)
                return self._thumbnail_cache[item.path]

            # 單幀批量攔截：不直接發送任務，而是先丟進「購物車」
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

        # 核心過濾魔法：判斷是「精確導航」還是「快速拖拽」
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

    def request_thumbnail(self, file_path):
        self._loading_set.add(file_path)
        loader = ThumbnailLoader(file_path, self.item_size)
        loader.signals.result.connect(self.on_thumbnail_loaded)
        self._active_workers[file_path] = loader
        self.thread_pool.start(loader)

    def on_thumbnail_loaded(self, file_path, pixmap, is_final):
        # 只有收到「最終訊號」，才把任務從活躍佇列中移除
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
            # 關鍵：必須告訴 Qt 這個項目「允許被拖拽」
            return default_flags | Qt.ItemFlag.ItemIsDragEnabled

        return default_flags


class GalleryListView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 啟動進階多選與框選模式
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionRectVisible(True) # 啟用半透明框選遮罩
        self.setDragEnabled(True)          # 啟用拖拽
        self.setAcceptDrops(False)         # 畫廊本身不接收外部檔案丟入
        # 明確宣告這裡「只允許拖出，不允許拖入」
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

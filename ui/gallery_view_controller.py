"""
GalleryViewController  –  畫廊視圖控制器
============================================
從 MainWindow 抽離的職責：
  • 搜尋結果的儲存與多層過濾（時間區間、長寬比、Limit 截斷）
  • 排序邏輯（搜尋相關度 / 日期 / 名稱 / 類型 / 大小，釘選永遠置頂）
  • 漏斗統計快取（raw → date → aspect → final）
  • 空狀態診斷覆蓋層的顯示／隱藏
  • 視圖模式 (xl/large/medium) 切換與卡片尺寸計算
  • Grid 佈局動態均分演算法（resize/sidebar 切換時觸發）
  • 時間區間直接搜尋的整個工作流（含防呆與狀態還原）

設計原則：
  • 繼承 QObject，使用 pyqtSignal 對外發射 UI 層級的更新事件
  • 直接持有 list_view / model / delegate / inspector_panel /
    empty_state_overlay / nav 等 UI 元件參照（如同 SidebarWidget 等
    UI 控制器的慣例）
  • status_label / search_input 採訊號解耦（避免雙向 UI 依賴）
  • engine 採延遲注入（與 SearchOrchestrator / IndexingLifecycleHandler 同模式）

使用方式：
    gallery_ctrl = GalleryViewController(
        list_view=mw.list_view, model=mw.model, delegate=mw.delegate,
        inspector_panel=mw.inspector_panel, config=mw.config,
        empty_state_overlay=mw._empty_state_overlay, nav=mw.nav,
        parent=mw,
    )
    gallery_ctrl.status_text_changed.connect(status.setText)
    gallery_ctrl.status_highlight_changed.connect(on_status_highlight)
    gallery_ctrl.search_input_cleared.connect(lambda: search_input.setText(""))
    # 延遲注入
    gallery_ctrl.engine = engine
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Optional

from PyQt6.QtCore import QObject, QSize, QTimer, pyqtSignal

if TYPE_CHECKING:
    pass  # 避免循環 import


class GalleryViewController(QObject):
    """畫廊視圖的獨立控制器。

    集中管理畫廊的所有顯示邏輯：過濾、排序、視圖模式、佈局。
    狀態完全內聚於本類別，MainWindow 透過 `self.gallery_ctrl.X` 存取。
    """

    # ── 對外訊號 ──────────────────────────────────────────────────────
    #: 重排版完成（adjust_layout 結束時發射，供外部觀察者使用）
    layout_changed = pyqtSignal()

    #: 狀態列文字更新（過濾結果統計、搜尋成功訊息等）
    status_text_changed = pyqtSignal(str)

    #: 狀態列高亮等級：'alert' 或 'none'
    status_highlight_changed = pyqtSignal(str)

    #: 通知搜尋輸入框應被清空（search_by_time_range 成功後）
    search_input_cleared = pyqtSignal()

    def __init__(
        self,
        *,
        list_view,
        model,
        delegate,
        inspector_panel,
        config,
        empty_state_overlay,
        nav,
        initial_view_mode: str = "large",
        initial_card_size: Optional[QSize] = None,
        initial_thumb_size: Optional[QSize] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        """建立 GalleryViewController 實例。

        Args:
            list_view: QListView 實例（畫廊主視圖）。
            model: SearchResultsModel 實例（Qt Model 層）。
            delegate: ImageDelegate 實例（自繪卡片）。
            inspector_panel: InspectorPanel 實例（右側篩選控制台）。
            config: ConfigManager 實例（讀取使用者設定）。
            empty_state_overlay: EmptyStateOverlay 實例（空狀態提示）。
            nav: NavigationManager 實例（用於回放滾輪位置）。
            initial_view_mode: 起始視圖模式 (xl / large / medium)。
            initial_card_size: 起始卡片尺寸 QSize；None 時採 large 預設。
            initial_thumb_size: 起始縮圖尺寸 QSize；None 時採 large 預設。
            parent: Qt 物件樹的父節點。**不會**被當作 MainWindow 使用。
        """
        super().__init__(parent)

        # ── 注入的 UI 元件與設定 ──
        self.list_view = list_view
        self.model = model
        self.delegate = delegate
        self.inspector_panel = inspector_panel
        self.config = config
        self.empty_state_overlay = empty_state_overlay
        self.nav = nav

        # ── 延遲注入 ──
        #: ImageSearchEngine 實例，由 MainWindow 在 load_engine() 完成後設定
        self.engine = None

        # ── 搜尋結果與過濾狀態 ──
        self.last_search_results: list = []
        self.last_search_stats: dict = {}
        self.active_time_range: Optional[tuple] = None
        self.is_in_search_mode: bool = False

        # ── 導航滾輪還原旗標 ──
        self._nav_restoring_scroll: bool = False

        # ── 視圖模式狀態 ──
        self.current_view_mode: str = initial_view_mode
        self.current_card_size: QSize = initial_card_size or QSize(240, 290)
        self.current_thumb_size: QSize = initial_thumb_size or QSize(240, 180)

        # ── adjust_layout 結果快取（相同計算跳過 setter） ──
        self._last_layout: tuple = ()

    # ==================================================================
    #  排序
    # ==================================================================
    def apply_gallery_sort(self) -> None:
        """對目前 Gallery 圖片進行洗牌排序。

        排序金鑰永遠以 is_pinned 為第一優先鍵（釘選圖置頂），
        第二鍵依使用者下拉選單決定（搜尋相關度 / 日期 / 名稱 / 類型 / 大小）。
        """
        # 如果目前畫面上沒圖片，就不需要排
        if not self.model.all_items:
            return

        # 1. 取得使用者的設定狀態
        sort_by = self.inspector_panel.combo_sort.currentText()
        is_descending = (self.inspector_panel.btn_sort_order.text() == "↓")

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
                except Exception:
                    return item.is_pinned, 0
            key_func = get_size
        else:
            key_func = lambda item: (item.is_pinned, item.mtime)

        # 3. 呼叫 Model 的排序方法
        self.model.sort_items(key_func, reverse=is_descending)

        # 4. 防禦：滾輪還原期間不回頂；其他情況才自動滾回最上方
        if not self._nav_restoring_scroll and self.nav.pending_scroll_pos is None:
            self.list_view.scrollToTop()

    # ==================================================================
    #  核心過濾器與資料派發機制
    # ==================================================================
    def set_base_results(self, results: list) -> None:
        """所有搜尋或載入資料的統一入口。

        保存最原始的結果，並自動套用目前的過濾器與漏斗診斷。
        """
        self.last_search_results = results
        self.apply_current_filters_and_show()
        self._update_search_diagnostics()

    def apply_current_filters_and_show(self, test_mode: bool = False) -> int:
        """套用時間／長寬比／Limit 過濾器到 last_search_results 並丟給 Model。

        Args:
            test_mode: True 時僅返回過濾後筆數，不更新 UI 也不更新漏斗統計；
                      用於套用前的防呆預覽。

        Returns:
            過濾後的最終筆數。
        """
        filtered = self.last_search_results
        raw_count = len(filtered)

        # 1. 時間區間過濾
        if self.active_time_range:
            start_ts, end_ts = self.active_time_range
            filtered = [item for item in filtered if start_ts <= item["mtime"] <= end_ts]
        after_date = len(filtered)

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
        after_aspect = len(filtered)

        # 3. UI 顯示數量限制 (Limit Truncation)
        # 實作「超額抓取 + 精準裁切」的最關鍵一步
        limit_text = self.inspector_panel.combo_limit_panel.currentText()
        if limit_text != "All":
            limit_val = int(limit_text)
            filtered = filtered[:limit_val]
        final_count = len(filtered)

        # 更新漏斗統計 (僅在正式顯示模式下更新，測試模式不污染統計)
        if not test_mode:
            self.last_search_stats = {
                "raw_count": raw_count,
                "after_date": after_date,
                "after_aspect": after_aspect,
                "final_count": final_count,
            }

        if test_mode:
            return final_count

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

        return final_count

    # ==================================================================
    #  時間過濾器
    # ==================================================================
    def apply_time_filter_to_gallery(self, start_ts: float, end_ts: float) -> None:
        """點擊 [套用結果]：測試過濾數量，若為 0 顯示防呆警告，否則套用。"""
        # 先暫存原本的時間區間 (為了防呆退回)
        old_range = self.active_time_range
        self.active_time_range = (start_ts, end_ts)

        # 進入 Test Mode 測試這刀切下去剩幾張圖
        count = self.apply_current_filters_and_show(test_mode=True)

        if count > 0:
            # 成功！正式更新畫面
            self.apply_current_filters_and_show(test_mode=False)
            self.inspector_panel.calendar_widget.set_status(
                f"✅ 已成功過濾，顯示 {count} 張圖片。", "success"
            )
            self.status_text_changed.emit(f"Filtered: {count} images")
        else:
            # 防呆啟動：找不到圖，退回上一個狀態並報錯，不收合日曆
            self.active_time_range = old_range
            self.inspector_panel.calendar_widget.set_status(
                f"⚠️ 您的搜尋結果中，此時間段內沒有圖片。", "error"
            )

    def clear_time_filter(self) -> None:
        """點擊 [清除]：移除過濾器並還原畫廊。"""
        self.active_time_range = None
        self.apply_current_filters_and_show()
        self._update_search_diagnostics()
        self.status_text_changed.emit(
            f"Time filter cleared. Showing {len(self.model.all_items)} images"
        )

    def search_by_time_range(self, start_ts: float, end_ts: float) -> None:
        """點擊 [直接搜尋]：忽略關鍵字，直接全域抓出該時段的圖。

        包含防呆檢查：若資料庫此時段無圖片，自動退回上一個狀態。
        """
        if not self.engine:
            return

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
            self.is_in_search_mode = True  # 進入搜尋結果模式，啟用漏斗卡片
            self.search_input_cleared.emit()  # 通知主視窗清空關鍵字輸入框
            self.apply_current_filters_and_show(test_mode=False)

            # 強制切換右側排序選單為「日期」，倒序 (↓) (阻擋訊號以避免重複洗牌)
            self.inspector_panel.combo_sort.blockSignals(True)
            self.inspector_panel.combo_sort.setCurrentText("日期")
            self.inspector_panel.btn_sort_order.setText("↓")
            self.inspector_panel.combo_sort.blockSignals(False)
            self.apply_gallery_sort()  # 正式套用排序

            self.inspector_panel.calendar_widget.set_status(
                f"✅ 搜尋完成，已列出 {count} 張圖片。", "success"
            )
            self.status_text_changed.emit(f"Direct Time Search: {count} items")
        else:
            # 防呆啟動：資料庫中找不到圖，退回上一個狀態並報錯，不變動畫廊
            self.last_search_results = old_results
            self.active_time_range = old_range
            self.inspector_panel.calendar_widget.set_status(
                f"⚠️ 資料庫中，此時間段內沒有符合的圖片。", "error"
            )

    # ==================================================================
    #  空狀態診斷
    # ==================================================================
    def _update_search_diagnostics(self) -> None:
        """根據 last_search_stats 決定是否顯示空狀態覆蓋層與狀態列高亮。

        僅在「搜尋模式」且「最終結果為 0」時觸發；
        會依據漏斗各層消耗的圖片數量，給出針對性的引導訊息。
        """
        stats = self.last_search_stats
        final_count = stats.get('final_count', -1)

        # 僅在搜尋模式且結果為 0 時啟動診斷
        if not self.is_in_search_mode or final_count != 0:
            self.empty_state_overlay.hide()
            self.update_status_highlight('none')
            return

        raw = stats.get('raw_count', 0)
        after_date = stats.get('after_date', 0)
        after_aspect = stats.get('after_aspect', 0)

        if raw == 0:
            icon = '🔍'
            msg = "找不到符合關鍵字的圖片。\n請嘗試不同的關鍵字，或切換到「全域」搜尋。"
        elif after_date == 0:
            icon = '📅'
            msg = "我們找到了相似圖片，但它們都不在您選擇的『日期區間』內。\n建議在右側面板放寬日期範圍！"
        elif after_aspect == 0:
            icon = '📐'
            msg = "有符合日期的相似圖，但因為您限制了『比例』所以被隱藏了。\n建議在右側面板改為「不限比例」！"
        else:
            icon = '🔢'
            msg = "顯示數量限制將所有結果截斷。\n請在右側面板提高 Limit 數量！"

        self.empty_state_overlay.show_message(icon, msg)
        # 若是過濾器造成的空結果，高亮狀態列吸引使用者注意右側面板
        self.update_status_highlight('alert' if raw > 0 else 'none')

    def update_status_highlight(self, alert_level: str) -> None:
        """發射狀態列邊框高亮訊號。

        Args:
            alert_level: 'alert' 顯示橘色邊框，'none' 還原無邊框。
        """
        self.status_highlight_changed.emit(alert_level)

    # ==================================================================
    #  視圖模式與佈局
    # ==================================================================
    def change_view_mode(self, mode: str) -> None:
        """切換視圖模式 (xl / large / medium)，同步更新卡片尺寸與佈局。

        Args:
            mode: 'xl' / 'large' / 'medium' 之一；其他值視為 no-op。
        """
        if mode == self.current_view_mode:
            return
        self.current_view_mode = mode

        if mode == "xl":
            new_card_size = QSize(320, 380)
            thumb_h = 240
        elif mode == "large":
            new_card_size = QSize(240, 290)
            thumb_h = 160
        elif mode == "medium":
            new_card_size = QSize(180, 230)
            thumb_h = 120
        else:
            return

        self.current_card_size = new_card_size
        self.current_thumb_size = QSize(new_card_size.width(), thumb_h)

        self.delegate.set_view_params(new_card_size, thumb_h)
        self.model.update_target_size(self.current_thumb_size)
        self._last_layout = ()  # 視圖模式變更，強制 adjust_layout 重算
        self.adjust_layout()

    def adjust_layout(self) -> None:
        """全動態均分佈局：四周邊距與卡片間距完全相等。

        演算法（test.py 邏輯）：
          1. 取 ListView 寬度 - 26px 滾動條預留
          2. 計算列數 = 可用寬度 // 卡片寬
          3. 剩餘空間 / (列數 + 1) = 等分間距
          4. setSpacing / setContentsMargins / setGridSize 一次設好
        """
        # 防呆：viewport 尚未初始化
        if self.list_view.width() <= 0:
            return

        # 1. 取得 ListView 當前寬度（已扣除 Sidebar）
        raw_width = self.list_view.width()

        # 2. 扣除滾動條預留空間（test.py 標準值）
        view_w = raw_width - 26

        # 取得目前卡片寬度
        item_w = self.current_card_size.width()

        # 3. 計算列數 (Columns)
        n_cols = view_w // item_w
        if n_cols < 1:
            n_cols = 1

        # 4. 計算剩餘空間
        total_card_w = n_cols * item_w
        remaining_space = view_w - total_card_w

        # 5. 計算間距：均分給 (左邊界 + 所有圖片間隙 + 右邊界)
        # 總縫隙數 = n_cols + 1
        space = int(remaining_space // (n_cols + 1))
        space = max(0, space)  # 安全限制：不小於 0

        # 6. 計算最終格子尺寸
        grid_w = self.current_card_size.width() + space
        grid_h = self.current_card_size.height() + space

        # 相同結果跳過所有 setter，避免無效 relayout
        cache_key = (space, grid_w, grid_h)
        if cache_key == self._last_layout:
            return
        self._last_layout = cache_key

        self.list_view.setSpacing(space)
        self.list_view.setContentsMargins(space, space, space, space)
        self.list_view.setGridSize(QSize(grid_w, grid_h))

        self.layout_changed.emit()

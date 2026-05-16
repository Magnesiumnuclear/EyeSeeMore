"""
IndexingLifecycleHandler  –  索引掃描的生命週期管理器
========================================================
從 MainWindow 抽離的職責：
  • IndexerWorker 完成事件處理（scan_finished / all_finished）
  • 掃描暫停 / 繼續 / 取消 的狀態切換
  • 索引完成後觸發背景資料庫雙緩衝重載
  • 重載完畢通知 UI 刷新畫廊與側邊欄

設計原則：
  • 繼承 QObject 以使用 pyqtSignal 機制
  • UI 元件操作（status / progress / taskbar / 系統選單）一律透過訊號
    對外發射，由 MainWindow 訂閱後刷新元件；handler 本身不持有任何
    QWidget 參照
  • engine 與 indexer_worker 採延遲注入（與 SearchOrchestrator 同模式），
    因為它們在 MainWindow.__init__ 時尚未建立
  • eta_ctrl 為必要依賴，於建構時注入

使用方式：
    handler = IndexingLifecycleHandler(eta_ctrl=eta_ctrl, parent=mw)
    # 訊號連接（UI 元件已存在後）
    handler.scan_status_changed.connect(status.setText)
    handler.gallery_refresh_requested.connect(refresh_gallery)
    handler.sidebar_refresh_requested.connect(refresh_sidebar)
    handler.taskbar_state_changed.connect(taskbar.set_state)
    handler.pause_menu_state_changed.connect(set_menu_checked)
    handler.progress_completed.connect(complete_progress_bar)
    # 延遲注入
    handler.engine = engine
    handler.indexer_worker = indexer_worker
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, pyqtSignal

if TYPE_CHECKING:
    from core.eta_progress_controller import EtaProgressController


class IndexingLifecycleHandler(QObject):
    """索引掃描生命週期的獨立控制器。

    將原本散落在 MainWindow 內的 6 個索引相關方法集中管理，並透過
    訊號發射機制將 UI 更新需求轉交給訂閱者，徹底解耦 UI 元件操作。
    """

    # ── 對外訊號 ──────────────────────────────────────────────────────
    #: 通知狀態列文字更新（例如 "Synchronizing..."、"索引完成"）
    scan_status_changed = pyqtSignal(str)

    #: 通知畫廊刷新顯示（不攜帶資料，由訂閱者依當前狀態決定如何刷新）
    #: 設計選擇：不採用 pyqtSignal(list) 是因為 handler 不知道 UI 端
    #: 目前所在的資料夾 / 篩選條件，無法決定要顯示哪些圖片；交給
    #: MainWindow 的 slot 自行調用 _apply_folder_filter(current_folder_path)
    gallery_refresh_requested = pyqtSignal()

    #: 通知側邊欄重新整理資料夾統計
    sidebar_refresh_requested = pyqtSignal()

    #: 通知 Windows 工作列進度條狀態變更（TBPF_* 常數）
    taskbar_state_changed = pyqtSignal(int)

    #: 通知 Win32 系統選單「Pause Scan」項目的勾選狀態變更
    pause_menu_state_changed = pyqtSignal(bool)

    #: 通知主進度條進入「完成收尾」狀態（停止動畫 → 拉到滿格 → 隱藏）
    progress_completed = pyqtSignal()

    # ── 內部訊號（跨執行緒橋接：背景 thread → 主執行緒）────────────────
    #: trigger_background_db_reload 的背景執行緒完成後發射，
    #: 內部連到 on_db_reloaded（自動跨執行緒切換到主執行緒）
    _db_reloaded = pyqtSignal()

    def __init__(
        self,
        eta_ctrl: "EtaProgressController",
        parent: Optional[QObject] = None,
    ) -> None:
        """建立 IndexingLifecycleHandler 實例。

        Args:
            eta_ctrl: EtaProgressController 實例，必要依賴
                     （on_indexing_finished 與 pause/cancel 邏輯都需要）。
            parent: Qt 物件樹的父節點。**不會**被當作 MainWindow 使用——
                   handler 完全不依賴 UI 元件。
        """
        super().__init__(parent)
        self.eta_ctrl: "EtaProgressController" = eta_ctrl
        #: ImageSearchEngine 實例。延遲注入（MainWindow.__init__ 時尚未建立），
        #: 由 MainWindow 在 load_engine() 完成後賦值
        self.engine = None
        #: IndexerWorker 實例。延遲注入，由 MainWindow 在 init_ui 之後賦值
        self.indexer_worker = None

        # 內部訊號自連：背景執行緒只負責 emit，主執行緒接收後處理 UI 刷新
        self._db_reloaded.connect(self.on_db_reloaded)

    # ------------------------------------------------------------------
    #  Worker 完成事件
    # ------------------------------------------------------------------
    def on_scan_finished(self, added: int, deleted: int) -> None:
        """IndexerWorker.scan_finished 訊號的接收端。

        僅做日誌輸出；資料庫實際載入延後到 on_indexing_finished 統一處理，
        避免在開始索引前同步呼叫 load_data_from_db 造成 UI 卡死。
        """
        if added > 0 or deleted > 0:
            print(f"[Indexer] Scan found {added} new, {deleted} deleted.")
        else:
            print("[Indexer] No changes detected.")

    def on_indexing_finished(self) -> None:
        """IndexerWorker.all_finished 訊號的接收端。

        執行順序：
          1. 取出 ETA mode 1 的總耗時（必須在 reset 前完成）
          2. 發送對應的完成狀態文字
          3. 重置 EtaProgressController 所有內部狀態
          4. 通知進度條收尾（progress_completed）
          5. 關閉工作列進度條
          6. 觸發背景資料庫雙緩衝重載
        """
        # 在 reset 前先取得 mode 1 所需的總耗時
        if self.eta_ctrl.mode == 1:
            total_sec = int(self.eta_ctrl.total_elapsed())
            _m, _s = divmod(total_sec, 60)
            self.scan_status_changed.emit(f"索引完成!總耗時:{_m:02d} 分 {_s:02d} 秒")
        else:
            self.scan_status_changed.emit("Index Updated.")

        # 一次性重置所有 ETA 狀態（timer 停止、T_fake/T_total/累計全部清空）
        self.eta_ctrl.reset()

        # 進度條收尾（停止動畫、滿格、隱藏） + 工作列關閉
        self.progress_completed.emit()
        # TBPF_NOPROGRESS = 0
        self.taskbar_state_changed.emit(0)

        # 觸發雙緩衝背景載入
        self.trigger_background_db_reload()

    # ------------------------------------------------------------------
    #  掃描控制 API（由 WinScanCtrlFilter / Jump List / 系統選單驅動）
    # ------------------------------------------------------------------
    def toggle_scan_pause(self) -> None:
        """切換 IndexerWorker 暫停 / 繼續狀態。

        - 暫停：工作列轉黃色；系統選單顯示勾選符號。
        - 繼續：工作列恢復綠色；系統選單移除勾選符號。

        若 Worker 不存在或未執行則不做事（安全靜默）。
        """
        if not (self.indexer_worker and self.indexer_worker.isRunning()):
            return

        if self.indexer_worker._paused:
            # ── 繼續 ──
            self.indexer_worker._paused = False
            self.indexer_worker._resume_event.set()
            # TBPF_NORMAL = 0x2
            self.taskbar_state_changed.emit(0x2)
            self.eta_ctrl.set_paused_flag(False)
            self.pause_menu_state_changed.emit(False)
            print("[ScanCtrl] 掃描已繼續。")
        else:
            # ── 暫停 ──
            self.indexer_worker._paused = True
            self.indexer_worker._resume_event.clear()
            # TBPF_PAUSED = 0x8
            self.taskbar_state_changed.emit(0x8)
            self.eta_ctrl.set_paused_flag(True)
            self.pause_menu_state_changed.emit(True)
            print("[ScanCtrl] 掃描已暫停。")

    def cancel_indexing(self) -> None:
        """強制中止 IndexerWorker 並清空目前任務。

        若 Worker 處於暫停狀態，先解除暫停以確保執行緒能正常結束。
        """
        if not (self.indexer_worker and self.indexer_worker.isRunning()):
            return

        # 若暫停中，先解除暫停讓 Worker 執行緒能往前跑到 cancel 檢查點
        if self.indexer_worker._paused:
            self.indexer_worker._paused = False
            self.indexer_worker._resume_event.set()

        self.indexer_worker._cancelled = True
        # TBPF_NOPROGRESS = 0
        self.taskbar_state_changed.emit(0)
        self.eta_ctrl.set_paused_flag(False)
        self.pause_menu_state_changed.emit(False)
        print("[ScanCtrl] 取消掃描指令已發出，等待 Worker 結束目前批次…")

    # ------------------------------------------------------------------
    #  雙緩衝資料庫重載
    # ------------------------------------------------------------------
    def trigger_background_db_reload(self) -> None:
        """[方案 B：雙緩衝核心] 在背景執行緒讀取資料庫，UI 與搜尋不中斷。

        若 engine 尚未注入則靜默返回。背景執行緒結束時透過內部訊號
        _db_reloaded 跨執行緒切回主執行緒處理 UI 更新。
        """
        if not self.engine:
            return
        self.scan_status_changed.emit("Synchronizing database in background...")

        def bg_reload():
            print("[Engine] Reloading engine data in background (Double Buffering)...")
            self.engine.load_data_from_db()  # 此處內部已實作 Atomic Swap

            # [關鍵] 發送空訊號讓主執行緒接手，徹底杜絕跨執行緒崩潰
            self._db_reloaded.emit()

        threading.Thread(target=bg_reload, daemon=True).start()

    def on_db_reloaded(self) -> None:
        """背景重載完畢，發射 UI 刷新訊號（已在主執行緒）。

        透過 gallery_refresh_requested / sidebar_refresh_requested 通知
        訂閱者刷新，handler 本身不需要知道目前所在的資料夾或側邊欄結構。
        """
        if not self.engine:
            return
        self.gallery_refresh_requested.emit()
        self.sidebar_refresh_requested.emit()

"""
EtaProgressController  –  索引進度 ETA 計時器
================================================
從 MainWindow 抽離的職責：
  • 累計運行時間（pause / resume 邏輯）
  • PID 假時間平滑器（mode 2，避免進度條跳動）
  • 100ms 內部 QTimer 驅動，將更新後的狀態文字與進度值
    透過 Signal 發送給 UI 層

設計原則：
  • 僅依賴 PyQt6.QtCore (QObject, QTimer, pyqtSignal)，零 UI 元件依賴
  • 不持有 MainWindow 參照；所有 UI 更新透過 status_text_changed /
    progress_updated 訊號發射，由訂閱者自行決定如何更新介面
  • 所有 ETA 內部狀態都封裝在此類別內，外部僅能透過公開方法操作

使用方式：
    eta_ctrl = EtaProgressController(mode=1, parent=main_window)
    eta_ctrl.status_text_changed.connect(status_bar.setText)
    eta_ctrl.progress_updated.connect(lambda v, m: progress_bar.setValue(v))

    # IndexerWorker 開始任務
    eta_ctrl.start_session()
    indexer.eta_updated.connect(eta_ctrl.on_real_eta)

    # 任務結束
    eta_ctrl.reset()

四種顯示模式：
  • mode 1 = 真實跳動時間（worker 直接決定顯示文字）
  • mode 2 = PID 假時間（本 controller 的主要工作模式）
  • mode 3 = 純張數計數（不啟動 PID timer）
  • mode 4 = 開發測試模式（不啟動 PID timer）
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class EtaProgressController(QObject):
    """索引進度 ETA 的獨立控制器。

    封裝原本 MainWindow 內 12+ 個 `_eta_*` 屬性與 QTimer，
    並將 UI 更新解耦為 pyqtSignal 對外發射。
    """

    # ── 對外訊號 ──────────────────────────────────────────────────────
    #: 通知狀態列文字更新（內含階段訊息 + ETA 剩餘時間 suffix）
    status_text_changed = pyqtSignal(str)

    #: 通知進度條更新 (current, total)。
    #: 在 PID mode 2，total 永遠等於 PROGRESS_SCALE (1000)
    progress_updated = pyqtSignal(int, int)

    # ── PID / 計時器常數 ──────────────────────────────────────────────
    #: PID 比例增益（Proportional Gain）
    PID_KP: float = 0.30
    #: PID 積分增益（Integral Gain）
    PID_KI: float = 0.01
    #: PID 微分增益（Derivative Gain）
    PID_KD: float = 0.05
    #: 進度條在 mode 2 採用的解析度（0~1000）
    PROGRESS_SCALE: int = 1000
    #: QTimer tick 間隔（毫秒），對應內部 DT = 0.1 秒
    TICK_INTERVAL_MS: int = 100
    #: 內部時間步長（秒），對應 TICK_INTERVAL_MS
    _DT: float = 0.1

    def __init__(self, mode: int = 1, parent: Optional[QObject] = None) -> None:
        """建立 EtaProgressController 實例。

        Args:
            mode: 初始 ETA 顯示模式 (1~4)。可在執行時透過 apply_mode 切換。
            parent: Qt 物件樹的父節點，標準 QObject parent。**不會**被當作
                   MainWindow 來使用——本類別完全不依賴 UI 元件。
        """
        super().__init__(parent)

        # ── 模式（mode 1~4）──
        self._mode: int = mode

        # ── 共用狀態（所有模式共用）──
        self._t_real: float = 0.0
        self._stage_msg: str = ""

        # ── mode 1：累計運行時間（pause / resume 用）──
        self._run_start: float = 0.0      # 最近一次 resume 的 wall-clock
        self._accumulated: float = 0.0    # 暫停期間累計秒數
        self._paused: bool = False

        # ── mode 2：PID 假計時器狀態 ──
        self._t_fake: Optional[float] = None
        self._t_total: Optional[float] = None   # 鎖定首次估計的總耗時
        self._pid_integral: float = 0.0
        self._pid_last_error: float = 0.0

        # ── QTimer 驅動 _on_tick（mode 2 用）──
        self._timer: QTimer = QTimer(self)
        self._timer.setInterval(self.TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------
    #  模式管理
    # ------------------------------------------------------------------
    @property
    def mode(self) -> int:
        """目前 ETA 顯示模式（1=真實、2=PID 假時間、3=張數、4=測試）。"""
        return self._mode

    def apply_mode(self, mode: int) -> None:
        """設定頁即時切換模式；模式切離 2 時自動停止 PID timer。

        Args:
            mode: 新的顯示模式 (1~4)。
        """
        old = self._mode
        self._mode = mode
        if old == 2 and mode != 2:
            self._timer.stop()

    # ------------------------------------------------------------------
    #  階段訊息（由 MainWindow.update_status 呼叫）
    # ------------------------------------------------------------------
    def set_stage_message(self, text: str) -> bool:
        """設定目前階段訊息（例如 "Indexing 1234 images..."）。

        Args:
            text: 階段訊息字串。

        Returns:
            True  → 呼叫端應自行更新狀態列 UI（一般情況）。
            False → 模式 2 PID timer 執行中，狀態列由 tick 控制，
                    呼叫端不應額外寫入以免閃爍。
        """
        self._stage_msg = text
        return not (self._mode == 2 and self._timer.isActive())

    # ------------------------------------------------------------------
    #  Session 生命週期
    # ------------------------------------------------------------------
    def start_session(self) -> None:
        """開始新的計時 session（由 IndexerWorker 在 run() 啟動時呼叫）。

        重置累計與暫停旗標，記錄 wall-clock 起始時刻。
        """
        self._accumulated = 0.0
        self._paused = False
        self._run_start = time.time()

    def reset(self) -> None:
        """完整重置所有 ETA 內部狀態（任務完成或取消時呼叫）。

        停止 PID timer，清空 t_fake / t_total / t_real 與 PID 積分項，
        並將累計時間與暫停旗標歸零。
        """
        self._timer.stop()
        self._t_fake = None
        self._t_total = None
        self._t_real = 0.0
        self._pid_integral = 0.0
        self._pid_last_error = 0.0
        self._accumulated = 0.0
        self._paused = False

    # ------------------------------------------------------------------
    #  完整 pause / resume（會累積暫停期間的時間）
    # ------------------------------------------------------------------
    def pause_timer(self) -> None:
        """暫停 ETA 計時並累計目前 run 的時間至 _accumulated。

        對應原 MainWindow.pause_eta_timer，預留給未來完整的
        Pause/Resume 功能使用。會 stop QTimer。
        """
        if not self._paused:
            self._accumulated += time.time() - self._run_start
            self._paused = True
            self._timer.stop()

    def resume_timer(self) -> None:
        """繼續 ETA 計時並重設 _run_start。

        對應原 MainWindow.resume_eta_timer。若在模式 2 且 t_fake
        尚未結算，會自動重啟 QTimer。
        """
        if self._paused:
            self._run_start = time.time()
            self._paused = False
            if self._mode == 2 and self._t_fake is not None:
                self._timer.start()

    # ------------------------------------------------------------------
    #  裸暫停旗標（toggle_scan_pause / cancel 用）
    # ------------------------------------------------------------------
    def set_paused_flag(self, paused: bool) -> None:
        """直接設定 _paused 旗標，不累計時間也不啟停 timer。

        對應原 MainWindow 在 toggle_scan_pause 與 cancel_indexing 內
        對 self._eta_paused 的裸寫入操作。語意上是「半成品 pause/resume
        功能」的最小占位實作。

        Args:
            paused: 新的暫停狀態（True=暫停旗標升起）。
        """
        self._paused = paused

    # ------------------------------------------------------------------
    #  時間查詢
    # ------------------------------------------------------------------
    def total_elapsed(self) -> float:
        """回傳累計運行秒數（暫停期間不包含）。"""
        if self._paused:
            return self._accumulated
        return self._accumulated + (time.time() - self._run_start)

    # ------------------------------------------------------------------
    #  Worker → Controller 入口
    # ------------------------------------------------------------------
    def on_real_eta(self, t_real: float) -> None:
        """接收 IndexerWorker.eta_updated 訊號發來的真實剩餘時間。

        Args:
            t_real: Worker 透過滑動視窗測速估算的真實剩餘秒數。
                   若為負值表示樣本不足（暖機中），會被忽略。
        """
        if t_real < 0:
            return  # 暖機中，樣本不足
        self._t_real = t_real
        # 模式 2：第一次收到有效 t_real 時初始化 PID 假計時器
        if self._mode == 2 and self._t_fake is None and t_real > 0:
            self._t_fake = t_real
            self._t_total = t_real   # 鎖定基準總耗時，後續不覆蓋
            self._pid_integral = 0.0
            self._pid_last_error = 0.0
            if not self._timer.isActive():
                self._timer.start()

    # ------------------------------------------------------------------
    #  內部 PID Tick（每 100ms 由 QTimer 觸發）
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        """PID 控制器迭代：以假時間平滑趨近真實時間，並發射 UI 更新訊號。

        若 t_fake 尚未初始化（模式 2 還沒收到第一筆 t_real）會直接返回。
        """
        if self._t_fake is None:
            return

        # ── PID 計算 ──
        # error 正 → 假時間超前需減速；負 → 落後需加速
        error = self._t_real - self._t_fake
        p_term = self.PID_KP * error
        self._pid_integral += error * self._DT
        self._pid_integral = max(-20.0, min(20.0, self._pid_integral))
        i_term = self.PID_KI * self._pid_integral
        d_term = self.PID_KD * (error - self._pid_last_error) / self._DT
        self._pid_last_error = error

        pid_output = p_term + i_term + d_term
        speed_factor = max(0.2, min(3.0, 1.0 - pid_output))  # 正 error → 減速
        self._t_fake = max(0.0, self._t_fake - self._DT * speed_factor)

        # ── Endgame 狀態機 ──
        if self._t_fake <= 1.0 and self._t_real > 10.0:
            self._t_fake = 1.0
            eta_suffix = "(即將完成...)"
        elif self._t_fake <= 5.0 and self._t_real > 30.0:
            self._t_fake = 5.0
            eta_suffix = "(最後步驟...)"
        else:
            _ms_total = int(self._t_fake * 1000)
            _ms = _ms_total % 1000
            _sec = (_ms_total // 1000) % 60
            _min = (_ms_total // 60000) % 60
            _hr = _ms_total // 3600000
            eta_suffix = f"(剩餘時間: {_hr:02d}:{_min:02d}:{_sec:02d}:{_ms:03d})"

        # ── 發射 UI 更新訊號（不直接操作 status / progress 元件）──
        self.status_text_changed.emit(f"{self._stage_msg} {eta_suffix}")

        # 用 PID 假時間反算假進度 %，推進進度條
        if self._t_total and self._t_total > 0:
            p = 1.0 - (self._t_fake / self._t_total)
            p = max(0.0, min(0.98, p))  # 上限 98%，真實完成事件才推到 100
            self.progress_updated.emit(int(p * self.PROGRESS_SCALE), self.PROGRESS_SCALE)

"""
Clock Slewing ETA 示範
======================
示範雙軌時間變數 (T_real / T_fake) + 時鐘偏移 + 收尾狀態機。

架構：
  WorkerThread  ──[t_real_updated signal]──►  MainWindow
                                                  │
                                             QTimer(100ms)
                                                  │
                                          slewing + endgame
                                                  │
                                              UI 顯示
"""

import sys
import time
import random

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QProgressBar,
)


# ─────────────────────────────────────────────────────────────────────────────
# Worker Thread
# 模擬真實索引作業：有時快、有時慢、偶爾暴增（模型切換/密集 OCR 等情境）
# ─────────────────────────────────────────────────────────────────────────────
class WorkerThread(QThread):
    t_real_updated = pyqtSignal(float)   # 最新估計剩餘秒數
    progress_updated = pyqtSignal(int, int)  # current, total

    def run(self):
        total = 50
        current = 0
        speed_history: list[float] = []

        while current < total and not self.isInterruptionRequested():
            rand = random.random()

            # ── 刻意設計三種速度情境 ──────────────────────────────
            if rand < 0.01:
                # ★ 暴增：模擬遇到超大圖 / OCR 密集頁面
                item_time = random.uniform(6.0, 14.0)
            elif rand < 0.25:
                # 較慢：Full AI pipeline
                item_time = random.uniform(1.5, 3.5)
            else:
                # 正常
                item_time = random.uniform(0.3, 1.2)

            time.sleep(item_time)
            current += 1

            # 滑動視窗 (最近 5 筆)
            speed_history.append(item_time)
            if len(speed_history) > 5:
                speed_history.pop(0)

            avg = sum(speed_history) / len(speed_history)
            t_real = (total - current) * avg
            self.t_real_updated.emit(max(0.0, t_real))
            self.progress_updated.emit(current, total)

        self.t_real_updated.emit(0.0)
        self.progress_updated.emit(total, total)


# ─────────────────────────────────────────────────────────────────────────────
# Main Window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clock Slewing ETA 示範")
        self.setMinimumSize(520, 340)

        self.T_real: float = 0.0
        self.T_fake: float | None = None   # None = 尚未初始化

        self.worker: WorkerThread | None = None

        self._build_ui()

        # ── 100ms 驅動假計時器 ──────────────────────────────────
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._on_tick)

    # ── UI 建構 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(14)
        layout.setContentsMargins(36, 28, 36, 28)

        title = QLabel("Clock Slewing ETA 示範")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: bold;")
        layout.addWidget(title)

        # 假的倒數顯示（HH:MM:SS:CC） + 箭頭
        fake_row = QHBoxLayout()
        fake_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fake_row.setSpacing(10)

        self.lbl_fake = QLabel("00:00:00:00")
        self.lbl_fake.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fake.setStyleSheet(
            "font-size: 48px; font-family: 'Courier New', monospace;"
            "color: #1565C0; letter-spacing: 2px;"
        )

        self.lbl_arrow = QLabel("")
        self.lbl_arrow.setFixedWidth(40)
        self.lbl_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_arrow.setStyleSheet("font-size: 36px;")

        fake_row.addWidget(self.lbl_fake)
        fake_row.addWidget(self.lbl_arrow)
        layout.addLayout(fake_row)

        # 真實剩餘時間（輔助資訊）
        self.lbl_real = QLabel("真實剩餘: --- 秒")
        self.lbl_real.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_real.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(self.lbl_real)

        # 狀態文字
        self.lbl_state = QLabel("等待開始...")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setStyleSheet("font-size: 15px; color: #333;")
        layout.addWidget(self.lbl_state)

        # 進度條
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        layout.addWidget(self.progress)

        # 按鈕
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("開始模擬")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._start)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)

        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

    # ── 流程控制 ──────────────────────────────────────────────────────────────
    def _start(self):
        self.T_real = 0.0
        self.T_fake = None
        self.lbl_fake.setText("00:00:00:00")
        self.lbl_arrow.setText("")
        self.lbl_state.setText("計算估時中...")
        self.lbl_real.setText("真實剩餘: --- 秒")
        self.progress.setValue(0)

        self.worker = WorkerThread()
        self.worker.t_real_updated.connect(self._on_t_real_updated)
        self.worker.progress_updated.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

        self.timer.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _stop(self):
        self.timer.stop()
        if self.worker:
            self.worker.requestInterruption()
        self.lbl_state.setText("已停止")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_t_real_updated(self, t_real: float):
        self.T_real = t_real
        self.lbl_real.setText(f"真實剩餘: {t_real:.2f} 秒")

        # 第一次收到有效 T_real 時，用它初始化 T_fake
        if self.T_fake is None and t_real > 0:
            self.T_fake = t_real
            print(f"[Debug] T_fake 初始化為 {t_real:.2f} 秒")

    def _on_progress(self, current: int, total: int):
        self.progress.setValue(int(current / total * 100) if total else 0)

    # ── 核心：每 100ms 觸發 ───────────────────────────────────────────────────
    def _on_tick(self):
        if self.T_fake is None:
            # 尚未收到第一筆 T_real，等待中
            return

        # ── 1. Clock Slewing ──────────────────────────────────────────────────
        delta = self.T_real - self.T_fake   # 正 = 假時間落後；負 = 假時間超前

        if delta > 0.5:
            speed_factor = 0.25   # 假時間超前 → 減速等待
            arrow, arrow_color = "▼", "#1976D2"   # 藍色下箭頭
        elif delta < -0.5:
            speed_factor = 2   # 假時間落後 → 加速追上
            arrow, arrow_color = "▲", "#D32F2F"   # 紅色上箭頭
        else:
            speed_factor = 1.0   # 同步
            arrow, arrow_color = "=" , "#555555"   # 灰色等號

        self.T_fake = max(0.0, self.T_fake - 0.1 * speed_factor)

        # ── 2. Endgame State Machine ──────────────────────────────────────────
        if self.T_fake <= 1.0 and self.T_real > 10.0:
            self.T_fake = 1.0
            state = "即將完成..."
        elif self.T_fake <= 5.0 and self.T_real > 30.0:
            self.T_fake = 5.0
            state = "最後步驟..."
        else:
            state = "處理中"

        # ── 3. 更新 UI ────────────────────────────────────────────────────────
        self.lbl_state.setText(state)
        self.lbl_fake.setText(self._format_time(self.T_fake))
        self.lbl_arrow.setText(arrow)
        self.lbl_arrow.setStyleSheet(f"font-size: 36px; color: {arrow_color};")

        # ── 4. 終端機 Debug 輸出 ──────────────────────────────────────────────
        print(f"[Debug] 假的時間 : {self.T_fake:.2f} ; 真實時間 : {self.T_real:.2f}    speed_factor : {speed_factor}")

    # ── 任務完成 ──────────────────────────────────────────────────────────────
    def _on_finished(self):
        self.timer.stop()
        self.T_fake = 0.0
        self.lbl_fake.setText("00:00:00:00")
        self.lbl_arrow.setText("")
        self.lbl_state.setText("完成！")
        self.lbl_real.setText("真實剩餘: 0.00 秒")
        self.progress.setValue(100)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        print("[Debug] ── 任務完成 ──")

    # ── 工具函式 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _format_time(seconds: float) -> str:
        """
        float 秒數 → HH:MM:SS:CC (CC = centiseconds, 1/100 秒)
        例：45.73 秒 → 00:00:45:73
        """
        cs_total = int(seconds * 100)          # 換算成百分之一秒
        cc = cs_total % 100                    # 百分之一秒位
        s_total = cs_total // 100
        h = s_total // 3600
        m = (s_total % 3600) // 60
        s = s_total % 60
        return f"{h:02d}:{m:02d}:{s:02d}:{cc:02d}"


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

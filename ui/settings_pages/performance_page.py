"""Performance settings page — tunable constants for scanning and display."""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QGroupBox, QSpinBox,
)
from PyQt6.QtCore import Qt


class PerformancePage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]
        perf = ctx["config"].get("performance", {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        title = QLabel(trans.t("performance", "page_title", "⚡ 效能調整 (Performance)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("PageHLine")
        layout.addWidget(sep)

        # ── 掃描效能 ──────────────────────────────────────────────────────
        grp_scan = QGroupBox("掃描效能　（下次掃描生效）")
        grp_scan_layout = QVBoxLayout(grp_scan)
        grp_scan_layout.setSpacing(10)
        grp_scan_layout.setContentsMargins(16, 12, 16, 16)

        self.spin_batch = self._row(
            grp_scan_layout,
            label="每批處理幾張圖片",
            hint="越大越快，但需要更多記憶體。GPU 用戶建議 8–16，CPU 用戶建議 2–4。",
            lo=1, hi=32, step=1,
            val=perf.get("indexing_batch_size", 4),
        )
        self.spin_commit = self._row(
            grp_scan_layout,
            label="每幾張才記錄一次進度",
            hint="越小越安全（中斷損失少），越大越快。建議範圍：16–64。",
            lo=4, hi=256, step=4,
            val=perf.get("db_commit_threshold", 24),
        )
        layout.addWidget(grp_scan)

        # ── 顯示效能 ──────────────────────────────────────────────────────
        grp_display = QGroupBox("顯示效能　（重新啟動後生效）")
        grp_display_layout = QVBoxLayout(grp_display)
        grp_display_layout.setSpacing(10)
        grp_display_layout.setContentsMargins(16, 12, 16, 16)

        self.spin_cache = self._row(
            grp_display_layout,
            label="記憶體縮圖快取張數",
            hint="越多捲動越順暢，但佔用更多記憶體。建議範圍：500–2000。",
            lo=100, hi=5000, step=100,
            val=perf.get("thumbnail_cache_size", 1000),
        )
        cpu_count = os.cpu_count() or 1
        saved_threads = self._safe_int(
            perf.get("thumbnail_thread_count", 8), 8, 1, cpu_count
        )
        self.spin_threads = self._row(
            grp_display_layout,
            label="同時載入縮圖的執行緒數",
            hint=f"越多載入越快，但佔用更多 CPU。此電腦最多 {cpu_count} 個執行緒。",
            lo=1, hi=cpu_count, step=1,
            val=saved_threads,
        )
        layout.addWidget(grp_display)
        layout.addStretch(1)

        # 任何 spinbox 改動就即時寫入 config
        for sp in (self.spin_batch, self.spin_commit, self.spin_cache, self.spin_threads):
            sp.valueChanged.connect(self._save)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _safe_int(val, default: int, lo: int, hi: int) -> int:
        """將 config 載入的值安全轉為合法整數，防止 null / 字串 / 浮點數崩潰。"""
        try:
            v = int(val)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, v))

    def _row(self, parent_layout, *, label, hint, lo, hi, step, val) -> QSpinBox:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        lbl = QLabel(label)
        row_layout.addWidget(lbl, stretch=1)

        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(self._safe_int(val, lo, lo, hi))
        spin.setFixedWidth(90)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        row_layout.addWidget(spin)

        parent_layout.addWidget(row)

        hint_lbl = QLabel(hint)
        hint_lbl.setObjectName("SettingsHint")
        hint_lbl.setWordWrap(True)
        parent_layout.addWidget(hint_lbl)

        return spin

    # ------------------------------------------------------------------ save
    def _save(self):
        self.ctx["config"].set("performance", {
            "indexing_batch_size":    self.spin_batch.value(),
            "db_commit_threshold":    self.spin_commit.value(),
            "thumbnail_cache_size":   self.spin_cache.value(),
            "thumbnail_thread_count": self.spin_threads.value(),
        })

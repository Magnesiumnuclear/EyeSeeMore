"""Hotkeys & advanced visual options settings page."""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QComboBox, QGroupBox, QCheckBox
)
from PyQt6.QtCore import Qt


class HotkeysPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]
        ui_state = ctx["config"].get("ui_state", {})

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("hotkeys", "page_title", "⌨️ 操作與快捷鍵 (Hotkeys)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        layout.addWidget(sep)

        # ── Navigation group ──────────────────────────────────────────────
        group_nav = QGroupBox(trans.t("hotkeys", "grp_nav_title", "預覽導覽行為"))
        layout_nav = QVBoxLayout(group_nav)
        layout_nav.setSpacing(10)
        lbl_nav = QLabel(trans.t("hotkeys", "lbl_nav", "空白鍵預覽時，按下 W/A/S/D 的反應："))
        lbl_nav.setObjectName("SettingsHint")
        layout_nav.addWidget(lbl_nav)

        self.combo_wasd = QComboBox()
        self.combo_wasd.setFixedHeight(38)
        self.combo_wasd.addItems([
            trans.t("hotkeys", "nav_opt_a", "選項 A：移動背景游標並保持預覽 (預設)"),
            trans.t("hotkeys", "nav_opt_b", "選項 B：關閉預覽圖 (快速偷瞄模式)"),
            trans.t("hotkeys", "nav_opt_c", "選項 C：切換預覽圖 (沉浸看圖模式)"),
        ])
        nav_map = {"nav": 0, "close": 1, "sync": 2}
        self.combo_wasd.setCurrentIndex(nav_map.get(ui_state.get("preview_wasd_mode", "nav"), 0))
        self.combo_wasd.currentIndexChanged.connect(self._on_wasd_mode_changed)
        layout_nav.addWidget(self.combo_wasd)
        layout.addWidget(group_nav)

        # ── OCR Shift-key group ───────────────────────────────────────────
        group_ocr = QGroupBox(trans.t("hotkeys", "grp_ocr_title", "OCR 檢視方式"))
        layout_ocr = QVBoxLayout(group_ocr)
        layout_ocr.setSpacing(10)
        lbl_ocr = QLabel(trans.t("hotkeys", "lbl_ocr", "預覽圖片時，Shift 鍵的觸發邏輯："))
        lbl_ocr.setObjectName("SettingsHint")
        layout_ocr.addWidget(lbl_ocr)

        self.combo_ocr = QComboBox()
        self.combo_ocr.setFixedHeight(38)
        self.combo_ocr.addItems([
            trans.t("hotkeys", "ocr_opt_hold",   "模式 A：長按 Shift 顯示紅框，放開隱藏 (Hold)"),
            trans.t("hotkeys", "ocr_opt_toggle", "模式 B：按一下 Shift 切換顯示 / 隱藏 (Toggle)"),
        ])
        ocr_mode = ui_state.get("ocr_shift_mode", "hold")
        self.combo_ocr.setCurrentIndex(1 if ocr_mode == "toggle" else 0)
        self.combo_ocr.currentIndexChanged.connect(self._on_ocr_mode_changed)
        layout_ocr.addWidget(self.combo_ocr)
        layout.addWidget(group_ocr)

        # ── Advanced visuals group ────────────────────────────────────────
        group_visual = QGroupBox(trans.t("hotkeys", "grp_visual_title", "進階視覺效果 (Advanced Visuals)"))
        layout_visual = QVBoxLayout(group_visual)
        layout_visual.setSpacing(12)

        self.chk_precise_ocr = QCheckBox(trans.t("hotkeys", "chk_precise", "啟用精確文字高亮 (僅著色關鍵字部分)"))
        self.chk_precise_ocr.setChecked(ui_state.get("precise_ocr_highlight", False))

        self.chk_margin_comp = QCheckBox(trans.t("hotkeys", "chk_margin", "↳ 啟用邊緣縮減補償 (Margin Compensation)"))
        self.chk_margin_comp.setObjectName("SubCheckBox")
        self.chk_margin_comp.setChecked(ui_state.get("margin_compensation", True))
        self.chk_margin_comp.setEnabled(ui_state.get("precise_ocr_highlight", False))

        self.chk_precise_ocr.stateChanged.connect(self._on_precise_highlight_changed)
        self.chk_margin_comp.stateChanged.connect(self._on_margin_comp_changed)

        self.chk_dedup = QCheckBox(trans.t("hotkeys", "chk_dedup", "啟用多語系重疊防護 (Deduplication)"))
        self.chk_dedup.setChecked(ui_state.get("ocr_deduplication", True))
        self.chk_dedup.stateChanged.connect(self._on_dedup_changed)

        layout_visual.addWidget(self.chk_precise_ocr)
        layout_visual.addWidget(self.chk_margin_comp)
        dash = QFrame(); dash.setFrameShape(QFrame.Shape.HLine); dash.setObjectName("DashedLine")
        layout_visual.addWidget(dash)
        layout_visual.addWidget(self.chk_dedup)
        layout.addWidget(group_visual)

        layout.addStretch(1)

    # ------------------------------------------------------------------ handlers
    def _on_wasd_mode_changed(self, index: int):
        wasd_map = {0: "nav", 1: "close", 2: "sync"}
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["preview_wasd_mode"] = wasd_map.get(index, "nav")
        self.ctx["config"].set("ui_state", ui_state)

    def _on_ocr_mode_changed(self, index: int):
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["ocr_shift_mode"] = "toggle" if index == 1 else "hold"
        self.ctx["config"].set("ui_state", ui_state)

    def _on_precise_highlight_changed(self, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        if not is_checked:
            self.chk_margin_comp.setChecked(False)
        self.chk_margin_comp.setEnabled(is_checked)
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["precise_ocr_highlight"] = is_checked
        self.ctx["config"].set("ui_state", ui_state)

    def _on_margin_comp_changed(self, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["margin_compensation"] = is_checked
        self.ctx["config"].set("ui_state", ui_state)

    def _on_dedup_changed(self, state: int):
        is_checked = (state == Qt.CheckState.Checked.value)
        ui_state = self.ctx["config"].get("ui_state", {})
        ui_state["ocr_deduplication"] = is_checked
        self.ctx["config"].set("ui_state", ui_state)

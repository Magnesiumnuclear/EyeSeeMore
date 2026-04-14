"""AI Engine settings page (CLIP models + OCR language packs).

Emits:
  clip_model_changed(str)  – model_id – wired up by SettingsDialog to MainWindow

Context keys:
  config, translator, engine, theme_manager

hub keys:
  navigate_to_ai_ocr_tab – callable: go to this page / OCR tab (for cross-page jump)
"""
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QGroupBox, QTabWidget, QProgressBar, QPushButton, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction

from core.paths import MODELS_DIR


class AIEnginePage(QWidget):
    clip_model_changed = pyqtSignal(str)   # payload: model_id

    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        trans = ctx["translator"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)

        title = QLabel(trans.t("ai_engine", "page_title", "🧠 AI 引擎設定 (AI Engine)"))
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine); sep.setObjectName("PageHLine")
        sep.hide()
        layout.addWidget(sep)

        # ── Download status bar ───────────────────────────────────────────
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

        # ── Tab widget ────────────────────────────────────────────────────
        self.ai_tabs = QTabWidget()
        self.ai_tabs.setObjectName("AITabs")

        # -- Tab: CLIP semantic models ------------------------------------
        tab_clip = QWidget()
        clip_layout = QVBoxLayout(tab_clip)
        clip_layout.setContentsMargins(20, 20, 20, 20)
        clip_layout.setSpacing(15)

        group_clip = QGroupBox(trans.t("ai_engine", "grp_clip_title", "語意搜尋模型 (Semantic Models)"))
        clip_list_layout = QVBoxLayout(group_clip)
        clip_list_layout.setSpacing(10)

        current_model = ctx["config"].get("model_name")
        mock_clips = [
            {
                "name": trans.t("ai_engine", "model_std_name",   "🟢 標準模式 (ViT-B-32)"),
                "id":   "ViT-B-32",
                "pre":  "laion2b_s34b_b79k",
                "desc": trans.t("ai_engine", "model_std_desc",   "速度極快，佔用極低"),
            },
            {
                "name": trans.t("ai_engine", "model_acc_name",   "🔵 精準模式 (ViT-H-14)"),
                "id":   "ViT-H-14",
                "pre":  "laion2b_s32b_b79k",
                "desc": trans.t("ai_engine", "model_acc_desc",   "準確度高，細節辨識佳"),
            },
            {
                "name": trans.t("ai_engine", "model_multi_name", "🟣 多語系模式 (xlm-roberta)"),
                "id":   "xlm-roberta-large-ViT-H-14",
                "pre":  "frozen_laion5b_s13b_b90k",
                "desc": trans.t("ai_engine", "model_multi_desc", "支援中文等多國語言搜尋"),
            },
        ]

        for item in mock_clips:
            row = QHBoxLayout()
            muted_color = ctx["theme_manager"].current_colors.get("text_muted", "#888888")
            lbl_name = QLabel(
                f"{item['name']}<br>"
                f"<span style='color:{muted_color}; font-size:12px;'>{item['desc']}</span>"
            )
            lbl_name.setFixedWidth(240)
            lbl_name.setTextFormat(Qt.TextFormat.RichText)

            is_active = (item["id"] == current_model)
            if is_active:
                status_text = trans.t("ai_engine", "status_running",  "✅ 運行中")
                state_val   = "running"
                btn_text    = trans.t("ai_engine", "btn_in_use",       "目前使用中")
                btn_enabled = False
            else:
                status_text = trans.t("ai_engine", "status_installed", "💾 已安裝")
                state_val   = "installed"
                btn_text    = trans.t("ai_engine", "btn_switch",       "切換並重啟")
                btn_enabled = True

            lbl_status = QLabel(status_text)
            lbl_status.setObjectName("ModelStatusLabel")
            lbl_status.setProperty("state", state_val)

            btn_action = QPushButton(btn_text)
            btn_action.setFixedWidth(100)
            btn_action.setEnabled(btn_enabled)
            btn_action.setProperty("cssClass", "ActionBtn")
            if btn_enabled:
                btn_action.clicked.connect(
                    lambda checked, m_id=item["id"], pre=item["pre"]:
                        self._on_switch_clip_model(m_id, pre)
                )

            row.addWidget(lbl_name)
            row.addWidget(lbl_status)
            row.addStretch(1)
            row.addWidget(btn_action)
            clip_list_layout.addLayout(row)

            ln = QFrame(); ln.setFrameShape(QFrame.Shape.HLine); ln.setObjectName("SolidLine")
            clip_list_layout.addWidget(ln)

        clip_layout.addWidget(group_clip)
        clip_layout.addStretch(1)
        self.ai_tabs.addTab(tab_clip, trans.t("ai_engine", "tab_clip", "👁️ CLIP 語意模型"))

        # -- Tab: OCR language packs --------------------------------------
        tab_ocr = QWidget()
        ocr_layout = QVBoxLayout(tab_ocr)
        ocr_layout.setContentsMargins(20, 20, 20, 20)
        ocr_layout.setSpacing(15)

        group_lang = QGroupBox(trans.t("ai_engine", "grp_ocr_title", "語系擴充包 (Language Packs)"))
        self.lang_layout = QVBoxLayout(group_lang)
        self.lang_layout.setSpacing(10)

        ocr_layout.addWidget(group_lang)
        ocr_layout.addStretch(1)
        self.ai_tabs.addTab(tab_ocr, trans.t("ai_engine", "tab_ocr", "📝 OCR 文字辨識"))

        layout.addWidget(self.ai_tabs, stretch=1)

        self.lang_ui_elements: dict = {}
        self.refresh_ocr_status()

    # ------------------------------------------------------------------ public refresh
    def refresh_ocr_status(self):
        """Rebuild OCR language-pack status rows."""
        while self.lang_layout.count():
            item = self.lang_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
                item.layout().deleteLater()

        trans = self.ctx["translator"]
        models_dir = os.path.join(MODELS_DIR, "ocr")

        active_langs: set = set()
        for f in self.ctx["config"].get("source_folders", []):
            active_langs.update(f.get("enabled_langs", []))

        langs = [
            ("ch", trans.t("ai_engine", "lang_ch", "🇨🇳 中文 (通用)")),
            ("jp", trans.t("ai_engine", "lang_jp", "🇯🇵 日文 (日本語)")),
            ("kr", trans.t("ai_engine", "lang_kr", "🇰🇷 韓文 (한국어)")),
            ("en", trans.t("ai_engine", "lang_en", "🇬🇧 英文 (English)")),
        ]
        self.lang_ui_elements.clear()

        for lang_code, name in langs:
            rec_path  = os.path.join(models_dir, lang_code, "rec.onnx")
            dict_path = os.path.join(models_dir, lang_code, "dict.txt")
            is_installed = os.path.exists(rec_path) and os.path.exists(dict_path)
            is_running   = lang_code in active_langs

            if is_running and is_installed:
                status    = trans.t("ai_engine", "status_running",       "✅ 運行中")
                state_val = "running"
                btn_text  = trans.t("ai_engine", "btn_enabled",          "已啟用")
                btn_enabled = False
            elif is_installed:
                status    = trans.t("ai_engine", "status_installed",     "💾 已安裝")
                state_val = "installed"
                btn_text  = trans.t("ai_engine", "btn_apply",            "套用")
                btn_enabled = True
            else:
                status    = trans.t("ai_engine", "status_not_installed", "📥 未安裝")
                state_val = "missing"
                btn_text  = trans.t("ai_engine", "btn_import",           "匯入")
                btn_enabled = True

            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 5, 0, 5)

            lbl_name = QLabel(name)
            lbl_name.setFixedWidth(160)
            lbl_name.setStyleSheet("font-size: 14px; font-weight: bold; background: transparent;")

            lbl_status = QLabel(status)
            lbl_status.setObjectName("ModelStatusLabel")
            lbl_status.setProperty("state", state_val)

            btn_action = QPushButton(btn_text)
            btn_action.setFixedWidth(90)
            btn_action.setEnabled(btn_enabled)

            if btn_enabled and not is_installed:
                btn_action.setProperty("cssClass", "ActionBtn")
                btn_action.clicked.connect(
                    lambda checked, lc=lang_code: self._start_download_ocr(lc)
                )
            elif btn_enabled and is_installed:
                btn_action.setProperty("cssClass", "SuccessBtn")
                btn_action.clicked.connect(
                    lambda checked: QMessageBox.information(self, "提示", "此語言包已就緒！...")
                )
            else:
                btn_action.setProperty("cssClass", "ActionBtn")

            row.addWidget(lbl_name)
            row.addWidget(lbl_status)
            row.addStretch(1)
            row.addWidget(btn_action)

            self.lang_layout.addWidget(row_widget)
            self.lang_ui_elements[lang_code] = {"status": lbl_status, "btn": btn_action}

            ln = QFrame(); ln.setFrameShape(QFrame.Shape.HLine); ln.setObjectName("SolidLine")
            self.lang_layout.addWidget(ln)

    # ------------------------------------------------------------------ private helpers
    def _on_switch_clip_model(self, model_id: str, pretrained: str):
        img_path = os.path.join(MODELS_DIR, "onnx_clip", f"{model_id}_image.onnx")
        txt_path = os.path.join(MODELS_DIR, "onnx_clip", f"{model_id}_text.onnx")
        if os.path.exists(img_path) and os.path.exists(txt_path):
            self.ctx["config"].set("model_name", model_id)
            self.ctx["config"].set("pretrained", pretrained)
            self.clip_model_changed.emit(model_id)
        else:
            QMessageBox.warning(
                self, "模型缺失",
                f"在本地找不到 {model_id} 的 ONNX 檔案。\n\n"
                "請先將對應的模型檔案放入 `models/onnx_clip/` 資料夾中，或透過安裝包匯入。"
            )

    def _start_download_ocr(self, lang_code: str):
        from PyQt6.QtWidgets import QFileDialog
        zip_path, _ = QFileDialog.getOpenFileName(
            self, f"選擇 {lang_code.upper()} 語言模型包 (ZIP)", "", "ZIP Files (*.zip)"
        )
        if not zip_path:
            return

        self.dl_progress.setFixedHeight(12)
        self.dl_progress.setValue(0)
        self.dl_status_label.setText(f"準備匯入 {lang_code.upper()} 語言包...")
        self.dl_status_label.show()

        for elems in self.lang_ui_elements.values():
            elems["btn"].setEnabled(False)

        # OCRImportWorker class is injected via ctx["ocr_worker_class"]
        OCRImportWorker = self.ctx["ocr_worker_class"]
        self.dl_worker = OCRImportWorker(lang_code, zip_path)
        self.dl_worker.progress_update.connect(self._update_download_progress)
        self.dl_worker.finished_signal.connect(self._on_download_finished)
        self.dl_worker.start()

    def _update_download_progress(self, percent: int, msg: str):
        self.dl_progress.setValue(percent)
        self.dl_status_label.setText(msg)

    def _on_download_finished(self, success: bool, lang_code: str, msg: str):
        self.dl_progress.setFixedHeight(2)
        self.dl_progress.setValue(0)
        self.dl_status_label.hide()
        if success:
            QMessageBox.information(self, "下載成功", msg)
        else:
            QMessageBox.critical(self, "下載失敗", msg)
        self.refresh_ocr_status()

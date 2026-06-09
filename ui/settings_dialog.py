"""Settings-related dialogs.

Contains:
  - OnboardingDialog  — first-run welcome & hardware auto-config panel
  - SettingsDialog    — nav ↔ stack container; all page logic lives in
                        ui/settings_pages/ sub-modules
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QStackedWidget,
)


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
        # OCRImportWorker 尚在 Blur-main.py，使用延遲匯入避免循環依賴
        from Blur_main import OCRImportWorker  # noqa: F401 — 待 workers 模組完成後更新

        ctx = {
            "config":             mw.config,
            "translator":         trans,
            "engine":             mw.engine,
            "theme_manager":      mw.theme_manager,
            "change_view_mode":   mw.change_view_mode,
            "reload_index":       mw.trigger_background_db_reload,
            "refresh_sidebar":    mw.refresh_sidebar,
            "on_refresh_clicked": mw.on_refresh_clicked,
            "current_view_mode":  mw.gallery_ctrl.current_view_mode,
            "ocr_worker_class":   OCRImportWorker,
            "apply_eta_mode":     mw.apply_eta_mode,
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
        hub["refresh_ocr_status"]     = self._ai_page.refresh_ocr_status
        hub["refresh_folder_list"]    = self._folders_page.refresh_folder_list
        hub["navigate_to_ai_ocr_tab"] = self._navigate_to_ai_ocr_tab

        # ── 透傳 AIEnginePage 的 clip_model_changed ───────────────────────
        self._ai_page.clip_model_changed.connect(self.clip_model_changed)

        self.nav_list.setCurrentRow(0)

    def _navigate_to_ai_ocr_tab(self):
        """跨頁面跳轉：切換至 AI 引擎頁面的 OCR 分頁。"""
        self.nav_list.setCurrentRow(1)           # AI 引擎 = index 1
        self._ai_page.ai_tabs.setCurrentIndex(1)  # OCR 分頁 = index 1

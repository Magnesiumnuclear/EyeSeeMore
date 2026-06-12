# ARCHITECTURE.md — 目錄架構與職責劃分

## 目錄結構

```
rag-image/
├── main.py                   ← 對外啟動入口
├── Blur-main.py              ← 主程式（~1400 行，僅含 MainWindow + 啟動代碼）
├── indexer.py                ← 背景索引引擎
├── onnx_ocr.py               ← ONNX PaddleOCR 推論
│
├── core/                     ← 零 UI 依賴的業務邏輯層
│   ├── config_manager.py     ← 應用程式設定 I/O
│   ├── paths.py              ← 路徑常數中心
│   ├── win_titlebar.py       ← 自訂標題列 DLL 橋接
│   ├── search_orchestrator.py ← SearchWorker 生命週期
│   ├── image_action_manager.py ← 圖片右鍵選單動作
│   ├── pin_manager.py        ← 釘選功能 (Phase 1-A)
│   ├── ocr_repository.py     ← OCR 框 CRUD (Phase 1-B)
│   ├── collection_manager.py ← 虛擬資料夾管理 (Phase 1-C)
│   ├── search_history_manager.py ← 搜尋歷史 (Phase 2-A)
│   ├── eta_progress_controller.py ← ETA + PID (Phase 2-B)
│   ├── indexing_lifecycle.py ← 掃描生命週期 (Phase 2-C)
│   ├── model_provider.py     ← 模型加載與共享 (Phase 3-A)
│   ├── image_search_engine.py ← AI 核心引擎 (Phase 3-F)
│   ├── taskbar_controller.py ← Windows 工作列 COM 橋接 (Phase 3-F)
│   ├── win_event_filters.py  ← Win32 原生事件過濾器 + Jump List (Phase 3-F)
│   └── workers.py            ← QThread/QRunnable 工作者執行緒 (Phase 3-F)
│
├── ui/                       ← 視圖控制器與 widget 層
│   ├── main_window_ui.py     ← MainWindow 佈局
│   ├── theme_manager.py      ← 主題管理
│   ├── navigation_manager.py ← 上一頁/下一頁導航
│   ├── action_handler.py     ← 鍵盤滑鼠事件分發
│   ├── inspector_panel.py    ← 右側 3 分頁面板
│   ├── gallery_view_controller.py ← 畫廊視圖控制器 (Phase 2-D)
│   ├── window_state_manager.py   ← 視窗狀態 + Win32 (Phase 2-E)
│   ├── gallery_model.py      ← 畫廊 Model + ListView (Phase 3-F)
│   ├── preview_overlay.py    ← 全螢幕圖片預覽層 (Phase 3-F)
│   ├── settings_dialog.py    ← 設定對話框 + Onboarding (Phase 3-F)
│   ├── sidebar_widget.py     ← 左側邊欄 + Hover 選單 (Phase 3-F)
│   │
│   ├── widgets/
│   │   ├── base.py           ← BaseToggleWidget 基類
│   │   ├── drag_list.py      ← 半透明拖曳列表
│   │   ├── elided_label.py   ← 自動省略文字的 QLabel (Phase 3-C)
│   │   ├── search_capsule.py ← 頂部搜尋膠囊
│   │   ├── empty_state.py    ← 空狀態覆蓋層 (Phase 3-F)
│   │   ├── feature_widgets.py ← 特徵標籤面板 (Phase 3-F)
│   │   ├── image_delegate.py ← 圖片卡片繪製代理 (Phase 3-F)
│   │   └── ocr_widgets.py    ← OCR 框選與標籤 widget (Phase 3-F)
│   │
│   └── settings_pages/
│       ├── folders_page.py   ← 資料夾管理
│       ├── ai_engine_page.py ← AI 引擎設定
│       ├── appearance_page.py ← 介面與顯示
│       ├── hotkeys_page.py   ← 快捷鍵設定
│       ├── performance_page.py ← 效能調整
│       ├── auto_tasks_page.py ← 自動任務
│       ├── language_page.py  ← 語言選擇
│       └── about_page.py     ← 關於與說明
│
├── utils/
│   └── translator.py         ← i18n 翻譯器
│
├── benchmarks/               ← 效能測試套件（量測 + 優化驗收，見 benchmarks/README.md）
│
├── models/                   ← AI 模型權重
├── themes/                   ← QSS 主題
├── languages/                ← i18n JSON
├── data/                     ← 範例圖片
├── src_cpp/                  ← C++ 元件源碼
├── build/                    ← C++ 編譯產物
├── .cache/                   ← 執行期快取（自動生成，勿入版控）
│   ├── thumbnails/           ← L2 縮圖快取（indexer 與 UI 共用，路徑見 core/paths.py）
│   └── faiss/                ← FAISS HNSW 索引磁碟快取
│
├── config.json               ← 使用者設定
├── images.db                 ← SQLite 索引資料庫
└── search_history.json       ← 搜尋歷史
```

## 分層設計

### `core/` — 零 UI 依賴的業務邏輯

**職責：** 純數據邏輯、資料庫 CRUD、AI 模型、算法

**可依賴：** `PyQt6.QtCore`、`sqlite3`、`numpy`、`onnxruntime`、`faiss`

**禁忌：** 不能持有 QWidget 參照；所有 UI 更新透過 `pyqtSignal` 發射

**特點：** 可繼承 QObject 以使用訊號機制，但只能發訊號，不能直接操作 UI

---

### `ui/` — 視圖控制器與 widget 層

**職責：** UI 佈局、事件處理、widget 組合、訊號連接

**可依賴：** 所有 PyQt、`core/` 模組

**禁忌：** 業務邏輯應委派給 `core/`；不能把複雜邏輯寫在 widget 裡

**特點：** **可以直接持有 QWidget 參照**（list_view / model / delegate），這是 View Controller 模式的合理設計

---

### `ui/widgets/` — 可複用原子 widget

**職責：** 自訂小元件（搜尋膠囊、拖曳列表、省略標籤等）

**禁忌：** 不能持有 MainWindow 內部狀態；應透過訊號或參數通信

---

### `ui/settings_pages/` — 設定對話框分頁

**職責：** 各分頁的設定 UI

**特點：** 透過 `ctx: dict` 統一注入依賴（`engine` / `config` / `translator` 等），**完全不持有 main_window 參照**

---

### `utils/` — 跨層通用工具

**職責：** 純函式或無狀態類別（翻譯器、助手函式等）

**禁忌：** 不能依賴 PyQt、`core/`、`ui/`——只能用標準庫

---

## 主程式棧

```
main.py
  ↓ runpy.run_path()
Blur-main.py (~1400 行，Phase 3-F 重構後)
  ├── import 區段（僅輕量模組；最頂端的 import onnxruntime 是
  │   DLL 順序保護，必須先於 PyQt6——重模組延後策略見 MODEL_LOADING.md）
  ├── class MainWindow(QMainWindow)  ← 唯一保留的 class
  │     ├── __init__: 組裝所有 core/ + ui/ 模組
  │     ├── 訊號連接
  │     └── 事件處理槽函式
  └── if __name__ == "__main__": QApplication 啟動

已拆分到獨立模組的 class（Phase 3-F）：
  core/image_search_engine.py  ← ImageSearchEngine (AI 核心)
  core/taskbar_controller.py   ← TaskbarController (工作列 COM)
  core/win_event_filters.py    ← WinMaxHoverFilter, WinScanCtrlFilter, Jump List
  core/workers.py              ← IndexerWorker, SearchWorker, OCRImportWorker 等
  ui/gallery_model.py          ← SearchResultsModel, GalleryListView
  ui/preview_overlay.py        ← PreviewOverlay
  ui/settings_dialog.py        ← SettingsDialog, OnboardingDialog
  ui/sidebar_widget.py         ← SidebarWidget + StatsMenuWidget 等
  ui/widgets/empty_state.py    ← EmptyStateOverlay
  ui/widgets/feature_widgets.py ← TextFeatureWidget, FeatureBucketWidget 等
  ui/widgets/image_delegate.py ← ImageItem, ImageDelegate, ThumbnailLoader 等
  ui/widgets/ocr_widgets.py    ← CropOCRWorker, FloatingWidget, OCRLabel
```

---

## 核心與背景服務

| 腳本 | 職責 |
|------|------|
| **`indexer.py`** | 獨立可執行的索引引擎：掃描資料夾 → 提取 EXIF/縮圖 → CLIP 向量化 → OCR → 寫入 DB |
| **`onnx_ocr.py`** | ONNX PaddleOCR 推論引擎：加載 det/rec 模型，提供統一 `ocr()` 接口 |
| **`cleanup_db.py`** | 一次性維護腳本：清理孤兒 collection_items |
| **`export_clip_onnx.py`** | 模型轉換（PyTorch CLIP → ONNX） |
| **`pack_release.py`** | 發佈套件打包（由 build_installer.bat 呼叫） |

---

## 相關詳細文檔

- **各層職責與禁忌** → 見 [LAYERS.md](./LAYERS.md)
- **8 個核心模組詳解** → 見 [MODULES_CORE.md](./MODULES_CORE.md)
- **UI 控制器與 widgets** → 見 [MODULES_UI.md](./MODULES_UI.md)

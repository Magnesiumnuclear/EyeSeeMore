# EyeSeeMore — 架構地圖與開發指南

> **EyeSeeMore（諧音 "I see more"）** — 以 CLIP 視覺向量 + OCR 文字 + FAISS 為核心的本地端圖片語意搜尋器。即便檔名是亂碼，也能透過圖片內容與隱藏文字精準找到。

本文件記錄完成 Phase 1 + Phase 2 重構後的專案架構與開發慣例，是接手開發者（或 AI Agent）的入門指南。

---

## 🏗 一、目錄架構與職責大綱

```
rag-image/
├── Blur-main.py              ← 主程式（單檔 ~6300 行：UI 主視窗、Worker、入口）
├── main.py                   ← 對外啟動入口（runpy 包裝 Blur-main.py）
├── indexer.py                ← 背景索引引擎（CLIP 向量化 + OCR + DB 寫入）
├── onnx_ocr.py               ← ONNX 版 PaddleOCR 推論引擎
│
├── core/                     ← 【零 UI 依賴的核心業務邏輯層】
├── ui/                       ← 【視圖控制器與 PyQt 元件層】
│   ├── settings_pages/       ←   設定對話框各分頁
│   └── widgets/              ←   可複用原子 widget
├── utils/                    ← 通用工具（目前只有 Translator）
│
├── models/                   ← AI 模型權重檔
│   ├── onnx_clip/            ←   ONNX 格式 CLIP 模型（_image.onnx / _text.onnx）
│   ├── ocr/                  ←   PaddleOCR ONNX 權重（det / rec 多語系）
│   ├── tokenizers/           ←   HuggingFace tokenizer 離線檔
│   └── parametric_umap_encoder.keras ← 向量空間視覺化用
│
├── themes/                   ← QSS 主題（dark.json / light.json + base_style.qss）
├── languages/                ← i18n JSON（zh_TW / en_US）
├── data/                     ← 範例圖片資料夾
├── src_cpp/                  ← C++ 元件原始碼（win_titlebar DLL / installer / launcher）
├── build/                    ← C++ 編譯產物（EyeSeeMoreWin.dll 等）
├── User_Environment/         ← 攜帶版 Python 3.10 環境
├── EyeSeeMore_installer/     ← 打包後的安裝器產物
├── config.json               ← 使用者設定（ui_state、源資料夾、AI 模型等）
├── images.db                 ← SQLite 索引資料庫（files / embeddings / ocr_results / pinned / collections）
└── search_history.json       ← 最近 10 筆搜尋字串
```

### 各層設計原則

| 層級 | 設計原則 | 可依賴什麼 | 不可依賴什麼 |
|------|---------|-----------|-------------|
| **`core/`** | 零 UI 依賴的核心業務邏輯。可繼承 `QObject` 以使用訊號機制，但**不持有任何 QWidget 參照**，所有 UI 更新透過 `pyqtSignal` 對外發射 | `PyQt6.QtCore`、`sqlite3`、`numpy`、`onnxruntime`、`faiss` | `PyQt6.QtWidgets`、`PyQt6.QtGui` 內的具體元件 |
| **`ui/`** | 視圖控制器與 widget。**可以**直接持有 QWidget 參照（list_view / model / delegate 等），這是 View Controller 模式的合理設計 | 所有 PyQt、`core/` | 業務邏輯不應寫在這裡（應委派給 `core/`） |
| **`ui/widgets/`** | 可複用的原子 widget。每個檔案一個小型自訂元件 | PyQt、`core/`、其他 widgets | MainWindow 內部狀態（應透過訊號或參數） |
| **`ui/settings_pages/`** | SettingsDialog 各分頁。透過 `ctx` 字典統一注入依賴，**不持有 main_window 參照** | PyQt、`core/`、`ctx["engine"/"config"/...]` | `main_window` 直接參照 |
| **`utils/`** | 跨層通用工具，純函式或無狀態類別 | 標準庫 | PyQt、`core/`、`ui/` |

---

## 📦 二、核心模組任務總覽

### 🚪 主程式入口

| 檔案 | 行數 | 任務 |
|------|------|------|
| **`main.py`** | 13 | 對外啟動入口；因 `Blur-main.py` 檔名含連字號無法直接 import，用 `runpy.run_path()` 啟動 |
| **`Blur-main.py`** | ~6300 | 主程式：MainWindow 主視窗、各種 QThread Worker（IndexerWorker / SearchWorker / OCRImportWorker）、ImageDelegate 自繪卡片、PreviewOverlay 圖片預覽、SidebarWidget 側邊欄、Win32 native event filters（WinMaxHoverFilter / WinScanCtrlFilter）、SettingsDialog 設定對話框、應用程式進入點 `if __name__ == "__main__"` |

### 🧠 `core/` — 核心業務邏輯（零 UI 依賴）

| 模組 | Phase | 任務 |
|------|-------|------|
| **`config_manager.py`** | 原有 | 應用程式設定的單一真理源；管理 `config.json` 的載入、儲存、深層合併、舊結構遷移；支援 source folder / collection icon / language 的細粒度操作 |
| **`paths.py`** | 原有 | 專案路徑常數中心（BASE_DIR 等）；所有子模組從這裡匯入，避免各自計算 `__file__` 層數 |
| **`win_titlebar.py`** | 原有 | 自訂標題列 DLL 橋接：載入 `EyeSeeMoreWin.dll`、提供 `install()` / `update_button_rects()` / `uninstall()`；DLL 不存在時靜默降級為 no-op |
| **`search_orchestrator.py`** | 原有 | `SearchWorker` 的生命週期管理；保證舊 Worker 安全退役（斷訊號 + 收容所防 C++ 幽靈物件）；統一解析 `fetch_k` / `target_folder` 參數 |
| **`image_action_manager.py`** | 原有 | 圖片右鍵選單動作（開啟 / 複製 / 重新命名 / 屬性 / 在檔案總管中顯示）；菜單建構工廠 |
| **`pin_manager.py`** | **1-A** | 圖片釘選：`pinned` 表的 CRUD、記憶體 `pinned_paths` 快取、`merge_pinned_to_top()` 置頂合併。採 callable 依賴注入避免 data_store rebinding 問題 |
| **`ocr_repository.py`** | **1-B** | OCR 框資料存取層：`ocr_results` 表的 4 個 CRUD 方法（get_by_path / upsert / delete_box / update_box_text）。內建 `_boxes_match` ±2px 容忍度比對 helper |
| **`collection_manager.py`** | **1-C** | 虛擬資料夾管理：`collections` + `collection_items` 兩表的 CRUD、icon 欄位冪等遷移、與 `data_store` by-reference 共享以快速產生資料夾內容清單 |
| **`search_history_manager.py`** | **2-A** | 搜尋歷史紀錄：`search_history.json` 的 I/O、MRU（Most Recently Used）行為、`MAX_ITEMS = 10` 自動截斷 |
| **`eta_progress_controller.py`** | **2-B** | ETA 進度控制器（QObject）：4 種顯示模式、PID 假時間平滑器（mode 2）、100ms QTimer tick。發射 `status_text_changed` / `progress_updated` 訊號 |
| **`indexing_lifecycle.py`** | **2-C** | 索引生命週期（QObject）：Worker 完成事件、暫停/繼續/取消、背景 DB 雙緩衝重載。發射 6 個 UI 訊號 + 1 個內部跨執行緒橋接訊號 `_db_reloaded` |

### 🖼 `ui/` — 視圖控制器與元件

| 模組 | Phase | 任務 |
|------|-------|------|
| **`main_window_ui.py`** | 原有 | 純 UI 佈局類別 `Ui_MainWindow`，負責在 MainWindow 上建立所有視覺元件、splitter、top_bar、信號連接。`setup_ui()` 前 MainWindow 必須有 `self.config` 與 `self.history_mgr` 屬性 |
| **`theme_manager.py`** | 原有 | 主題管理：讀取 `themes/*.json` + `base_style.qss`，動態套用至 QApplication；提供 `get_available_themes()` / `apply_theme()` |
| **`navigation_manager.py`** | 原有 | 上一頁/下一頁導航堆疊：純資料結構 + 回呼函式模式（不使用訊號）；維護 back/forward 兩個 stack 與 `pending_scroll_pos` |
| **`action_handler.py`** | 原有 | 鍵盤與滑鼠事件統一分發：將 Escape / Shift / WASD / Space / Ctrl+C / 歷史切換等事件轉換為 9 個 `request*` 訊號 |
| **`inspector_panel.py`** | 原有 | 右側 3 分頁面板（搜尋過濾 / 屬性檢視 / OCR 結果）；含 `CollapsibleSection` 摺疊區塊與 `RangeCalendarWidget` 日期區間日曆 |
| **`gallery_view_controller.py`** | **2-D** | 畫廊視圖控制器（QObject）：搜尋結果儲存、3 層過濾（時間/比例/Limit）、5 種排序（含釘選永遠置頂）、視圖模式切換、Grid 動態均分佈局、空狀態診斷。發射 4 個訊號 |
| **`window_state_manager.py`** | **2-E** | 視窗狀態與 Win32 整合（QObject）：釘選 TOPMOST（Win32 SetWindowPos）、最大化/還原、NC hit-test 按鈕座標通知、saveGeometry/restoreGeometry 封裝、Win32 資源回收。不發訊號（直接操作注入的 widget） |

### 🧩 `ui/widgets/` — 可複用原子 widget

| 檔案 | 任務 |
|------|------|
| **`base.py`** | `BaseToggleWidget`：所有 EyeSeeMore 自訂 widget 的基類，統一持有 `errorOccurred` 訊號（全域錯誤協議） |
| **`drag_list.py`** | `TransparentDragListWidget`：拖曳時產生半透明鬼影的 QListWidget |
| **`search_capsule.py`** | `SearchCapsule`：頂部搜尋膠囊（輸入框 + 模式切換 + 歷史下拉彈窗）；發射 `searchRequested(dict)` / `modeChanged(str)` |

### ⚙️ `ui/settings_pages/` — 設定對話框分頁

統一透過 `ctx: dict` 注入依賴（`config` / `translator` / `engine` / `theme_manager` 等），子頁面間透過 `ctx["hub"]` 做跨頁面回呼，**不持有 main_window 參照**。

| 檔案 | 分頁 |
|------|------|
| `folders_page.py` | 📁 資料夾管理（新增/移除/排序/圖示） |
| `ai_engine_page.py` | 🧠 AI 引擎設定（CLIP 模型切換 + OCR 語言包安裝） |
| `appearance_page.py` | 🖥️ 介面與顯示（主題、啟動資料夾、圖示大小） |
| `hotkeys_page.py` | ⌨️ 操作與快捷鍵（WASD / Shift-OCR / 視覺效果） |
| `performance_page.py` | ⚡ 效能調整（縮圖快取、執行緒數） |
| `auto_tasks_page.py` | 🕒 自動任務（OCR 任務綁定、啟動行為） |
| `language_page.py` | 🌍 語言切換（動態掃描 `languages/*.json`） |
| `about_page.py` | ℹ️ 關於與說明（版本、GitHub、技術致敬） |

### 🛠 `utils/` — 通用工具

| 檔案 | 任務 |
|------|------|
| **`translator.py`** | i18n 翻譯器：讀取 `languages/<lang>.json`，提供 `t(category, key, default)` 介面 |

### 🌐 背景服務與獨立腳本

| 腳本 | 任務 |
|------|------|
| **`indexer.py`** | 背景索引引擎：掃描資料夾、提取 EXIF / 縮圖、CLIP 向量化、OCR 辨識（含多語系）、寫入 SQLite。獨立可執行；亦由 MainWindow 的 IndexerWorker 內部呼叫 |
| **`onnx_ocr.py`** | ONNX 版 PaddleOCR：載入 det/rec 模型 + 字典檔，提供統一的 `ocr()` 介面 |
| **`cleanup_db.py`** | 一次性維護腳本：清理孤兒 `collection_items`、重置 collections 自增 ID |
| **`export_clip_onnx.py`** | （離線版）將 PyTorch CLIP 模型轉為 ONNX；舊版下載功能已廢棄 |
| **`dev_model_exporter.py`** | 開發者模型匯出（open_clip → ONNX） |
| **`fix_env.py`** | `User_Environment` 攜帶版 Python 環境修復腳本（補裝 faiss-cpu 等） |
| **`pack_release.py`** | 發佈套件打包腳本，由 `build_installer.bat` 呼叫 |

---

## 🏛 三、架構設計原則

### 3.1 Thin Delegation Layer（薄委派層）

**原則：** 從 MainWindow 抽出邏輯到獨立模組時，**保留 MainWindow 上的方法簽章**作為一行委派包裝，確保外部呼叫端零修改。

```python
# 重構前：MainWindow 內部複雜邏輯
def toggle_pin(self, file_path):
    if not hasattr(self, 'pinned_paths'):
        self._reload_pinned_cache()
    # ... 20 行資料庫操作 ...

# 重構後：Thin Delegation Layer
def toggle_pin(self, file_path: str) -> bool:
    """[委派] 切換圖片釘選狀態。"""
    return self.pin_manager.toggle(file_path)
```

**使用時機：**
- 該方法被 `MainWindow` 以外的程式碼（其他 UI 元件、Worker、外部模組）呼叫過
- 該方法被連接為 `pyqtSignal` 的 slot

**何時可以省略 delegate：**
- 方法純屬內部呼叫，沒有外部 caller
- 完全私有的 implementation details

### 3.2 依賴注入三大策略

依照「被依賴的物件何時可用」選擇不同模式：

| 策略 | 適用場景 | 範例 |
|------|---------|------|
| **建構子直接傳入** | 依賴在建構時已就緒（早期可用） | `OcrRepository(db_path=...)`、`EtaProgressController(mode=...)` |
| **延遲屬性注入** | 依賴在建構後才建立（如 engine 在 `load_engine()` 才實例化） | `self.indexing_handler.engine = engine`（同 `SearchOrchestrator.engine` 模式） |
| **Callable Provider** | 依賴會被 rebinding，需要永遠取得最新參照 | `PinManager(data_store_provider=lambda: engine.data_store)` |

**配套地雷修復：**
> Phase 1-A 發現 `data_store` 被 rebinding 會讓 `PinManager` 持有舊參照。Phase 1-C 配套改 `load_data_from_db()` 為**就地修改**（`list.clear()` + `list.extend()`）保留參照，此後 by-reference 注入才安全。

```python
# load_data_from_db 內：原本是 rebinding
self.data_store = temp_data_store  # ❌ 會破壞下游持有的參照

# 重構後：就地修改保留 list 身分
self.data_store.clear()
self.data_store.extend(temp_data_store)  # ✅
```

### 3.3 PyQt 訊號 (Signal) 解耦規範

**何時應該用 Signal 解耦：**

| 情境 | 訊號類型 | 範例 |
|------|---------|------|
| 跨層通知（core → UI） | 對外 `pyqtSignal` | `EtaProgressController.status_text_changed(str)` |
| 跨執行緒橋接（worker thread → UI thread） | 內部 `pyqtSignal` 自連 | `IndexingLifecycleHandler._db_reloaded` |
| 多訂閱者觀察事件 | 對外 `pyqtSignal` | `GalleryViewController.layout_changed()` |

**何時可以直接呼叫 widget：**

- View Controller 直接持有的 widget（已注入的 list_view / model / delegate）
- 同層 UI 元件間（widget 之間的協作）
- Win32 系統整合（HWND 操作沒有訂閱者場景）

**訊號連接時序陷阱：**

```python
# ❌ 錯：self.status 在 init_ui() 後才存在
self.eta_ctrl = EtaProgressController(...)
self.eta_ctrl.status_text_changed.connect(self.status.setText)  # AttributeError!
self.init_ui()

# ✅ 對：先 init_ui 建立 UI 元件，再連接訊號
self.init_ui()
self.eta_ctrl = EtaProgressController(...)
self.eta_ctrl.status_text_changed.connect(self.status.setText)
```

### 3.4 跨執行緒通訊標準作法

**模式：** 背景執行緒只 `emit` 訊號，UI 更新交給主執行緒。

```python
# 在 IndexingLifecycleHandler 內部
def trigger_background_db_reload(self) -> None:
    def bg_reload():
        self.engine.load_data_from_db()       # 重 I/O，在背景跑
        self._db_reloaded.emit()              # 跨執行緒訊號發射
    threading.Thread(target=bg_reload, daemon=True).start()

def __init__(self, ...):
    super().__init__(parent)
    # 自連：bg thread emit → Qt 自動切到主執行緒執行 slot
    self._db_reloaded.connect(self.on_db_reloaded)

def on_db_reloaded(self) -> None:
    # 此處已在主執行緒，安全地操作 UI 訊號
    self.gallery_refresh_requested.emit()
    self.sidebar_refresh_requested.emit()
```

**禁忌：**
- ❌ 背景執行緒直接寫 QWidget（如 `self.status.setText(...)`）
- ❌ 背景執行緒直接呼叫主執行緒的 method（如 `self._apply_folder_filter(...)`）
- ✅ 唯一管道：`pyqtSignal.emit(...)`，Qt 會自動跨執行緒派遣

### 3.5 Win32 整合注意事項

EyeSeeMore 是無邊框視窗 + 自訂標題列（透過 `core/win_titlebar.py` 載入 C++ DLL Hook）。處理視窗狀態時：

**地雷：** `setWindowFlag(WindowStaysOnTopHint)` 會**重建 HWND**，導致 WndProc Hook 與 `WS_THICKFRAME` 全部失效。

```python
# ❌ 錯：會毀掉自訂標題列
self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

# ✅ 對：Win32 SetWindowPos 直接切換 TOPMOST，不重建 HWND
ctypes.windll.user32.SetWindowPos(
    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
)
```

**resizeEvent 內必須同步：**
- `WindowStateManager.update_button_rects()` — 通知 WndProc Hook 新的按鈕命中座標（NC hit-test 用，**像素必須乘以 DPR**）
- `WindowStateManager.sync_max_button_state()` — 同步 btn_max 的勾選狀態與圖示

---

## 🚦 四、新增功能的標準流程

1. **判斷職責歸屬：** 是純資料邏輯 → `core/`；是 UI 編排 → `ui/`；是原子元件 → `ui/widgets/`
2. **設計依賴注入：** 依 §3.2 三大策略選一；最常見是「建構子傳入主要依賴 + 延遲注入 engine」
3. **設計訊號邊界：** 依 §3.3 規範；跨層用 signal，同層用直接呼叫
4. **MainWindow 整合：** 在 `init_ui()` 後實例化、連接訊號；若需要保留方法簽章則加 thin delegate
5. **驗證：** AST 語法檢查 + smoke test（單元行為 + 訊號發射）
6. **Commit：** 訊息以 `refactor: ...` 或 `feat: ...` 開頭，附帶設計取捨說明

---

## 📐 五、資料庫 Schema（SQLite, `images.db`）

```
files               主表：圖片元資料
├── id, file_path (UNIQUE), folder_path, filename, mtime, width, height
│
embeddings          CLIP 向量
├── file_id (FK), model_name, embedding (BLOB, float32)
│
ocr_results         OCR 框資料（多語系一張圖可多筆）
├── file_id (FK), lang, ocr_text, ocr_data (JSON), confidence
│
pinned              釘選清單
├── file_path (UNIQUE)
│
collections         虛擬資料夾
├── id, name (UNIQUE), icon, created_at
│
collection_items    虛擬資料夾的圖片成員
├── collection_id (FK ON DELETE CASCADE), file_path
│
model_stats         各模型已索引的資料夾統計
├── model_name, folder_path, image_count
```

**WAL 模式：** 所有 `core/` 內的 DB 模組都使用相同的 `_connect()` 模式：
```python
conn = sqlite3.connect(db_path, timeout=15.0)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")
```

**FAISS 索引：** 對 `embeddings` 表做 L2 正規化後使用 `IndexFlatIP`（內積 = cosine similarity）。每次 `load_data_from_db()` 重建。

---

## 📊 六、重構戰績總覽（Phase 1 + 2）

| 指標 | 重構前 | 重構後 | 變化 |
|------|--------|--------|------|
| `Blur-main.py` 總行數 | 7081 | **6346** | **−735 行 (−10.4%)** |
| `ImageSearchEngine` | 1016 | **688** | −328 行 |
| `MainWindow` 估算 | 1612 | **~1100** | −500+ 行 |
| `core/` 業務模組 | 0 | **6** | +6 |
| `ui/` 控制器 | 0 | **2** | +2 |
| 獨立可測試模組 | 0 | **8** | +8 |

### 抽離出的 8 個獨立模組

```
core/pin_manager.py              (Phase 1-A) 釘選功能
core/ocr_repository.py           (Phase 1-B) OCR 框 CRUD
core/collection_manager.py       (Phase 1-C) 虛擬資料夾
core/search_history_manager.py   (Phase 2-A) 搜尋歷史
core/eta_progress_controller.py  (Phase 2-B) ETA 進度 + PID
core/indexing_lifecycle.py       (Phase 2-C) 掃描生命週期
ui/gallery_view_controller.py    (Phase 2-D) 畫廊視圖
ui/window_state_manager.py       (Phase 2-E) 視窗狀態 + Win32
```

---

## 🎯 七、未完待續的後續方向

| 方向 | 內容 |
|------|------|
| **Phase 3** | 拆分 `PreviewOverlay` (690 行)：CropOcrController + OcrBoxEditor |
| **Phase 4** | 拆分 `ImageDelegate.paint()` (207 行) 與 `OCRLabel.paintEvent()` (110 行) 為多個私有 `_draw_*` / `_paint_*` 方法 |
| **測試補完** | 為 `core/` 內 8 個模組撰寫 pytest 單元測試 |
| **既存 Bug** | `SearchCapsule._on_history_delete` 未透過 signal 通知 MainWindow，刪除不會持久化（重啟復活） |
| **型別檢查** | 引入 mypy / pyright 並逐步補完 type hints |

---

## 📚 八、重要文件指引

| 想了解… | 看這個檔案 |
|--------|----------|
| 應用啟動流程 | `main.py` → `Blur-main.py` 底部 `if __name__ == "__main__"` |
| MainWindow 全貌 | `Blur-main.py` 中的 `class MainWindow`（約 L4900-6300） |
| AI 引擎細節 | `Blur-main.py` 中的 `class ImageSearchEngine`（約 L1260-1950） |
| UI 佈局 | `ui/main_window_ui.py` 中的 `Ui_MainWindow.setup_ui()` |
| 索引流程 | `indexer.py`（獨立可執行）+ `Blur-main.py` 中的 `class IndexerWorker` |
| 跨進程 / Jump List | `Blur-main.py` 頂部 `--esm-cmd` 區塊（L1-30） |
| 自訂標題列 DLL | `core/win_titlebar.py` + `src_cpp/win_titlebar/` |

---

*本文件記錄狀態：Phase 1 + Phase 2 完工後（commit `9f84392`）。後續若新增模組或調整架構，請同步更新本文件。*

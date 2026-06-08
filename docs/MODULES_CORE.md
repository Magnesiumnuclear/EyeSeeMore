# MODULES_CORE.md — 8 個核心業務邏輯模組詳解

> 這8個模組是 Phase 1 + Phase 2 從 MainWindow 中重構拆離出來的核心邏輯。

## 🗺 模組地圖

```
core/
├─ 原有基礎層（infrastructure）
│  ├─ config_manager.py      ← 應用設定 I/O
│  ├─ paths.py               ← 路徑常數
│  ├─ win_titlebar.py        ← Win32 標題列
│  └─ search_orchestrator.py ← SearchWorker 生命週期
│
├─ Phase 1 − 資料存取與釘選 (1-A/1-B/1-C)
│  ├─ pin_manager.py         ← 圖片釘選
│  ├─ ocr_repository.py      ← OCR 框 CRUD
│  └─ collection_manager.py  ← 虛擬資料夾
│
├─ Phase 2 − UI 反饋與控制 (2-A/2-B/2-C)
│  ├─ search_history_manager.py    ← 搜尋歷史
│  ├─ eta_progress_controller.py   ← ETA 進度 + PID
│  └─ indexing_lifecycle.py        ← 索引掃描生命週期
│
├─ Phase 3 − 非阻塞模型加載 (3-A)
│  └─ model_provider.py            ← 模型加載與共享（解耦 IndexerWorker）
│
└─ 其他
   └─ image_action_manager.py ← 圖片右鍵選單
```

---

## 📋 模組列表

### 原有基礎層

#### `config_manager.py`

**職責：** 應用程式設定的唯一真理源，管理 `config.json` 的 I/O

| 方法 | 簽名 |
|------|------|
| `load()` | 讀取 config.json，進行舊版本遷移 |
| `get(key: str, default=None)` | 取值（支援深層路徑如 `ui_state.geometry`） |
| `set(key: str, value)` | 設值 |
| `merge(updates: dict)` | 深層合併 |
| `save()` | 寫回 config.json |
| `add_source_folder(path)` / `remove_source_folder(path)` | 細粒度操作 |

**訊號：** 無（純資料層）

**與 MainWindow 的關係：**
```python
# Blur-main.py: 最先建立
self.config = ConfigManager(config_path="config.json")
self.config.load()
# 後續所有需要設定的地方都從這裡取
```

---

#### `paths.py`

**職責：** 專案路徑常數集中地，避免各模組重複計算 `__file__`

**提供常數：**
```python
BASE_DIR          # 專案根目錄
MODELS_DIR        # models/ 路徑
THEMES_DIR        # themes/ 路徑
LANGUAGES_DIR     # languages/ 路徑
DB_PATH           # images.db 路徑
CONFIG_PATH       # config.json 路徑
```

**使用方式：**
```python
# ✅ 正確
from core.paths import DB_PATH
conn = sqlite3.connect(DB_PATH)

# ❌ 錯誤（別自己計算）
db_path = os.path.join(os.path.dirname(__file__), "..", "images.db")
```

---

#### `win_titlebar.py`

**職責：** 自訂標題列 DLL 橋接（無邊框視窗 + 自訂佈局）

| 方法 | 含義 |
|------|------|
| `install(hwnd, ...)` | 載入 DLL Hook，初始化 WndProc |
| `update_button_rects(rects)` | 通知按鈕座標（NC hit-test 用） |
| `uninstall(hwnd)` | 卸載 Hook |

**特點：**
- DLL 不存在時靜默降級為 no-op（graceful fallback）
- 必須配套 `core/window_state_manager.py` 用（Win32 整合）

---

#### `search_orchestrator.py`

**職責：** `SearchWorker` 線程生命週期管理

| 方法 | 含義 |
|------|------|
| `launch_search(query, fetch_k, ...)` | 啟動搜尋 Worker |
| `cancel_search()` | 取消現有搜尋 |
| `ensure_old_worker_retired()` | 安全退役舊 Worker |

**為什麼需要這個：**
- 防止舊 Worker 與新 Worker 競爭資源
- 遮蔽實作細節（Worker 如何管理）
- 統一解析搜尋參數（fetch_k / target_folder）

---

### Phase 1 − 資料存取與釘選

#### `pin_manager.py` (Phase 1-A)

**職責：** 圖片釘選邏輯：pinned 表 CRUD + 記憶體快取

| 方法 | 簽名 | 回傳 |
|------|------|------|
| `toggle(file_path)` | 切換釘選狀態 | `bool` (新狀態) |
| `get_pinned_paths()` | 取所有釘選路徑清單 | `list[str]` |
| `is_pinned(file_path)` | 檢查釘選否 | `bool` |
| `merge_pinned_to_top(items)` | 釘選項目置頂 + 保持排序 | `list` |

**訊號：** 無（純資料層）

**依賴注入方式（Callable Provider）：**
```python
# core/pin_manager.py
class PinManager:
    def __init__(self, data_store_provider: Callable):
        # 為什麼用 Callable？因為 data_store 會被 rebind
        # 用 lambda 永遠取最新參照
        self.get_data_store = data_store_provider

# MainWindow 注入時
self.pin_manager = PinManager(
    data_store_provider=lambda: self.engine.data_store
)
```

**為什麼這樣設計：** 見 [DESIGN_PATTERNS.md §3.2](./DESIGN_PATTERNS.md) 的「配套地雷修復」

---

#### `ocr_repository.py` (Phase 1-B)

**職責：** OCR 框資料的資料存取層（CRUD 操作 ocr_results 表）

| 方法 | 含義 |
|------|------|
| `get_by_path(file_path)` | 取某圖片的所有 OCR 框 |
| `upsert(file_path, lang, boxes, ...)` | 插入或更新 OCR 資料 |
| `delete_box(file_path, box_id)` | 刪除單一框 |
| `update_box_text(file_path, box_id, new_text)` | 編輯框文字 |

**內置 Helper：**
```python
def _boxes_match(box1, box2) -> bool:
    """帶 ±2px 容忍度的框比對"""
    # 用於 upsert 時判斷是否應新建還是覆蓋
```

**資料格式：**
```python
# ocr_results 表結構
{
    "file_id": int,
    "lang": "zh_TW",
    "ocr_text": "辨識出的文字",
    "ocr_data": {  # JSON
        "boxes": [
            {"text": "單字", "bbox": [x1, y1, x2, y2], "conf": 0.95},
            ...
        ]
    },
    "confidence": 0.92  # 平均信心度
}
```

---

#### `collection_manager.py` (Phase 1-C)

**職責：** 虛擬資料夾（collections 表）的 CRUD 與聯動

| 操作 | 方法 |
|------|------|
| **新增資料夾** | `add_collection(name, icon)` |
| **取資料夾清單** | `get_collections()` |
| **刪除資料夾** | `remove_collection(collection_id)` |
| **更新圖示** | `update_collection_icon(collection_id, icon)` |
| **加入圖片** | `add_to_virtual_folder(collection_id, file_paths)` |
| **取資料夾內容** | `get_virtual_folder_images(collection_id)` |

**特點：**
- icon 欄位**冪等遷移**（`_ensure_icon_column`）：若 collections 表尚無 icon 欄位則自動補建；使用 class-level `_icon_column_ensured` 旗標確保 `PRAGMA table_info` 只執行一次，後續所有呼叫零額外 SQL（Phase 3-E 優化）
- 與 `data_store` **by-reference 共享**（不復制，直接操作 list）→ `get_virtual_folder_images` 掃記憶體即可，O(N) 但無 I/O

**schema：**
```
collections:
  - id (PK)
  - name (UNIQUE)
  - icon (可選)
  - created_at

collection_items:
  - collection_id (FK, ON DELETE CASCADE)
  - file_path (FK)
```

---

### Phase 2 − UI 反饋與控制

#### `search_history_manager.py` (Phase 2-A)

**職責：** 搜尋歷史（`search_history.json`）的 I/O 與 MRU 行為

| 方法 | 含義 |
|------|------|
| `add(query_string)` | 新增搜尋歷史（自動 MRU 升序） |
| `get_all()` | 取所有歷史 |
| `clear()` | 清空歷史 |

**特點：**
- `MAX_ITEMS = 10` 自動截斷（保留最近 10 筆）
- MRU (Most Recently Used)：重複搜尋時自動把它移到最前面
- JSON 格式，人工可讀

**檔案樣例：**
```json
[
  {"query": "貓咪", "timestamp": 1234567890},
  {"query": "風景", "timestamp": 1234567880}
]
```

---

#### `eta_progress_controller.py` (Phase 2-B)

**職責：** 掃描進度與 ETA 展示控制（4 種模式 + PID 平滑器）

| 訊號 | 參數 |
|------|------|
| `status_text_changed(str)` | 狀態文字（如 "掃描中: 234/1000 (ETA: 2:30)"） |
| `progress_updated(int)` | 進度百分比 (0-100) |

**4 種顯示模式：**

| Mode | 含義 | 何時用 |
|------|------|--------|
| **0** | 進度條 + 百分比 | 首次啟動、進度不穩定 |
| **1** | 進度條 + 秒數倒計時 | 掃描中段、預估穩定 |
| **2** | 進度條 + 秒數**平滑**倒計時 | 掃描接近完成、需光滑 UX |
| **3** | 完成狀態（隱藏進度條） | 掃描結束 |

**PID 平滑器（Mode 2）：**
- 模擬物理加速度：ETA 不會突然跳動
- 基於掃描速率的「假時間」（pseudo-wall-time）
- 讓進度條看起來自然逐緩

**初始化：**
```python
self.eta_ctrl = EtaProgressController(mode=0)
self.eta_ctrl.status_text_changed.connect(self.status_bar.setText)
self.eta_ctrl.progress_updated.connect(self.progress_bar.setValue)
```

---

#### `indexing_lifecycle.py` (Phase 2-C)

**職責：** 索引掃描的完整生命週期管理（暫停/繼續/取消 + DB 雙緩衝）

| 訊號 | 含義 |
|------|------|
| `scanning_started()` | 掃描開始 |
| `scanning_paused()` / `scanning_resumed()` | 暫停/恢復 |
| `scanning_cancelled()` | 取消 |
| `scanning_finished()` | 掃描完成 |
| `gallery_refresh_requested()` | UI 更新：重繪畫廊 |
| `sidebar_refresh_requested()` | UI 更新：重繪側邊欄 |

**內部訊號（跨執行緒橋接）：**
| 訊號 | 含義 |
|------|------|
| `_db_reloaded` | 背景 DB 重載完（自動連 `on_db_reloaded`） |

**雙緩衝邏輯：**
```
IndexerWorker 掃描結束
    ↓
background thread: engine.load_data_from_db()  (耗時 I/O)
    ↓
emit _db_reloaded  (跨執行緒訊號)
    ↓
主執行緒: on_db_reloaded()
    ↓
emit gallery_refresh_requested  (UI 層接收)
```

**為什麼需要雙緩衝：** 避免主執行緒等待 DB 重載，UI 卡頓

---

### 其他模組

#### `image_action_manager.py`

**職責：** 圖片右鍵選單動作統一處理（開啟/複製/重新命名/屬性/在檔案總管中顯示）

**工廠方法：**
```python
def create_context_menu(...) -> QMenu:
    """根據選中檔案構建右鍵菜單"""
    menu = QMenu()
    menu.addAction("開啟", lambda: self.open_file(...))
    menu.addAction("複製路徑", ...)
    ...
    return menu
```

---

## 依賴圖

```
config_manager.py  ← 所有模組都用（設定集中地）
    ↓
paths.py  ← 所有模組都用（路徑集中地）
    ↓
pin_manager.py ←→ collection_manager.py ←→ ocr_repository.py
    ↓ (共同依賴：data_store / db_path)
      search_orchestrator.py (SearchWorker 管理)
            ↓
      search_history_manager.py (記錄搜尋)
            ↓
      eta_progress_controller.py (進度展示)
      indexing_lifecycle.py (掃描生命週期)
            ↓ (都發訊號給 UI)
      ui/ 層（MainWindow / GalleryViewController）
```

---

## 常見集成錯誤

### ❌ 錯誤 1：直接傳 engine.data_store

```python
# 錯誤（Phase 1-A 已踩過）
self.pin_mgr = PinManager(data_store=engine.data_store)
# 問題：engine 重載時會 rebind data_store，pin_mgr 持舊參照
```

✅ **正確做法：** 見上述 `pin_manager.py` 的 Callable Provider 模式

---

### ❌ 錯誤 2：在 core/ 層直接修改 UI widget

```python
# 錯誤
class EtaProgressController:
    def update_progress(self, ...):
        self.progress_bar.setValue(...)  # ❌ core/ 不應持有 widget
---

## Phase 3 — 非阻塞模型加載

### `model_provider.py` (Phase 3-A)

**職責：** 獨立管理 AI 模型的加載與共享，解耦 IndexerWorker 與模型依賴

**問題背景：**
- 舊架構：IndexerWorker 卡在 `while not engine.is_ready: sleep(1)` 阻塞迴圈
- 結果：新檔案索引被延遲，用戶感受冷啟動慢

**解決方案：** ModelProvider（QObject）
- 在**背景執行緒**非阻塞加載 ONNX CLIP 模型 + Tokenizer
- 提供 `models_loaded` / `models_load_failed` 訊號
- 支援 OCR 引擎的 Lazy Load（首次使用時才加載）

**核心API：**

| 方法/屬性 | 簽名 | 備註 |
|----------|------|------|
| `load_models_async()` | 無返回值 | 立刻啟動背景加載，不阻塞 |
| `is_ready` | bool | 檢查模型是否加載完成 |
| `is_loading` | bool | 檢查是否正在加載中 |
| `models_loaded` | Signal | 加載成功發射 |
| `models_load_failed` | Signal(str) | 加載失敗發射錯誤訊息 |
| `get_ocr_engine(lang)` | ONNXOCR \| None | Lazy Load OCR 引擎 |
| `wait_until_ready(timeout)` | bool | (可選) 阻塞式等待 |

**使用範例：**

```python
# ImageSearchEngine.__init__
self.model_provider = ModelProvider(self.config, parent=None)

# 立刻啟動非阻塞加載
self.engine.load_ai_models()  # ← 改為: model_provider.load_models_async()

# MainWindow 監聽訊號
self.engine.model_provider.models_loaded.connect(self._on_models_loaded)
self.engine.model_provider.models_load_failed.connect(self._on_models_load_failed)
```

**鏈式效果：**

```
時間線（Phase 3-A + 3-B 改進後）：
t=0ms     : MainWindow.__init__
t+150ms   : load_engine() 後台執行緒啟動
t+100ms   : ✅ random_data_ready 發射 → 圖片立刻填入 Model
            ✅ 畫廊圖片在 UI 顯示（不等模型！）[Phase 3-B]
            ✅ IndexerWorker 啟動 → 掃描新檔案（不再被阻擋）[Phase 3-A]
t+500ms   : ⚙️ model_provider 在背景加載 ONNX 模型
t+8000ms  : ✅ models_loaded 發射 → _on_models_loaded()
            ✅ 只刷新 sidebar/collections（不重置畫廊）[Phase 3-B]
            ✅ IndexerWorker._run_ai_processing 開始執行
```

**Lazy Load OCR 機制：**

```python
# indexer.py: run_ai_processing()
def ensure_ocr_engine(lang: str):
    """需要時才加載"""
    if lang not in ocr_engines:
        ocr_engines[lang] = ONNXOCR(lang=lang, use_gpu=...)
    return lang in ocr_engines

# 迴圈中使用
for target_lang in required_langs:
    if ensure_ocr_engine(target_lang):
        ocr_result = ocr_engines[target_lang].ocr(...)
```

**訊號：**

| 訊號 | 參數 | 含義 |
|------|------|------|
| `models_loaded()` | — | 模型加載成功 |
| `models_load_failed(str)` | 錯誤訊息 | 模型加載失敗 |

**設計決策：**

1. **QObject 母類**：以支援 pyqtSignal；背景執行緒發射訊號，Qt 自動切到主執行緒
2. **Lazy Load OCR**：減少冷啟動時間（第一個圖片需要 OCR 時才加載該語言引擎）
3. **Callable Provider**（未來可選）：若 ModelProvider 支援熱切換模型，可改為 lambda 注入

**與其他模組的關係：**

```
MainWindow
  ├─ engine = ImageSearchEngine
  │   └─ model_provider = ModelProvider ← 背景加載模型
  │       └─ models_loaded.connect → _on_models_loaded()
  └─ indexer_worker = IndexerWorker
      └─ 改為：不等待 engine.is_ready，改為 Lazy Load 需要的模型
```

---

## Phase 3-B — 畫廊提早渲染修復

**問題：** Phase 3-A 完成後，畫廊圖片仍須等待模型加載（t~8000ms）才出現

**根本原因追蹤：**

```
random_data_ready.emit(all_images)   ← t~100ms，圖片填入 Model ✅
  ↓
set_base_results() → model.set_search_results()
  ↓ 圖片應顯示於 UI

...（模型加載中）...

_on_models_loaded()                  ← t~8000ms
  └─ _apply_folder_filter("ALL")
       └─ engine.get_all_images_sorted()
           └─ set_base_results()
               └─ model.beginResetModel()  ← 重置 Model，覆蓋初始渲染！
```

**修復（Blur-main.py `_on_models_loaded`）：**

```python
# 只在非 "ALL" 的啟動資料夾時才需要套用資料夾過濾
# "ALL" 的情況已由 random_data_ready 訊號（t~100ms）的 set_base_results() 處理
if self.current_folder_path and self.current_folder_path != "ALL":
    self._apply_folder_filter(self.current_folder_path)
```

**效果：**

| 情況 | Phase 3-A | Phase 3-A + 3-B |
|------|-----------|-----------------|
| 啟動資料夾 = ALL | 圖片 t~8000ms 出現 | 圖片 **t~100ms** 出現 ✅ |
| 啟動資料夾 = 指定資料夾 | 圖片 t~8000ms 出現 | 圖片 t~8000ms 出現（維持功能正確） |

---

## 相關詳細文檔

- **依賴注入陷阱** → [DESIGN_PATTERNS.md §3.2](./DESIGN_PATTERNS.md#32-依賴注入三大策略)
- **訊號規範** → [DESIGN_PATTERNS.md §3.3](./DESIGN_PATTERNS.md#33-pyqt-訊號-signal-解耦規範)
- **各層職責邊界** → [LAYERS.md](./LAYERS.md)

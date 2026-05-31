# MODULES_UI.md — UI 控制器與 widget 層詳解

> 這層負責視覺展示、事件處理、訊號連接，包含 2 個主控制器、3 個原子 widget 與 8 個設定頁面。

## 📐 層次結構

```
ui/
├─ 主布局與管理
│  ├─ main_window_ui.py        ← MainWindow 元件佈局（純 UI）
│  └─ action_handler.py        ← 鍵盤滑鼠事件分發
│
├─ 控制器（Phase 2 新增）
│  ├─ gallery_view_controller.py   (Phase 2-D) ← 畫廊視圖邏輯
│  └─ window_state_manager.py      (Phase 2-E) ← 視窗狀態 + Win32
│
├─ 原有管理器
│  ├─ theme_manager.py         ← 主題 I/O 與套用
│  ├─ navigation_manager.py    ← 導航回退棧
│  └─ inspector_panel.py       ← 右側 3 分頁面板
│
├─ widgets/ 原子 widget
│  ├─ base.py                  ← BaseToggleWidget 基類
│  ├─ drag_list.py             ← 半透明拖曳列表
│  └─ search_capsule.py        ← 頂部搜尋膠囊 + 歷史下拉
│
└─ settings_pages/ 設定分頁（8 頁）
   ├─ folders_page.py          ← 📁 資料夾管理
   ├─ ai_engine_page.py        ← 🧠 AI 引擎設定
   ├─ appearance_page.py       ← 🖥️ 介面與顯示
   ├─ hotkeys_page.py          ← ⌨️ 快捷鍵設定
   ├─ performance_page.py      ← ⚡ 效能調整
   ├─ auto_tasks_page.py       ← 🕒 自動任務
   ├─ language_page.py         ← 🌍 語言選擇
   └─ about_page.py            ← ℹ️ 關於與說明
```

---

## 主布局與事件處理

### `main_window_ui.py`

**職責：** 純 UI 元件佈局，負責在 MainWindow 建立所有視覺元件

| 組件 | 描述 |
|------|------|
| **頂部搜尋膠囊** | SearchCapsule widget |
| **左側導航** | 資料夾樹、集合清單、釘選清單 |
| **中心畫廊** | QListView（縮圖網格） + 自繪 ImageDelegate |
| **右側檢查器** | 3 分頁：過濾 / 屬性 / OCR 結果 |
| **Splitter** | 可調整分割線 |

**關鍵方法：**
```python
class Ui_MainWindow:
    def setup_ui(self, MainWindow):
        """在提供的 MainWindow 上建立所有視覺元件"""
        # 前提條件：MainWindow 需有 self.config 與 self.history_mgr 屬性
        MainWindow.setWindowTitle("EyeSeeMore")
        # ... 建立所有 widget
```

**使用範例：**
```python
# Blur-main.py: MainWindow.__init__
self.config = ConfigManager(...)
self.history_mgr = SearchHistoryManager(...)
self.ui = Ui_MainWindow()
self.ui.setup_ui(self)  # ✅ 此時 self.config 和 self.history_mgr 已存在
```

---

### `action_handler.py`

**職責：** 統一分發鍵盤與滑鼠事件，轉換為訊號

| 事件 | 轉換訊號 |
|------|---------|
| Escape | `requestExitPreview()` |
| Shift | `requestToggleOCR()` |
| WASD / 方向鍵 | `requestNavigate(direction)` |
| Space | `requestPlayPauseVideo()` |
| Ctrl+C | `requestCopyFilePath()` |
| Alt←/→ | `requestBackNavigation()` / `requestForwardNavigation()` |
| 滑鼠中鍵 | `requestShowContext()` |

**設計意圖：** 將複雜的按鍵邏輯統一集中，便於維護和修改快捷鍵

---

## 控制器層（Phase 2）

### `gallery_view_controller.py` (Phase 2-D)

**職責：** 畫廊視圖（搜尋結果清單）的邏輯與狀態管理

**訊號：**
| 訊號 | 參數 | 用途 |
|------|------|------|
| `layout_changed()` | — | 佈局變化（通知重繪） |
| `selection_changed(list)` | 選中檔案路徑清單 | 更新右側面板 |
| `preview_requested(str)` | 檔案路徑 | 開啟預覽 |
| `empty_state_changed(bool)` | 是否為空 | 顯示/隱藏「無搜尋結果」提示 |

**搜尋結果儲存：**
```python
class GalleryViewController:
    def __init__(self, list_view: QListView, model: QStandardItemModel):
        self.list_view = list_view
        self.model = model

    def display_results(self, items: list[ImageItem]):
        """顯示搜尋結果"""
        self.model.clear()
        for item in items:
            self.model.appendRow(...)
```

**3 層過濾 + 5 種排序：**

過濾層：
1. **時間範圍過濾** —— 日期區間選擇
2. **圖片比例過濾** —— 橫/豎/正方形
3. **結果數量限制** —— 只顯示前 N 項

排序模式：
1. 搜尋相關度（高→低）
2. 修改時間（新→舊）
3. 修改時間（舊→新）
4. 檔案名（A→Z 或反序）
5. **自動置頂釘選** ← 無論哪種排序都保留

**視圖模式：**
- Grid 佈局（縮圖網格，動態均分列寬）
- List 佈局（列表視圖）
- 切換時自動保持滾動位置

**空狀態診斷：**
```python
def check_empty_state(self):
    """判斷是否應顯示「無搜尋結果」提示"""
    if not self.model.rowCount():
        self.empty_state_changed.emit(True)
        # UI 層可在圖片區域顯示提示文字
```

---

### `window_state_manager.py` (Phase 2-E)

**職責：** 視窗狀態與 Win32 整合（TOPMOST 釘選、最大化/還原、NC 按鈕座標）

| 操作 | 方法 |
|------|------|
| **釘選視窗置頂** | `set_topmost(enabled: bool)` |
| **最大化/還原** | `toggle_maximize()` |
| **按鈕座標通知** | `update_button_rects(btn_rects)` |
| **按鈕狀態同步** | `sync_max_button_state()` |
| **幾何記憶** | `save_geometry()` / `restore_geometry()` |

**訊號：** 無（直接操作注入的 widget）

**特點：**
- 不發訊號，直接操作 widget（因為 caller 已持有 widget）
- Win32 層面切換 TOPMOST（`SetWindowPos`），不用 `setWindowFlag`
- 按鈕座標必須 **乘以 DPR**（設備像素比）

**初始化範例：**
```python
# Blur-main.py
self.window_mgr = WindowStateManager(
    main_window=self,
    config=self.config,
    titlebar_bridge=self.titlebar
)
# 監聽視窗大小變化
self.resizeEvent = lambda e: self.window_mgr.on_resize_event(e)
```

**Win32 地雷：**
```python
# ❌ 錯誤（會毀掉自訂標題列）
self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

# ✅ 正確
self.window_mgr.set_topmost(True)  # 內部使用 SetWindowPos
```

---

## 原有管理器

### `theme_manager.py`

**職責：** 主題讀取與套用

| 方法 | 含義 |
|------|------|
| `get_available_themes()` | 掃描 `themes/` 並列舉所有主題 |
| `apply_theme(theme_name)` | 套用主題樣式表 |
| `get_current_theme()` | 取現用主題名稱 |

**主題格式：**
```
themes/
├─ dark.json          ← 顏色變數定義
├─ light.json
└─ base_style.qss     ← QSS 基礎樣式
```

dark.json 例：
```json
{
  "primary": "#1e1e1e",
  "text": "#ffffff",
  "accent": "#0d7377"
}
```

base_style.qss：
```qss
QMainWindow {
    background-color: $primary;
    color: $text;
}
```

---

### `navigation_manager.py`

**職責：** 「上一頁」/「下一頁」導航堆疊

**資料結構：**
```python
class NavigationManager:
    back_stack: list = [...]        # 導航歷史
    forward_stack: list = [...]     # 前進歷史
    pending_scroll_pos = None       # 待恢復的滾動位置
```

**操作：**
```python
nav.push_state(current_state)       # 記錄當前狀態
nav.go_back() -> state              # 回退 + 記錄 forward
nav.go_forward() -> state           # 前進
nav.get_pending_scroll_pos() -> int # 恢復滾動位置
```

**設計：** 純資料結構 + 回呼函式，不使用訊號

---

### `inspector_panel.py`

**職責：** 右側 3 分頁面板（搜尋過濾 / 屬性檢視 / OCR 結果）

| 分頁 | 組件 |
|------|------|
| **搜尋過濾** | 日期區間日曆、比例勾選、結果限制滑桿 |
| **屬性檢視** | 圖片尺寸、檔案大小、修改時間等 |
| **OCR 結果** | OCR 文字顯示、摺疊區塊 |

**包含的自訂 widget：**
- `CollapsibleSection` — 可摺疊區塊（點標題展開/收起）
- `RangeCalendarWidget` — 日期區間日曆

---

## 原子 Widget (`ui/widgets/`)

### `base.py` — BaseToggleWidget

**職責：** 所有自訂 widget 的基類

```python
class BaseToggleWidget(QWidget):
    errorOccurred = pyqtSignal(str)  # 全域錯誤訊號

    def __init__(self):
        super().__init__()
        # 統一的錯誤協議
```

**使用場景：** 任何自訂 widget 都應繼承此類，便於統一錯誤處理

---

### `drag_list.py` — TransparentDragListWidget

**職責：** 拖曳時產生半透明鬼影的列表

**特點：**
- 拖曳中顯示半透明預覽圖（鬼影）
- 支援 drop-on-drop 重新排序
- 視覺反饋流暢

**使用範例：** 資料夾順序調整、集合成員編排

---

### `search_capsule.py` — SearchCapsule

**職責：** 頂部搜尋膠囊（輸入框 + 模式切換 + 歷史下拉）

**訊號：**
| 訊號 | 參數 | 含義 |
|------|------|------|
| `searchRequested(dict)` | `{"query": "...", "mode": "text/visual"}` | 搜尋請求 |
| `modeChanged(str)` | "text" 或 "visual" | 切換搜尋模式 |

**子組件：**
```python
self.input_field = QLineEdit()
self.mode_button = QPushButton()  # 文字/圖片模式切換
self.history_button = QPushButton()  # 歷史下拉
self.history_popup = HistoryDropdown()  # 下拉選單
```

**狀態管理：**
- 輸入框焦點管理
- 歷史清單 MRU 排序
- 模式狀態持久化（config）

---

## 設定對話框分頁 (`ui/settings_pages/`)

### 統一設計

所有設定頁面都透過 `ctx: dict` 注入依賴：

```python
ctx = {
    "config": config_manager,
    "engine": image_search_engine,
    "translator": translator,
    "theme_manager": theme_manager,
    "hub": SettingsDialogHub(...),  # 跨頁面回呼
}

# 各頁面初始化
folders_page = FoldersPage(ctx)
ai_page = AiEnginePage(ctx)
```

**禁止：** 任何頁面**都不能**持有 `main_window` 參照

---

### 各頁面簡述

| 頁面 | 功能 |
|------|------|
| **folders_page.py** | 新增/移除資料夾、調整掃描順序、更改資料夾圖示 |
| **ai_engine_page.py** | CLIP 模型切換、OCR 語言包安裝/移除、模型加載進度 |
| **appearance_page.py** | 主題選擇、啟動資料夾、縮圖大小調整滑桿 |
| **hotkeys_page.py** | 快捷鍵綁定表、WASD 導航、Shift-OCR 觸發 |
| **performance_page.py** | 縮圖快取大小、背景索引執行緒數、記憶體限制 |
| **auto_tasks_page.py** | OCR 自動任務排程、啟動掃描行為 |
| **language_page.py** | 語言清單（動態掃描 `languages/*.json`） |
| **about_page.py** | 版本號、GitHub 連結、技術致敬 |

---

## 訊號流向圖

```
SearchCapsule.searchRequested(query)
    ↓
MainWindow._on_search_requested(query)
    ↓
SearchOrchestrator.launch_search(query)  [core/]
    ↓
SearchWorker (QThread)
    ↓
emit results
    ↓
GalleryViewController.display_results(results)
    ↓
emit selection_changed, layout_changed
    ↓
MainWindow 連接的 slots 更新 inspector_panel
```

---

## 相關詳細文檔

- **層責邊界** → [LAYERS.md](./LAYERS.md#ui--層--視圖控制器與元件)
- **訊號設計規範** → [DESIGN_PATTERNS.md §3.3](./DESIGN_PATTERNS.md)
- **設定頁面注入模式** → [DESIGN_PATTERNS.md §3.2](./DESIGN_PATTERNS.md#32-依賴注入三大策略)

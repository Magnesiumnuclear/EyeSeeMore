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
│  ├─ elided_label.py          ← 自動省略文字的 QLabel
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
| **麵包屑標題** | ElidedLabel（寬度不足時省略，tooltip 顯示完整路徑） |
| **狀態列文字** | ElidedLabel（同上） |
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
| `layout_changed()` | — | `adjust_layout` 計算完成，供外部觀察者使用 |
| `status_text_changed(str)` | 狀態文字 | 過濾結果統計、搜尋完成訊息等 |
| `status_highlight_changed(str)` | `'alert'` 或 `'none'` | 狀態列高亮等級 |
| `search_input_cleared()` | — | 通知搜尋框清空（time-range 搜尋完成後） |

**建構子：**
```python
gallery_ctrl = GalleryViewController(
    list_view=mw.list_view, model=mw.model, delegate=mw.delegate,
    inspector_panel=mw.inspector_panel, config=mw.config,
    empty_state_overlay=mw._empty_state_overlay, nav=mw.nav,
    initial_view_mode="large",   # xl / large / medium
    parent=mw,
)
```

**核心方法：**
```python
def set_base_results(self, results: list) -> None:
    """搜尋/載入資料的統一入口：儲存原始結果，自動套用過濾器並更新 UI"""

def apply_current_filters_and_show(self, test_mode: bool = False) -> int:
    """套用時間 / 長寬比 / Limit 過濾器到 last_search_results 並丟給 Model。
    test_mode=True 時只回傳筆數，不更新 UI（防呆預覽用）"""
```

**3 層過濾 + 5 種排序：**

過濾層（按順序套用）：
1. **時間範圍過濾** —— 起訖 mtime 區間
2. **圖片比例過濾** —— 橫圖 / 直圖 / 正方形（容差 5%）
3. **Limit 截斷** —— 只顯示前 N 項（改變 N 時直接呼叫 `apply_current_filters_and_show`，**不重跑 FAISS**）

排序模式（皆以 `is_pinned` 為第一優先鍵，釘選永遠置頂）：
1. 搜尋相關度（score 高→低）
2. 日期（mtime 新→舊或舊→新）
3. 名稱（filename A→Z 或反序）
4. 類型（副檔名）
5. 大小（檔案大小）

> **排序實作細節（Phase 3-E 改進）：** `sort_items` 改用 `layoutAboutToBeChanged` / `layoutChanged`
> 取代 `beginResetModel` / `endResetModel`，排序時不再觸發視圖全量重設，
> 避免排序後 scroll 位置跳頂的二次 reset。

**視圖模式：**
| 模式 | 卡片寬 × 高 | 縮圖高 |
|------|------------|--------|
| `xl` | 320 × 380 | 240px |
| `large`（預設） | 240 × 290 | 160px |
| `medium` | 180 × 230 | 120px |

**佈局計算（`adjust_layout`）：**
- 動態均分演算法：`space = 剩餘寬 / (列數 + 1)`，四周邊距與間距相等
- **Phase 3-E 優化**：計算結果以 `(space, grid_w, grid_h)` 為 key 快取（`_last_layout`），相同結果直接略過所有 setter，視窗微幅縮放不再觸發無效 relayout

**空狀態診斷（`_update_search_diagnostics`）：**
- 過濾後筆數為 0 時自動顯示原因（無結果 / 時間過濾截斷 / 長寬比截斷 / Limit 截斷）

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
| **搜尋過濾** | 日期區間日曆、比例勾選、結果限制下拉 |
| **屬性檢視** | 圖片尺寸、檔案大小、修改時間等 |
| **OCR 結果** | OCR 文字顯示、摺疊區塊 |

**訊號：**
| 訊號 | 參數 | 用途 |
|------|------|------|
| `weights_changed(dict)` | `WeightConfig` 字典 | 搜尋權重或模式改變時發射，觸發重新搜尋 |

> **重要區別（Phase 3-E）：**
> `on_limit_changed`（切換顯示數量）**不發射 `weights_changed`**，
> 直接呼叫 `main_window.apply_current_filters_and_show()`，
> 只對現有結果做截斷，**不重跑 FAISS 向量搜尋**。
> 只有真正影響搜尋分數的操作（權重滑桿、計算模式、閾值）才發射 `weights_changed`。

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

### `elided_label.py` — ElidedLabel

**職責：** 自動省略文字的 QLabel，用於 TopBar 的麵包屑與狀態列

**核心設計：**
- 覆寫 `minimumSizeHint()` 讓水平最小寬回傳 0，使佈局可在空間不足時將其縮至任意寬度，**不再撐大視窗最小寬度**
- 保留預設 `Preferred` SizePolicy，有多餘空間時仍索取完整文字寬度
- `resizeEvent` 時自動重算省略文字；省略時 ToolTip 顯示完整內容
- 提供 `fullText()` 取得未省略原始文字（`_nav_snapshot` 和 toast 還原用）

```python
class ElidedLabel(QLabel):
    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def setText(self, text: str) -> None:
        self._full_text = text
        self._refresh()           # 更新省略顯示

    def fullText(self) -> str:
        return self._full_text    # 未省略原始文字
```

**使用位置：**
- `main_window_ui.py` — `breadcrumb_lbl`（麵包屑）與 `status`（狀態列）
- 讀取文字時需用 `fullText()` 而非 `.text()`（`.text()` 回傳省略後的顯示值）

---

### `search_capsule.py` — SearchCapsule

**職責：** 頂部搜尋膠囊（輸入框 + OCR 切換 + 歷史下拉）

**訊號：**
| 訊號 | 參數 | 含義 |
|------|------|------|
| `searchRequested(dict)` | `{"query": "...", "use_ocr": bool}` | 搜尋請求 |
| `modeChanged(str)` | "ocr_on" 或 "ocr_off" | OCR 開關切換 |

**子組件：**
```python
self.input = QLineEdit()            # 搜尋框
self.btn_ocr_toggle = QPushButton() # OCR 開關按鈕 [T]
self._history_list: QListWidget     # 歷史下拉（懶初始化，掛在 top-level window）
```

**尺寸限制：**
- `setMinimumWidth(160)` — 最小可縮至 160px（不撐大視窗）
- `setMaximumWidth(550)` — 避免在超大視窗佔用過多空間

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
emit results_ready
    ↓
GalleryViewController.set_base_results(results)
  ├─ apply_current_filters_and_show()   → model.set_search_results(filtered)
  └─ apply_gallery_sort()               → model.sort_items(key_func)
                                            └─ layoutAboutToBeChanged / layoutChanged
    ↓
emit status_text_changed, layout_changed
    ↓
MainWindow 連接的 slots 更新狀態列

── Limit 切換（不重搜）──────────────────────────────────────────
InspectorPanel.on_limit_changed()
    ↓
MainWindow.apply_current_filters_and_show()   ← 直接截斷現有結果
    ↓
GalleryViewController.apply_current_filters_and_show()
```

---

## 相關詳細文檔

- **層責邊界** → [LAYERS.md](./LAYERS.md#ui--層--視圖控制器與元件)
- **訊號設計規範** → [DESIGN_PATTERNS.md §3.3](./DESIGN_PATTERNS.md)
- **設定頁面注入模式** → [DESIGN_PATTERNS.md §3.2](./DESIGN_PATTERNS.md#32-依賴注入三大策略)

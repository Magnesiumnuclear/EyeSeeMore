# LAYERS.md — 各層設計原則與職責邊界

## 快速決策樹

```
我要寫新代碼：

「這是純數據/算法邏輯嗎？」
├─ 是 → core/ 層
│   ├─ 資料庫 CRUD → ocr_repository.py / collection_manager.py
│   ├─ 業務邏輯 → 原有模組或新建模組
│   └─ ⚠️ 記得只發訊號，不直接寫 UI
│
├─「這是 UI 元件或事件處理嗎？」
│ ├─ 是小原子 widget → ui/widgets/
│ ├─ 是視圖控制器 → ui/
│ ├─ 是設定頁面 → ui/settings_pages/
│ └─ ⚠️ 複雜邏輯委派給 core/
│
└─「這是跨層工具嗎？」
  └─ 是 → utils/
     └─ ⚠️ 不能依賴 PyQt 或 core/
```

---

## `core/` 層 — 零 UI 依賴的業務邏輯

### 設計原則

| 項目 | 規則 |
|------|------|
| **可依賴的庫** | `PyQt6.QtCore`、`sqlite3`、`numpy`、`onnxruntime`、`faiss`、標準庫 |
| **禁止依賴** | `PyQt6.QtWidgets`、`PyQt6.QtGui`（除了顏色/字體常數） |
| **QObject 繼承** | ✅ 可以（為了使用 `pyqtSignal`），但**只發訊號，不持有 QWidget** |
| **外部可調用** | 其他 core/ 模組、ui/ 層、background workers |
| **UI 更新方式** | ✅ `self.signal.emit(data)` / ❌ `widget.setText(...)` |

### 典型列舉

```python
# ✅ 可以做的事
class PinManager(QObject):
    pin_toggled = pyqtSignal(str, bool)  # 訊號發射

    def toggle_pin(self, file_path: str) -> bool:
        result = self.data_store.toggle(file_path)
        self.pin_toggled.emit(file_path, result)  # UI 更新透過訊號
        return result

# ❌ 禁止做的事
class PinManager:
    def toggle_pin(self, file_path: str) -> bool:
        self.main_window.status_bar.setText(...)  # ❌ 不能直接寫 UI
        self.ui_model.setData(...)  # ❌ 不能操作 UI 物件
```

### 常見模組分類

| 子分類 | 例子 | 新增時命名 |
|--------|------|----------|
| **資料存取層 (Data Access)** | `ocr_repository.py`, `collection_manager.py` | `*_repository.py` / `*_manager.py` |
| **業務邏輯層 (Domain Logic)** | `pin_manager.py`, `search_history_manager.py` | `*_service.py` / `*_handler.py` |
| **控制器層 (Core QObject)** | `eta_progress_controller.py`, `indexing_lifecycle.py` | `*_controller.py` |
| **基礎設施** | `config_manager.py`, `paths.py`, `win_titlebar.py` | `*_manager.py` / `*_bridge.py` |

---

## `ui/` 層 — 視圖控制器與元件

### 設計原則

| 項目 | 規則 |
|------|------|
| **可依賴** | 所有 PyQt、`core/` 層、`utils/` |
| **持有 QWidget** | ✅ **必須可以**（list_view / model / delegate），這是 ViewController 的合理設計 |
| **業務邏輯** | ❌ 應委派給 `core/`；ui/ 只做「顯示」和「事件轉發」 |
| **訊號連接** | ✅ 在此層理清信號接線，形成 UI 反饋迴路 |
| **子模組持有 MainWindow** | ❌ settings_pages 絕對不能持有 main_window 參照 |

### ViewController 的合理設計

```python
# ✅ 這樣是對的：ViewController 直接持有註入的 QWidget
class GalleryViewController(QObject):
    def __init__(self, list_view: QListView, model: QStandardItemModel):
        self.list_view = list_view  # ✅ 持有是合理的
        self.model = model           # ✅ 持有是合理的
        self.list_view.setModel(self.model)
        self.list_view.itemClicked.connect(self._on_item_clicked)

    def refresh_layout(self):
        self.model.clear()
        self.model.appendRow(...)  # ✅ 直接操作 model

# ❌ 這樣是錯的：邏輯應在 core/ 裡，ui/ 只連訊號
class GalleryViewController(QObject):
    def __init__(self, list_view: QListView, ...):
        ...
        for file_path in self.engine.data_store:  # ❌ 不應在 ui/ 寫業務邏輯
            if self.too_old(file_path):  # ❌ 應該在 core/ 層過濾
                continue
```

### `ui/widgets/` — 原子 widget 的隔離

```python
# ✅ 原子 widget 無狀態，只暴露訊號
class SearchCapsule(QWidget):
    searchRequested = pyqtSignal(dict)  # 對外發訊號

    def __init__(self):
        super().__init__()
        # 不知道也不關心誰在聽我的訊號

    def on_search_button_clicked(self):
        self.searchRequested.emit({'query': self.input.text()})

# ❌ 錯：原子 widget 不應持有 MainWindow 狀態
class SearchCapsule(QWidget):
    def __init__(self, main_window):  # ❌ 不應注入 main_window
        self.main_window = main_window

    def on_search_button_clicked(self):
        self.main_window.gallery_view.refresh()  # ❌ 應該發訊號，讓上層連接
```

### `ui/settings_pages/` — 注入 ctx 字典，斷絕 MainWindow 參照

```python
# ✅ 透過 ctx 字典注入依賴，不持有 main_window
class FoldersPage(QWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.config = ctx["config"]        # 從字典取依賴
        self.engine = ctx["engine"]
        self.hub = ctx["hub"]              # 跨頁面回呼
        # main_window 不在 ctx 裡，刻意排除

# ❌ 錯：直接持有 main_window
class FoldersPage(QWidget):
    def __init__(self, main_window):
        self.main_window = main_window  # ❌ 導致耦合
```

---

## `ui/widgets/` 層 — 可複用原子 widget

### 設計原則

| 項目 | 規則 |
|------|------|
| **職責** | 只做一件事（搜尋膠囊、拖曳列表、可摺疊區塊等） |
| **依賴注入** | 需要的資料透過函式參數或初始化參數注入 |
| **持有狀態** | ✅ 可以，但只涉及**該 widget 自身的 UI 狀態** |
| **MainWindow 狀態** | ❌ 不能持有或依賴 MainWindow 內部狀態 |
| **通信方式** | 全部透過 `pyqtSignal`；不直接呼叫上層方法 |

### 反面教材

```python
# ❌ 錯：持有 MainWindow，造成 widget 複用困難
class MyWidget(QWidget):
    def __init__(self, main_window):
        self.main_window = main_window

    def on_button_clicked(self):
        self.main_window.refresh()  # 綁死了

# ✅ 對：發訊號，讓使用方決定如何反應
class MyWidget(QWidget):
    button_clicked = pyqtSignal()

    def on_button_clicked(self):
        self.button_clicked.emit()

# 上層在 MainWindow：
# self.my_widget.button_clicked.connect(self.refresh)
```

---

## `utils/` 層 — 跨層通用工具

### 設計原則

| 項目 | 規則 |
|------|------|
| **可依賴** | 標準庫、第三方純工具庫（如 requests / pillow） |
| **禁止依賴** | PyQt / `core/` / `ui/` |
| **形式** | 純函式或無狀態類別 |
| **使用場所** | 任何需要通用功能的地方都可 import |

### 典型例子

```python
# ✅ 翻譯器（無狀態，純函式介面）
class Translator:
    def t(self, category: str, key: str, default: str = "") -> str:
        # 讀 languages/<lang>.json，回傳翻譯字串
        pass

# ❌ 錯：雜亂的工具類
class Utils:  # 絕對不要這樣寫
    @staticmethod
    def setup_qt_app():  # ❌ 涉及 PyQt
        pass

    @staticmethod
    def query_db():  # ❌ 涉及 core/ 職責
        pass
```

---

## 邊界案例與陷阱

### 案例 1：「我想在 core/ 層用 logging，可以嗎？」

✅ **可以**。logging 是標準庫，ui/ 層也可用。

```python
# core/pin_manager.py
import logging
logger = logging.getLogger(__name__)

class PinManager:
    def toggle(self, file_path):
        logger.info(f"Toggling pin for {file_path}")  # ✅
```

---

### 案例 2：「core/ 層的訊號該在哪裡連接？」

✅ 在 `ui/` 層連接（通常在 MainWindow 的 `__init__` 後）。

```python
# ui/../main_window.py (Blur-main.py 的一部分)
self.init_ui()  # 先建立 UI 元件
self.pin_mgr = PinManager(...)
self.pin_mgr.pin_toggled.connect(self.on_pin_toggled)  # ✅ 在 ui/ 層連
```

❌ **不要在 core/ 層假設誰在聽訊號**：

```python
# ❌ 錯：core/ 不應關心 ui/ 如何反應
class PinManager:
    def toggle(self, ...):
        self.emit_signal()
        self.refresh_gallery_view()  # ❌ core/ 不應知道 gallery 的存在
```

---

### 案例 3：「ui/ 層想用 core/ 的某個類實例，怎麼注入？」

通常在 MainWindow 初始化時：

```python
# Blur-main.py (MainWindow.__init__)
self.config = ConfigManager(...)   # 先建 config
self.engine = ImageSearchEngine(..., config=self.config)  # 注入 config
self.pin_mgr = PinManager(data_store_provider=...)  # 延遲注入
# 這些都已備好，init_ui() 就能用了
self.init_ui()
```

---

## 層級速查表

| 想做... | 放在哪層 | 範例檔案 |
|--------|---------|---------|
| 資料庫 CRUD | `core/` | `ocr_repository.py` |
| 業務邏輯運算 | `core/` | `pin_manager.py` |
| 訊號發射 (pure logic) | `core/` (QObject 子類) | `eta_progress_controller.py` |
| UI 佈局 | `ui/` | `main_window_ui.py` |
| 事件連接、UI 反應 | `ui/` | `gallery_view_controller.py` |
| 小 widget 自訂元件 | `ui/widgets/` | `search_capsule.py` |
| 設定頁面 | `ui/settings_pages/` | `folders_page.py` |
| 跨層工具函式 | `utils/` | `translator.py` |
| 無處可放的雜貨 | 🚫 別這樣做 | — |

---

## 相關詳細文檔

- **設計模式與陷阱** → [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md)
- **核心模組詳解** → [MODULES_CORE.md](./MODULES_CORE.md)
- **UI 模組詳解** → [MODULES_UI.md](./MODULES_UI.md)

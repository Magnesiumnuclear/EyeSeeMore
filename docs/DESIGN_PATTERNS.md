# DESIGN_PATTERNS.md — 架構設計模式與最佳實踐

> 這份文檔記錄 EyeSeeMore 重構中發現的 5 個關鍵設計模式及其陷阱、解決方案。

---

## §1 Thin Delegation Layer（薄委派層）

**原則：** 從 MainWindow 抽出邏輯到獨立模組時，**保留 MainWindow 上的方法簽章**作為一行委派包裝。

### 背景

重構早期，許多邏輯從 MainWindow 拆遷到 `core/` 層。若靠「重新引入新模組」，會迫使所有呼叫端改寫代碼。為了**零修改成本**，採用 Thin Delegation：

### 做法

```python
# 重構前：MainWindow 內部邏輯（20 行）
def toggle_pin(self, file_path):
    if not hasattr(self, '_pinned_cache'):
        self._reload_pinned_cache()
    # ... DB 操作 ...
    self.update_ui()

# 重構後：拆遷到 core/pin_manager.py
class PinManager:
    def toggle(self, file_path: str) -> bool:
        # ... 完整邏輯 ...
        return new_state

# MainWindow 中保留委派（一行）
def toggle_pin(self, file_path: str) -> bool:
    """[委派] 切換圖片釘選狀態。"""
    return self.pin_manager.toggle(file_path)
```

### 何時使用

✅ 該方法被 MainWindow 以外的代碼呼叫
✅ 該方法被連接為 `pyqtSignal` 的 slot
✅ 改變簽名會影響多個呼叫端

❌ 方法純屬內部呼叫，沒有外部 caller
❌ 完全私有的實作細節

### 優勢

- 外部呼叫端零改動（向後相容）
- 代碼遷移時不產生副作用
- 清清楚楚標註「這個邏輯搬到哪裡去了」

---

## §2 依賴注入三大策略

**原則：** 依照「被依賴的物件何時可用」選擇不同模式。

### 策略 A：建構子直接傳入（最常見）

**適用場景：** 依賴在建構時已就緒

```python
# 例：OcrRepository 需要 db_path（在啟動時已定）
class OcrRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)

# 使用
ocr_repo = OcrRepository(db_path="images.db")
```

**優勢：** 清晰、不易出錯、易於測試

---

### 策略 B：延遲屬性注入

**適用場景：** 依賴在建構後才建立（如 engine 在 `load_engine()` 才實例化）

```python
# 例：SearchOrchestrator 需要 engine
class SearchOrchestrator:
    def __init__(self):
        self.engine = None  # 稍後賦值

    def set_engine(self, engine):
        self.engine = engine

# 使用
orchestrator = SearchOrchestrator()
# ... 後續 ...
engine = ImageSearchEngine(...)
orchestrator.set_engine(engine)
```

**優勢：** 避免初始化順序問題

**缺點：** 易忘設值；建議加守衛檢查

```python
def launch_search(self, ...):
    if not self.engine:
        raise RuntimeError("engine not set!")
```

---

### 策略 C：Callable Provider（**高級**，避免 rebinding 陷阱）

**適用場景：** 依賴會被 rebinding，需要永遠取得最新參照

**陷阱場景（Phase 1-A 踩過）：**

```python
# ❌ 錯誤
class ImageSearchEngine:
    def reload(self):
        self.data_store = []  # rebinding！
        # ... 重新加載 ...

class PinManager:
    def __init__(self, data_store):
        self.data_store = data_store  # 此時持有舊參照

# 使用
engine = ImageSearchEngine()
pin_mgr = PinManager(engine.data_store)  # 傳值
engine.reload()  # data_store 被替換，但 pin_mgr 還持著舊的！
```

**Phase 1-A 發現 + Phase 1-C 配套修復：**

```python
# 方案 1：改 load_data_from_db() 為「就地修改」保留列表身分
class ImageSearchEngine:
    def __init__(self):
        self.data_store = [...]

    def load_data_from_db(self):
        temp = [... 從 DB 讀 ...]
        # ✅ 改為就地修改，保留列表的身分
        self.data_store.clear()
        self.data_store.extend(temp)
        # 不再做 self.data_store = temp

# 方案 2：使用 Callable Provider（如果 engine 確實要 rebind）
class PinManager:
    def __init__(self, data_store_provider: Callable):
        self.get_data_store = data_store_provider

    def toggle(self, file_path):
        data_store = self.get_data_store()  # 永遠取最新
        # ... 操作 ...

# 使用
engine = ImageSearchEngine()
pin_mgr = PinManager(
    data_store_provider=lambda: engine.data_store
)

engine.reload()  # data_store 替換了，但 pin_mgr 透過 lambda 永遠拿最新
```

---

## §3 PyQt 訊號 (Signal) 解耦規範

**原則：** 決定「應該用訊號還是直接呼叫」依賴**以下三個問題**：

### 何時應該用 Signal 解耦

| 情境 | 訊號類型 | 範例 |
|------|---------|------|
| **跨層通知（core → UI）** | 對外 `pyqtSignal` | `EtaProgressController.status_text_changed(str)` |
| **跨執行緒橋接** | 內部 `pyqtSignal` 自連 | `IndexingLifecycleHandler._db_reloaded` |
| **多訂閱者觀察** | 對外 `pyqtSignal` | `GalleryViewController.layout_changed()` |

### 何時可以直接呼叫

✅ View Controller 直接持有的 widget（已注入的 list_view / model / delegate）
✅ 同層 UI 元件間（widget 之間的協作）
✅ Win32 系統整合（HWND 操作沒有訂閱者場景）

### 訊號連接時序陷阱

```python
# ❌ 錯：self.status 在 init_ui() 後才存在
def __init__(self):
    super().__init__()
    self.eta_ctrl = EtaProgressController(...)
    self.eta_ctrl.status_text_changed.connect(self.status.setText)
    # AttributeError: 'MainWindow' has no attribute 'status'
    self.init_ui()  # status 在此才建立

# ✅ 對：先 init_ui 建立 UI 元件，再連接訊號
def __init__(self):
    super().__init__()
    self.init_ui()  # 先建立 UI 元件
    # 此時 self.status、self.list_view 都存在了
    self.eta_ctrl = EtaProgressController(...)
    self.eta_ctrl.status_text_changed.connect(self.status.setText)
```

**規則：**
1. 先呼叫 `setup_ui()` / `init_ui()`
2. 建立 `core/` 層物件
3. 連接訊號

---

## §4 跨執行緒通訊標準作法

**原則：** 背景執行緒只 `emit` 訊號，UI 更新交給主執行緒。

### 標準模式

```python
# 在 core/ 層（QObject 子類）
class IndexingLifecycleHandler(QObject):
    gallery_refresh_requested = pyqtSignal()  # 對外訊號
    _db_reloaded = pyqtSignal()  # 內部訊號（跨執行緒橋接）

    def __init__(self, ...):
        super().__init__(parent=None)
        # 關鍵：自連內部訊號以跨越執行緒邊界
        self._db_reloaded.connect(self.on_db_reloaded)

    def trigger_background_db_reload(self) -> None:
        """觸發背景 DB 重載（在背景執行緒進行）"""
        def bg_reload():
            self.engine.load_data_from_db()  # 重 I/O，在背景跑
            self._db_reloaded.emit()  # 發內部訊號（自動跨所執行緒）

        thread = threading.Thread(target=bg_reload, daemon=True)
        thread.start()

    def on_db_reloaded(self) -> None:
        """被 _db_reloaded 訊號觸發（此時已在主執行緒）"""
        # 安全地發外部訊號給 UI 層
        self.gallery_refresh_requested.emit()
```

### 執行流程圖

```
主執行緒：
  IndexingWorker 掃描完成
  ↓
  emit scanning_finished()
  ↓
  MainWindow._on_scanning_finished()
    ↓ 觸發
    indexing_handler.trigger_background_db_reload()
      ↓ (啟動背景執行緒)

背景執行緒：
  engine.load_data_from_db()  (耗時 I/O)
  ↓
  emit _db_reloaded()
  ↓ (Qt 自動切回主執行緒)

主執行緒：
  on_db_reloaded()
  ↓
  emit gallery_refresh_requested()  (發外部訊號)
  ↓
  MainWindow._on_gallery_refresh()  (UI 更新)
```

### 禁忌

❌ 背景執行緒直接寫 QWidget
```python
def bg_thread():
    self.status.setText("掃描中...")  # ❌ 不安全，會崩潰
```

❌ 背景執行緒直接呼叫主執行緒的 method
```python
def bg_thread():
    self._apply_folder_filter(...)  # ❌ 不安全，競態
```

✅ 唯一管道：`pyqtSignal.emit(...)`
```python
def bg_thread():
    self.status_changed.emit("掃描中...")  # ✅ Qt 自動派遣
```

---

## §5 Win32 整合注意事項

> EyeSeeMore 是無邊框視窗 + 自訂標題列。WndProc Hook 由 C++ DLL 負責，Python 層透過 `core/win_titlebar.py` 橋接。

### 地雷：`setWindowFlag(WindowStaysOnTopHint)` 會毀掉標題列

```python
# ❌ 錯：會重建 HWND，導致 WndProc Hook 失效
self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
self.show()  # 視窗會沒有自訂標題列

# ✅ 正確：直接用 Win32 API 切換 TOPMOST，不重建 HWND
import ctypes
HWND_TOPMOST = ctypes.wintypes.HWND(-1)
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

hwnd = int(self.winId())
ctypes.windll.user32.SetWindowPos(
    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
)
```

### resizeEvent 內必須同步兩件事

每當視窗大小變化，需通知 WndProc Hook 新的按鈕座標：

```python
def resizeEvent(self, event: QResizeEvent):
    super().resizeEvent(event)

    # 1. 更新按鈕座標（NC hit-test 用）
    btn_rects = self._calculate_button_rects()  # 像素座標
    dpr = self.devicePixelRatio()
    btn_rects = [(x*dpr, y*dpr, w*dpr, h*dpr) for x,y,w,h in btn_rects]
    self.window_mgr.update_button_rects(btn_rects)

    # 2. 同步最大化按鈕狀態
    self.window_mgr.sync_max_button_state()
```

### DPI 感知

所有 Win32 座標必須**乘以 DPR**（Device Pixel Ratio）：

```python
def update_button_rects(self, rects):
    """rects: [(x, y, w, h), ...]，單位：邏輯像素"""
    dpr = self.widget.devicePixelRatio()
    physical_rects = [
        (int(x*dpr), int(y*dpr), int(w*dpr), int(h*dpr))
        for x, y, w, h in rects
    ]
    # 傳入 Win32 API
```

---

## 常見反面教材

### ❌ 錯誤 1：core/ 層持有 QWidget 參照

```python
# 錯誤
class SearchOrchestrator:
    def __init__(self, status_bar: QStatusBar):
        self.status_bar = status_bar

    def update_status(self, text):
        self.status_bar.setText(text)  # ❌ core/ 不應持有 widget
```

✅ **正確做法：** 發訊號
```python
class SearchOrchestrator(QObject):
    status_changed = pyqtSignal(str)

    def update_status(self, text):
        self.status_changed.emit(text)
```

---

### ❌ 錯誤 2：widget 持有 MainWindow 參照

```python
# 錯誤
class SearchCapsule(QWidget):
    def __init__(self, main_window):  # ❌
        self.main_window = main_window

    def on_search(self):
        self.main_window.gallery_view.refresh()
```

✅ **正確做法：** 發訊號，讓上層連接
```python
class SearchCapsule(QWidget):
    searchRequested = pyqtSignal(dict)

    def on_search(self):
        self.searchRequested.emit({'query': ...})

# MainWindow 連接
self.search_capsule.searchRequested.connect(self._on_search)
```

---

### ❌ 錯誤 3：忘記在 init_ui() 後才連接訊號

```python
# 錯誤時序
self.eta_ctrl = EtaProgressController()
self.eta_ctrl.status_changed.connect(self.status.setText)  # AttributeError!
self.init_ui()

# 正確時序
self.init_ui()
self.eta_ctrl = EtaProgressController()
self.eta_ctrl.status_changed.connect(self.status.setText)  # ✅
```

---

## 相關詳細文檔

- **各層職責邊界** → [LAYERS.md](./LAYERS.md)
- **核心模組實例** → [MODULES_CORE.md](./MODULES_CORE.md)
- **UI 控制器實例** → [MODULES_UI.md](./MODULES_UI.md)

# CONTRIBUTION.md — 新增功能的標準流程與開發指南

> 這份文檔是「我要在 EyeSeeMore 添加新功能」的逐步指南。

---

## 🚦 新增功能的 6 步標準流程

### Step 1：判斷職責歸屬（5 分鐘）

```
新功能是什麼？
│
├─ 純資料邏輯 / 算法 / 資料庫 CRUD
│  → 放在 core/ 層
│    ├─ 資料存取（DB CRUD）→ *_repository.py
│    ├─ 業務邏輯 → *_manager.py 或 *_handler.py
│    └─ 需訊號發射 → 繼承 QObject，發 pyqtSignal
│
├─ UI 相關
│  ├─ 是小原子 widget （< 200 行）
│  │  → ui/widgets/ 層
│  │
│  ├─ 是視圖控制器（管理 QListView、QTableView 等）
│  │  → ui/ 層（如 gallery_view_controller.py）
│  │
│  ├─ 是設定頁面
│  │  → ui/settings_pages/ 層
│  │
│  └─ 是事件分發、佈局
│     → ui/ 層（如 action_handler.py）
│
└─ 跨層工具函式（翻譯、助手函式）
   → utils/ 層
     └─ ⚠️ 禁止依賴 PyQt / core / ui
```

---

### Step 2：設計依賴注入（10 分鐘）

依 [DESIGN_PATTERNS.md §3.2](./DESIGN_PATTERNS.md#32-依賴注入三大策略) 選擇策略：

#### 選項 A：建構子直接傳入（最常見）

```python
# 例：新建 FolderScanner
class FolderScanner:
    def __init__(self, root_folder: str, config: ConfigManager):
        self.root_folder = root_folder
        self.config = config

# MainWindow 中
self.folder_scanner = FolderScanner(
    root_folder="E:\Photos",
    config=self.config
)
```

**適用：** 依賴在建構時已就緒

---

#### 選項 B：延遲屬性注入

```python
class MyService:
    def __init__(self):
        self.engine = None

    def set_engine(self, engine):
        self.engine = engine

# MainWindow 中
self.my_service = MyService()
# ... 稍後 ...
self.my_service.set_engine(self.engine)
```

**適用：** 依賴在建構後才建立

---

#### 選項 C：Callable Provider（高級）

```python
class MyService:
    def __init__(self, engine_provider):
        self.get_engine = engine_provider

    def do_something(self):
        engine = self.get_engine()  # 永遠取最新
        ...

# MainWindow 中
self.my_service = MyService(
    engine_provider=lambda: self.engine
)
```

**適用：** 依賴會 rebinding，需永遠取最新參照（見 [DESIGN_PATTERNS.md §3.2](./DESIGN_PATTERNS.md#策略-c：callable-provider高級避免-rebinding-陷阱)）

---

### Step 3：設計訊號邊界（10 分鐘）

依 [DESIGN_PATTERNS.md §3.3](./DESIGN_PATTERNS.md#§3-pyqt-訊號-signal-解耦規範) 判斷：

```
需要通知 UI 更新嗎？
│
├─ 是，而且多個 UI 元件 / mainWindow 想觀察
│  → core/ 層發 pyqtSignal
│    例：EtaProgressController.status_text_changed(str)
│
├─ 是，但只有一個地方在用（內部邏輯）
│  → 可以直接呼叫方法（不一定要訊號）
│  → 或發內部訊號給同層
│
├─ 涉及背景執行緒跨越到主執行緒
│  → 發內部 pyqtSignal 自連（Qt 自動派遣）
│    例：IndexingLifecycleHandler._db_reloaded
│
└─ 純資料邏輯，沒有 UI 相關
   → 不發訊號，直接當面向 API 呼叫
```

**訊號命名慣例：**
```python
class MyController(QObject):
    # 對外訊號（UI 層可能訂閱）
    data_updated = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    # 內部訊號（跨執行緒用）
    _internal_done = pyqtSignal()

    def __init__(self):
        super().__init__()
        # 自連內部訊號
        self._internal_done.connect(self._on_internal_done)
```

---

### Step 4：MainWindow 整合（15 分鐘）

**正確時序：**

```python
# Blur-main.py: MainWindow.__init__
def __init__(self, ...):
    super().__init__()

    # 第一步：載入基礎設定
    self.config = ConfigManager(...)
    self.config.load()

    # 第二步：建立 core/ 層物件
    self.my_service = MyService(...)
    self.eta_ctrl = EtaProgressController(...)

    # 第三步：建立 UI（此時 self.status / self.list_view 才存在）
    self.init_ui()

    # 第四步：連接訊號（UI 元件已存在）
    self.my_service.data_updated.connect(self._on_data_updated)
    self.eta_ctrl.status_text_changed.connect(self.status.setText)

    # 第五步：保留 Thin Delegation Layer（外部呼叫不變）
    if external_caller_calls_toggle_pin():
        self.toggle_pin(file_path)  # 委派給 pin_manager
```

**Thin Delegation 範例：**

```python
def toggle_pin(self, file_path: str) -> bool:
    """[委派] 切換釘選狀態。"""
    return self.pin_manager.toggle(file_path)

def clear_search_history(self) -> None:
    """[委派] 清空搜尋歷史。"""
    self.history_mgr.clear()
```

---

### Step 5：測試與驗證（15 分鐘）

#### 5a. 語法檢查
```bash
python -m py_compile core/my_new_module.py
```

#### 5b. Import 檢查
```python
# 確認循環依賴
from core.my_new_module import MyService  # ✅
```

#### 5c. Smoke Test（冒煙測試）

```python
# 簡單的單元測試
if __name__ == "__main__":
    # Test 1：初始化
    service = MyService(config=ConfigManager(...))
    print("✅ Service initialized")

    # Test 2：核心方法
    result = service.do_something()
    assert result is not None
    print("✅ Core method works")

    # Test 3：訊號發射（若有）
    signal_emitted = False
    service.data_updated.connect(lambda d: globals().update(signal_emitted=True))
    service.trigger_update({"test": "data"})
    assert signal_emitted
    print("✅ Signal emits correctly")
```

#### 5d. 視覺測試（手動 smoke test）

```bash
python main.py
# 手動操作新功能，確認 UI 反應、無錯誤訊息
```

---

### Step 6：Commit 與文檔更新（10 分鐘）

#### 6a. Git Commit

```bash
git add core/my_new_module.py ui/...
git commit -m "feat: 新增 MyService 用於...

- 實現了 XYZ 功能
- 設計上採用了 [Thin Delegation / Signal / Callable Provider]
- 與 [某某模組] 協作完成...

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

**Commit message 格式：**
- 首行：`feat:` / `refactor:` / `fix:` + 簡短說明
- 次行空行
- 後文：詳細設計取捨說明

#### 6b. 同步文檔

若新增的模組足夠重要（>100 行或新增控制器）：

1. **更新 [ARCHITECTURE.md](./ARCHITECTURE.md)** — 在「核心模組任務總覽」表中添加新模組
2. **新增或更新對應專題文檔** — 例如在 [MODULES_CORE.md](./MODULES_CORE.md) 添加詳解
3. **更新 [ROADMAP.md](./ROADMAP.md)** — 記錄新的達成或修改重構方向

---

## 背景服務與獨立腳本

### 現有背景服務概覽

| 腳本 | 職責 | 觸發時機 |
|------|------|---------|
| **`indexer.py`** | 獨立索引引擎 | 啟動時 & 使用者觸發掃描 |
| **`onnx_ocr.py`** | ONNX PaddleOCR 推論 | indexer.py 內部呼叫 |
| **`cleanup_db.py`** | 一次性 DB 維護 | 手動執行 |
| **`export_clip_onnx.py`** | CLIP 模型轉換 | 開發者用 |
| **`pack_release.py`** | 發佈打包 | CI/CD 流程 |
| **`fix_env.py`** | 補裝环境相依 | 攜帶版運行時補救 |

### 若要新增背景服務

1. **編寫獨立執行的新腳本** — 可單獨 `python service.py` 運行
2. **MainWindow 中建 QThread Worker 包裝**

```python
class MyServiceWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        try:
            from my_service import MyService
            service = MyService(...)
            service.do_work()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

# MainWindow 中
self.worker = MyServiceWorker()
self.worker.finished.connect(self._on_service_done)
self.worker.start()
```

---

## 常見場景示例

### 場景 1：新增一下簡單計算邏輯（如數據過濾）

```python
# 新建 core/date_filter.py
class DateFilter:
    """日期過濾邏輯"""
    def __init__(self, min_date: datetime, max_date: datetime):
        self.min_date = min_date
        self.max_date = max_date

    def filter(self, items: list) -> list:
        return [item for item in items
                if self.min_date <= item.mtime <= self.max_date]

# 在 GalleryViewController.py 中使用
from core.date_filter import DateFilter
date_filter = DateFilter(min_date, max_date)
filtered = date_filter.filter(self.all_items)
```

---

### 場景 2：新增 UI 控制器（如新的視圖模式）

```python
# 新建 ui/list_view_controller.py
from ui.gallery_view_controller import BaseViewController

class ListViewController(BaseViewController):
    """列表視圖控制器（vs. grid 視圖）"""

    def __init__(self, list_view: QListView, model: QAbstractItemModel):
        super().__init__()
        self.list_view = list_view
        self.model = model

    def display_results(self, items):
        # 列表式佈局
        self.model.clear()
        for item in items:
            self.model.appendRow(...)

    # emit layout_changed 等訊號...

# MainWindow 中
self.list_vc = ListViewController(self.list_view, self.model)
self.list_vc.layout_changed.connect(self._on_layout_changed)
```

---

### 場景 3：新增設定頁面

```python
# 新建 ui/settings_pages/custom_page.py
from ui.widgets.base import BaseToggleWidget

class CustomPage(BaseToggleWidget):
    def __init__(self, ctx: dict):
        super().__init__()
        self.config = ctx["config"]         # 從 ctx 注入
        self.engine = ctx["engine"]
        # ❌ 不 hold main_window

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        # ... 建立 UI ...
        self.setLayout(layout)

    def save(self):
        """設定變更時呼叫"""
        self.config.set("custom_key", value)
        self.config.save()

# SettingsDialog 中
ctx["custom_page"] = CustomPage(ctx)
```

---

### 場景 4：背景索引 Worker（如新增轉檔任務）

```python
# 在 Blur-main.py 中定義 Worker
class ConvertWorker(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, file_list):
        super().__init__()
        self.file_list = file_list

    def run(self):
        for i, file_path in enumerate(self.file_list):
            # 轉檔邏輯
            convert(file_path)
            self.progress.emit((i+1) * 100 // len(self.file_list))
        self.finished.emit()

# MainWindow 中
self.convert_worker = ConvertWorker(selected_files)
self.convert_worker.progress.connect(self.progress_bar.setValue)
self.convert_worker.finished.connect(self._on_convert_done)
self.convert_worker.start()
```

---

## 快速檢查清單

- [ ] **職責歸屬清楚** — 代碼在正確的層級（core / ui / utils）
- [ ] **無循環依賴** — A 不 import B，B 也不 import A
- [ ] **訊號設計正確** — 跨層用訊號，同層可直接呼叫
- [ ] **依賴注入完整** — 所有依賴都明確傳入（沒有全域變數）
- [ ] **Thin Delegation 就位** — 外部呼叫端無需改寫
- [ ] **測試通過** — 無語法誤，smoke test 通過
- [ ] **文檔同步** — 若新增重要模組，已更新相關文檔

---

## 相關詳細文檔

- **層責邊界與禁忌** → [LAYERS.md](./LAYERS.md)
- **依賴注入 / 訊號 / Win32 陷阱** → [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md)
- **核心模組完整 API** → [MODULES_CORE.md](./MODULES_CORE.md)
- **UI 控制器設計** → [MODULES_UI.md](./MODULES_UI.md)

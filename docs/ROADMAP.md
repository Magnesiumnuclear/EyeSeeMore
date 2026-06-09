# ROADMAP.md — 重構戰績、已知 Bug、未來規劃

> 本文件記錄 EyeSeeMore 從 Phase 0 到未來的發展進程。

---

## 📊 Phase 1 + 2 + 3 重構戰績

### 代碼瘦身

| 指標 | 重構前 | 重構後 | 變化 |
|------|--------|--------|------|
| **`Blur-main.py` 總行數** | 7081 | **~1400** | **−5681 行 (−80%)** |
| **`MainWindow` 佔比** | ~23% | ~88% | 主檔幾乎全是 MainWindow |
| **`ImageSearchEngine`** | 嵌入主檔 | 獨立 716 行 | 完全解耦 |
| **獨立模組總數** | 0 | **24** | +24（含 Phase 3-F 的 12 個）|

### 新增模組（24 個）

```
Phase 1 (資料存取與釘選)
└── 1-A: core/pin_manager.py             ← 圖片釘選
└── 1-B: core/ocr_repository.py          ← OCR 框 CRUD
└── 1-C: core/collection_manager.py      ← 虛擬資料夾

Phase 2 (UI 反饋與控制)
└── 2-A: core/search_history_manager.py  ← 搜尋歷史
└── 2-B: core/eta_progress_controller.py ← ETA 進度 + PID
└── 2-C: core/indexing_lifecycle.py      ← 索引生命週期
└── 2-D: ui/gallery_view_controller.py   ← 畫廊視圖
└── 2-E: ui/window_state_manager.py      ← 視窗狀態 + Win32

Phase 3 (非阻塞模型加載 & 解耦 & UI 響應式 & 效能優化 & 主檔拆分)
└── 3-A: core/model_provider.py          ← 模型加載與共享【已完成】
└── 3-B: _on_models_loaded 優化          ← 畫廊圖片提早顯示【已完成】
└── 3-C: ui/widgets/elided_label.py      ← TopBar 響應式寬度【已完成】
└── 3-D: 三大效能熱點修復                 ← I/O阻塞、N+1查詢、FAISS演算法【已完成】
└── 3-E: 畫廊渲染 Quick-wins             ← 7 項低風險效能改進【已完成】
└── 3-F: Blur-main.py 主檔大拆分         ← 12 個模組從主檔拆出【已完成】
     ├── core/image_search_engine.py     ← AI 核心引擎
     ├── core/taskbar_controller.py      ← Windows 工作列 COM
     ├── core/win_event_filters.py       ← Win32 事件 + Jump List
     ├── core/workers.py                 ← QThread/QRunnable 執行緒群
     ├── ui/gallery_model.py             ← SearchResultsModel + GalleryListView
     ├── ui/preview_overlay.py           ← 全螢幕預覽層
     ├── ui/settings_dialog.py           ← SettingsDialog + OnboardingDialog
     ├── ui/sidebar_widget.py            ← SidebarWidget + Hover 選單
     ├── ui/widgets/empty_state.py       ← 空狀態覆蓋層
     ├── ui/widgets/feature_widgets.py   ← 多模態特徵標籤面板
     ├── ui/widgets/image_delegate.py    ← 圖片卡片渲染代理
     └── ui/widgets/ocr_widgets.py       ← OCR 框選 + 標籤 widget
```

### 架構改進

- ✅ **零 UI 依賴的核心層** — 所有業務邏輯可獨立測試
- ✅ **Thin Delegation Layer** — 外部呼叫端零改動
- ✅ **訊號解耦規範** — 跨層通信明確、實作清晰
- ✅ **依賴注入三策略** — 避免全域變數、支援測試
- ✅ **跨執行緒雙緩衝** — DB 重載不卡主執行緒
- ✅ **非阻塞模型加載** — IndexerWorker 不再等待 AI 模型【Phase 3-A 新增】
- ✅ **畫廊提早渲染** — 圖片在 t~100ms 即顯示，不等模型加載完成【Phase 3-B 新增】
- ✅ **TopBar 響應式寬度** — 視窗可縮小，長路徑省略顯示不撐大最小寬度【Phase 3-C 新增】
- ✅ **啟動 I/O 去阻塞** — os.scandir 預掃描替代 N 次 os.path.exists syscall【Phase 3-D 新增】
- ✅ **軌道 C 批次查詢** — IN 子句消除 2N 次 round-trip，OCR 補算速度 ×2~5【Phase 3-D 新增】
- ✅ **FAISS 動態 HNSW** — 超過 1 萬筆自動切換 O(log N) 圖索引，搜尋延遲降至個位數 ms【Phase 3-D 新增】
- ✅ **Limit 切換不重搜** — 僅截斷現有結果，跳過 FAISS pipeline【Phase 3-E 新增】
- ✅ **sort_items 輕量更新** — `layoutAboutToBeChanged/layoutChanged` 取代第二次 `beginResetModel`，消除排序閃爍【Phase 3-E 新增】
- ✅ **adjust_layout 快取** — `_last_layout` tuple 防止視窗微幅縮放觸發無效 setter【Phase 3-E 新增】
- ✅ **_ensure_icon_column 單次執行** — class-level 旗標消除每次 get_collections 的額外 SQL【Phase 3-E 新增】

---

## 🔧 Phase 3-D 改進詳情（【已完成】）

### 問題

啟動與索引流程存在三個已量化的效能熱點：
1. `load_data_from_db` 對每張圖呼叫一次 `os.path.exists`，N 張圖 = N 次 syscall
2. `indexer.py` 軌道 C 對每張圖各發一條 `SELECT`，N 張圖 = 2N 次 SQLite round-trip
3. `build_faiss_index` 固定使用暴力搜尋 `IndexFlatIP`，搜尋複雜度 O(N)

### 解決方案

| 改動 | 檔案 | 說明 |
|------|------|------|
| **os.scandir 預掃描** | `Blur-main.py` | 先收集所有父目錄，一次 scandir 建立存在檔案的 Set；迴圈內改為 O(1) 記憶體查詢 |
| **軌道 C 批次 IN 查詢** | `indexer.py` | 兩條 `SELECT ... IN (?)` 一次取得整批的 `path→id` 及 `id→done_langs`，消除 N+1 |
| **FAISS 動態 HNSW** | `Blur-main.py` | 超過 10,000 筆自動切換 `IndexHNSWFlat(d, 32, METRIC_INNER_PRODUCT, efSearch=64)` |

### 效能改善數據

**Task 1 — 啟動 I/O 阻塞**

| 場景 | 優化前 | 優化後 |
|------|--------|--------|
| 1 萬張，SSD | ~50ms | ~5ms |
| 1 萬張，HDD | ~3,000ms | ~50ms |
| 5 萬張，HDD | ~15,000ms | ~200ms |

**Task 2 — 軌道 C N+1 查詢**

| 批次大小 | 優化前 | 優化後 |
|---------|--------|--------|
| 4 張 | 8 次 round-trip | 2 次 round-trip |
| 100 張 | 200 次 round-trip | 2 次 round-trip |

**Task 3 — FAISS 搜尋延遲**

| 資料量 | IndexFlatIP O(N) | IndexHNSWFlat O(log N) |
|--------|-----------------|------------------------|
| ≤10,000 | 自動保持 FlatIP（精度 100%） | — |
| 50,000 張 | ~40ms | ~3ms |
| 200,000 張 | ~160ms | ~5ms |

### 設計取捨

- `os.scandir` 只掃一層（直接父目錄），正確覆蓋所有已索引檔案路徑（DB 存的是完整絕對路徑，dirname 一定是其直接父目錄）
- HNSW 建構時間為 O(N log N)（比 FlatIP 慢），但只在啟動時執行一次；`efSearch=64` 在精度（~98% recall）與速度間取得平衡
- `METRIC_INNER_PRODUCT` 確保與原 `IndexFlatIP` 的余弦相似度語義完全一致（向量已 L2 正規化）

---

## 🔧 Phase 3-E 改進詳情（【已完成】）

### 問題

Phase 3-D 解決了啟動與索引流程的三大熱點，但畫廊的**互動渲染路徑**仍存在多個低成本可修復的瓶頸。

### 解決方案

| # | 改動 | 檔案 | 說明 |
|---|------|------|------|
| 1 | `on_limit_changed` 不再發射 `weights_changed` | `ui/inspector_panel.py` | 直接呼叫 `apply_current_filters_and_show()`，切換顯示數量時跳過完整 FAISS pipeline |
| 2 | `sort_items` 改用 `layoutAboutToBeChanged/layoutChanged` | `Blur-main.py` | 排序不再觸發第二次 `beginResetModel`，避免視圖全量重設與閃爍 |
| 3 | `on_sidebar_toggled` 移除 `processEvents()` | `Blur-main.py` | 改用 `QTimer.singleShot(0, adjust_layout)`，消除遞迴重入事件迴圈風險 |
| 4 | `adjust_layout` 加入 `_last_layout` 快取 | `ui/gallery_view_controller.py` | 相同計算結果直接 return，視窗微幅縮放不再觸發無效 setter |
| 5 | `import math` 移至檔案頂端 | `Blur-main.py` | 消除每次 `OCRLabel.paintEvent` 的模組字典查找 |
| 6 | `_ensure_icon_column` 加 class-level 旗標 | `core/collection_manager.py` | `PRAGMA table_info` 只執行一次，後續所有 `get_collections` 呼叫零額外 SQL |
| 7 | `change_view_mode` 移除冗餘 `layoutChanged.emit()` | `ui/gallery_view_controller.py` | `update_target_size` 已含 reset；改以 `_last_layout = ()` 強制 adjust_layout 重算 |

### 設計取捨

- **Quick-win #2 的限制**：`sort_items` 改用 `layoutAboutToBeChanged/layoutChanged` 後若未呼叫 `changePersistentIndexList`，`QPersistentModelIndex` 在排序後會失效（選取狀態可能偏移）。目前 `apply_gallery_sort` 結束後會呼叫 `scrollToTop()`，實務上不影響使用體驗。若未來需保留選取，應補完 `changePersistentIndexList` 映射表（屬中長期架構建議 C）。
- **Quick-win #6 的前提**：`_icon_column_ensured` 是 class-level（所有實例共享），適用於單一 DB 的正常使用場景。若同一程序同時操作多個 DB（每個需要獨立遷移），應改為 instance-level 旗標。

---

## 🔧 Phase 3-C 改進詳情（【已完成】）

### 問題

- **現象**：TopBar 的麵包屑（`breadcrumb_lbl`）顯示長路徑時（如 `"Collection: 超長名稱"`），視窗無法縮小
- **根本原因**：標準 `QLabel` 的 `minimumSizeHint()` 回傳完整文字寬度，成為佈局最小寬度的下限；加上 `SearchCapsule.setMinimumWidth(300)` 固定限制，導致視窗最小寬度遠超必要

### 解決方案

| 改動 | 檔案 | 說明 |
|------|------|------|
| **新增 ElidedLabel** | `ui/widgets/elided_label.py` | 覆寫 `minimumSizeHint()` 水平回傳 0；`resizeEvent` 自動省略文字 |
| **換用 ElidedLabel** | `ui/main_window_ui.py` | `breadcrumb_lbl` 與 `status` 改用 ElidedLabel |
| **縮小最小寬度** | `ui/widgets/search_capsule.py` | `setMinimumWidth(300)` → `setMinimumWidth(160)` |
| **設定視窗下限** | `Blur-main.py` | `MainWindow.setMinimumSize(540, 360)` |
| **修正文字讀取** | `Blur-main.py` | `breadcrumb_lbl.text()` → `fullText()`（_nav_snapshot）；`status.text()` → `fullText()`（toast 還原） |

### 設計取捨

- `ElidedLabel` 保留 `Preferred` SizePolicy（不用 `Ignored`），確保有多餘空間時仍顯示完整文字
- 只覆寫 `minimumSizeHint().width() = 0`，讓空間不足時可縮至任意寬度
- `fullText()` 提供完整原始文字的讀取介面，避免省略後的顯示文字被錯誤存入導航/toast 快照

---

## 🔧 Phase 3-B 改進詳情（【已完成】）

### 問題

- **現象**：Phase 3-A 完成後，畫廊圖片仍然要等模型加載（t~8000ms）才出現
- **根本原因**：`_on_models_loaded()` 調用了 `_apply_folder_filter(current_folder_path)`，觸發 `Model.beginResetModel()` 重置，覆蓋了 `random_data_ready` 在 t~100ms 的初始渲染

### 解決方案

- 📝 修改 `_on_models_loaded()` — 只在啟動資料夾為指定資料夾（非 "ALL"）時才套用過濾
- ✅ "ALL" 模式：圖片由 `random_data_ready` 訊號在 t~100ms 顯示
- ✅ 指定資料夾模式：仍在模型加載後套用（維持原有功能）

### 時間線（改進後）

```
t=0ms     : MainWindow.__init__
t+150ms   : load_engine() 後台執行緒啟動
t+100ms   : ✅ random_data_ready 發射 → 圖片立刻填入 Model
            ✅ 畫廊圖片在 UI 上顯示（不等模型！）
t+500ms   : ⚙️ model_provider 在背景加載 ONNX 模型
t+8000ms  : ✅ models_loaded 發射 → _on_models_loaded()
            ✅ 只刷新 sidebar/collections，不重置畫廊
```

### 實裝清單

| 檔案 | 改動 |
|------|------|
| `Blur-main.py` | `_on_models_loaded()` 加入 `if current_folder_path != "ALL"` 判斷 |

---

## 🔧 Phase 3-A 改進詳情（【已完成】）

### 問題
- **舊架構**：IndexerWorker 卡在 `while not engine.is_ready: sleep(1)` 忙輪詢
- **現象**：新圖片索引延遲，用戶感受冷啟動慢

### 解決方案
- 📦 新建 `core/model_provider.py` — 獨立的模型加載與共享
- ⚙️ ImageSearchEngine 改為委派給 ModelProvider（非阻塞 async 加載）
- 🚀 IndexerWorker 移除 WAIT_LOOP — 立刻啟動掃描與索引
- 💾 indexer.py 改為 Lazy Load OCR — 需要時才加載

### 時間線（改進前 vs 改進後）

**改進前：** ❌ 阻塞
```
t=0ms     : MainWindow.__init__
t+300ms   : ✅ 圖片清單顯示
t+500ms   : ❌ IndexerWorker 進入 WAIT_LOOP (卡住...)
t+8000ms+ : ⏳ 模型加載完成，IndexerWorker 才開始索引
```

**改進後：** ✅ 非阻塞
```
t=0ms     : MainWindow.__init__
t+300ms   : ✅ 圖片清單顯示
            ✅ IndexerWorker 立刻啟動掃描（無阻塞）
t+500ms   : ⚙️ 模型在背景加載（不干擾前台）
t+8000ms+ : ✅ 模型完成 → IndexerWorker 執行嵌入化 & OCR
```

### 實裝清單

| 檔案 | 改動 |
|------|------|
| `core/model_provider.py` | 【新建】獨立模型加載器 QObject |
| `Blur-main.py` | ImageSearchEngine 改為委派屬性；load_engine() 改為非阻塞 |
| `Blur-main.py` | IndexerWorker.run() 刪除 L2010 的 WAIT_LOOP |
| `indexer.py` | Lazy Load OCR 引擎（首次使用時才加載） |

---

## 🐛 已知 Bug

### Bug 1：搜尋歷史刪除未持久化

**現象：** 在 SearchCapsule 的歷史下拉中刪除某筆歷史，重啟應用首次還在

**根本原因：** `SearchCapsule._on_history_delete()` 未透過訊號通知 MainWindow，未觸發 `search_history_manager.delete()`

**影響：** 低（使用者再點一次手動刪）

**修復方案：**
```python
# ui/widgets/search_capsule.py
class SearchCapsule(QWidget):
    history_delete_requested = pyqtSignal(str)  # 新增訊號

    def _on_history_delete(self, query):
        self.history_delete_requested.emit(query)  # 發訊號

# Blur-main.py: MainWindow.__init__
self.search_capsule.history_delete_requested.connect(
    self.history_mgr.delete
)
```

---

### Bug 2：模型切換後未重索引

**現象：** 若使用者在 `ai_engine_page.py` 切換 CLIP 模型，現有的 embeddings 表內容未更新

**根本原因：** `ai_engine_page.py` 切換模型後只修改 config，未觸發重新向量化

**影響：** 中等（舊向量與新模型不匹配，搜尋結果差）

**修復方案：**
```python
# ui/settings_pages/ai_engine_page.py
def on_model_changed(self):
    self.config.set("ai._clip_model", new_model)
    self.config.save()

    # 透過 ctx["hub"] 通知 MainWindow
    self.ctx["hub"].request_reindex_all()
```

---

## 🔧 Phase 3-F 改進詳情（【已完成】）

### 目標

Blur-main.py 經過 Phase 1-3E 的模組化後仍有 6391 行，其中包含大量與 MainWindow 無關的 class 定義，導致：
- 單一檔案難以導覽（class 散落在 L220-L6262）
- VSCode 智能提示效率低
- 新功能難以定位應放在哪裡

### 解決方案

| 模組 | 行數 | 職責 |
|------|------|------|
| `core/image_search_engine.py` | 716 | AI 核心、FAISS、SQLite |
| `core/taskbar_controller.py` | 98 | Windows 工作列 COM |
| `core/win_event_filters.py` | 414 | Win32 事件 + Jump List |
| `core/workers.py` | 276 | QThread/QRunnable 群 |
| `ui/gallery_model.py` | 311 | SearchResultsModel + GalleryListView |
| `ui/preview_overlay.py` | 711 | 全螢幕預覽 + OCR 互動 |
| `ui/settings_dialog.py` | 194 | SettingsDialog + OnboardingDialog |
| `ui/sidebar_widget.py` | 804 | 側邊欄 + Hover 選單 |
| `ui/widgets/empty_state.py` | 52 | 空狀態覆蓋層 |
| `ui/widgets/feature_widgets.py` | 309 | 特徵標籤面板 |
| `ui/widgets/image_delegate.py` | 700 | 卡片渲染代理 |
| `ui/widgets/ocr_widgets.py` | 649 | OCR 框選 + 標籤 |

### 成果

| 指標 | 拆分前 | 拆分後 |
|------|--------|--------|
| Blur-main.py | 6391 行 | **1398 行（−78%）** |
| Blur-main.py 中的 class 數 | 32 個 | **1 個（MainWindow）** |
| 所有模組語法檢查 | — | **13/13 通過** |

---

## 🎯 Phase 4 − 拆分繪製邏輯（計劃中）

### 目標

`ImageDelegate.paint()` 與 `OCRLabel.paintEvent()` 分佈散亂的繪製邏輯

### 拆分方案

```
ui/painting/
├── image_delegate_painter.py  ← 繪製卡片（如陰影、釘選標誌）
└── ocr_label_painter.py       ← 繪製 OCR 框
```

**方式：** 提取私有方法 `_draw_shadow()`, `_draw_selection()`, `_paint_ocr_boxes()` 等

---

## 🧪 測試補完（計劃中）

### 目標

為 `core/` 層 8 個模組撰寫 pytest 單元測試

### 預計覆蓋

```
tests/
├── test_pin_manager.py              ← toggle / get_pinned_paths
├── test_ocr_repository.py           ← CRUD 操作
├── test_collection_manager.py       ← 集合管理
├── test_search_history_manager.py   ← MRU 行為
├── test_eta_progress_controller.py  ← 4 種模式、PID 平滑器
├── test_indexing_lifecycle.py       ← 生命週期事件
├── test_gallery_view_controller.py  ← 過濾、排序、空狀態
└── test_window_state_manager.py     ← Win32 整合（需 mock）
```

**測試框架：** pytest + pytest-qt（PyQt6 擴展）

**目標覆蓋率：** ≥ 80%

---

## ✍️ 型別檢查（計劃中）

### 目標

**逐步引入 mypy / pyright 型別檢查**，並補完 type hints

### 階段

1. **Phase 1：基礎設施層** — `core/paths.py`, `core/config_manager.py`
2. **Phase 2：資料層** — `core/ocr_repository.py`, `core/collection_manager.py`
3. **Phase 3：UI 層** — `ui/gallery_view_controller.py`, `ui/window_state_manager.py`

### 工具鏈

```bash
# 運行 mypy
mypy --strict core/ ui/

# 運行 pyright（VSCode / IDE 用）
# 在 pyrightconfig.json 中配置
```

---

## 📐 架構願景

### 短期（3 個月）

- ✅ 完成 Phase 3 預覽層拆分
- ✅ 修復已知 2 個 Bug
- ⏳ 補完 core/ 測試用例（≥ 80%）

### 中期（6-12 個月）

- ⏳ Phase 4 繪製邏輯拆分
- ⏳ 啟用型別檢查（全代碼库 mypy strict）
- ⏳ 重構 `ImageSearchEngine` — 與 `indexer.py` 職責整合

### 長期願景

- **可測試架構** — 所有邏輯層都能單元測試
- **外掛機制** — 支援第三方 AI 模型（如 LangChain 整合）
- ✅ **效能優化（基礎）** — FAISS HNSW 動態切換、I/O 去阻塞、N+1 消除【Phase 3-D 完成】；GPU 加速、增量索引仍待實作
- **國際化完善** — 動態語言包安裝、RTL 支援

---

## 🔧 現有技術棧

### 前端
- **PyQt6** — UI 框架
- **QListView + QStandardItemModel** — 搜尋結果網格
- **QThread** — 背景索引 / 搜尋

### 後端
- **CLIP (onnxruntime)** — 視覺向量化
- **PaddleOCR (onnxruntime)** — 文字辨識
- **FAISS** — 向量相似度搜尋
- **SQLite + WAL** — 索引存儲

### 工具
- **Qt Designer** 佈局（手工編寫）
- **subprocess** — 跨進程 IPC
- **ctypes** — Win32 原生呼叫

---

## 📚 延伸資源

### 設計文獻

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 目錄結構與職責
- [LAYERS.md](./LAYERS.md) — 各層邊界
- [DESIGN_PATTERNS.md](./DESIGN_PATTERNS.md) — 設計模式详解
- [CONTRIBUTION.md](./CONTRIBUTION.md) — 新增功能流程

### 模組文獻

- [MODULES_CORE.md](./MODULES_CORE.md) — 8 個核心模組
- [MODULES_UI.md](./MODULES_UI.md) — UI 控制器與 widgets
- [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) — SQLite 完整 schema

---

## 🔗 外部鏈接

- **GitHub 倉庫** — [gemini-rag-image](https://github.com/your-org/gemini-rag-image)
- **CLAUDE.md**（旋文件） — 架構精簡導航

---

*最後更新時間：Phase 3-F 完工後（Blur-main.py 主檔大拆分：6391→1398 行，32 個 class 提取為 12 個獨立模組）。後續若有新加模組或架構調整，請同步更新本文件。*

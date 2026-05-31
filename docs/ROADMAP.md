# ROADMAP.md — 重構戰績、已知 Bug、未來規劃

> 本文件記錄 EyeSeeMore 從 Phase 0 到未來的發展進程。

---

## 📊 Phase 1 + 2 + 3-A + 3-B + 3-C 重構戰績

### 代碼瘦身

| 指標 | 重構前 | 重構後 | 變化 |
|------|--------|--------|------|
| **`Blur-main.py` 總行數** | 7081 | ~6400 | **−681 行 (−9.6%)** |
| **`ImageSearchEngine`** | 1016 | ~650 | −366 行 |
| **`MainWindow` 估算** | ~1612 | ~1050 | −550+ 行 |
| **獨立模組總數** | 0 | 10 | +10 |

### 新增模組（9 個）

```
Phase 1 (資料存取與釘選)
└── 1-A: pin_manager.py          ← 圖片釘選
└── 1-B: ocr_repository.py       ← OCR 框 CRUD
└── 1-C: collection_manager.py   ← 虛擬資料夾

Phase 2 (UI 反饋與控制)
└── 2-A: search_history_manager.py    ← 搜尋歷史
└── 2-B: eta_progress_controller.py   ← ETA 進度 + PID
└── 2-C: indexing_lifecycle.py        ← 索引生命週期
└── 2-D: gallery_view_controller.py   ← 畫廊視圖
└── 2-E: window_state_manager.py      ← 視窗狀態 + Win32

Phase 3 (非阻塞模型加載 & 解耦 & UI 響應式)
└── 3-A: model_provider.py       ← 模型加載與共享【已完成】
└── 3-B: _on_models_loaded 優化  ← 畫廊圖片提早顯示【已完成】
└── 3-C: elided_label.py         ← TopBar 響應式寬度【已完成】
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

## 🎯 Phase 4 − 拆分 PreviewOverlay（計劃中）

### 目標

PreviewOverlay 是現存最臃腫的視圖元件（~690 行），負責：
- ✅ 圖片預覽
- ✅ OCR 框互動式裁切（CropController）
- ✅ 與 OCR 編輯器的協作

### 拆分方案

```
ui/preview/
├── base_preview_controller.py    ← 預覽控制器基類
├── crop_ocr_controller.py        ← OCR 裁切邏輯（~180 行）
└── ocr_box_editor.py             ← OCR 框編輯器（~150 行）
```

**預期成果：** PreviewOverlay 降至 ~300 行（純 UI 佈局 + 訊號連接）

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
- **性能優化** — FAISS GPU 加速、增量索引
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

*最後更新時間：Phase 3-C 完工後（TopBar 響應式寬度改進）。後續若有新加模組或架構調整，請同步更新本文件。*

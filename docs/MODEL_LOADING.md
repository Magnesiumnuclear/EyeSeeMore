# MODEL_LOADING.md — 模型加載、共享與啟動時序

> 這份文件只回答：AI 模型如何被加載、共享，並在不阻塞 UI 的前提下參與搜尋與索引。
> 不涵蓋完整索引流程；若要看索引三軌流程與資料表互動，請讀 INDEXER.md。

---

## 這份文件在回答什麼

1. 為什麼模型加載不能再卡住 IndexerWorker。
2. `model_provider.py` 在整體架構中的位置。
3. 啟動期間 UI、搜尋與索引如何和模型就緒狀態協調。

---

## 舊問題

舊架構的主要問題是：

1. IndexerWorker 會等待模型 ready，形成冷啟動阻塞。
2. 畫廊初始內容容易被模型完成後的 UI 重置覆蓋。
3. OCR 引擎初始化成本高，不適合啟動時一次全載。

---

## 新架構的核心角色

### `core/model_provider.py`

負責：

1. 在背景執行緒加載 CLIP 模型與 tokenizer。
2. 提供 ready/loading 狀態。
3. 發射模型加載完成或失敗訊號。
4. 以 Lazy Load 方式提供 OCR 引擎。

### `core/image_search_engine.py`

負責：

1. 委派模型相關生命週期給 ModelProvider。
2. 保持搜尋引擎與模型實例解耦。

### `core/workers.py` 與 `indexer.py`

負責：

1. 在模型尚未 ready 時先執行不依賴模型的掃描工作。
2. 在模型 ready 後再做向量化與 OCR 相關工作。

---

## 啟動時序

```text
t=0ms     MainWindow 建立
t+100ms   初始圖片結果可先顯示
t+150ms   背景執行緒啟動搜尋/索引相關載入
t+500ms   ModelProvider 背景加載模型
t+8000ms  models_loaded 發射，後續 AI 相關工作接手
```

設計重點是：

1. UI 可先顯示。
2. 掃描可先進行。
3. 模型完成後只補足 AI 能力，不應重置已穩定的 UI 狀態。

### 初始資料夾顯示與模型解耦（Phase 3-G）

初始畫廊內容由 `random_data_ready` 訊號觸發 `_on_initial_data_ready()`
（主執行緒），**在引擎資料就緒時立即**依 config 的 `default_startup_folder`
決定顯示哪個資料夾：

- `"ALL"`：顯示全部圖片。
- 特定資料夾 / `"col:{id}"` 虛擬資料夾：立即套用對應過濾。

關鍵在於：資料夾過濾只依賴 `engine.data_store`，與模型載入完全無關，
因此**不需等模型就緒**。`_on_models_loaded()` 不再重複套用資料夾過濾，
只負責刷新需要統計的 sidebar / collections。

這修正了兩個曾出現的症狀：

1. 初始顯示忽略 `default_startup_folder`，一律先顯示全部圖片。
2. 因資料夾切換被延到模型載入後，使用者誤以為「要先互動／模型才會加載」。
   （模型本來就自動在背景載入，與任何 UI 互動無關。）

---

## import 延後策略與 DLL 順序（Phase 3-G）

模型相關的重模組不在主檔頂層 import，而是延後到實際使用點，
讓 UI 出現前的 import 成本從約 1.07 秒降到約 0.2 秒
（冷開機另省 transformers 約 28 秒）：

| 模組 | import 時機 |
|------|-------------|
| `transformers`（Tokenizer） | `ModelProvider._load_models_impl()`（背景執行緒） |
| `faiss` / `ImageSearchEngine` | `MainWindow.load_engine()`（背景執行緒） |
| `indexer`（連帶 cv2 / onnx_ocr） | `IndexerWorker.run()` 內 lazy 建立 IndexerService |

### ⚠️ onnxruntime 的 DLL 順序約束

`import onnxruntime` **必須在任何 PyQt6 模組之前執行**——實測 PyQt6
先載入後，onnxruntime 的 pybind DLL 初始化必定失敗
（`ImportError: DLL load failed`）。因此 `Blur-main.py` 最頂端保留一行
`import onnxruntime` 作為順序保護，不可移除或移到 core/ui import 之後。
其餘重模組（faiss / cv2 / transformers / shapely）實測在 PyQt6 之後載入皆安全。

---

## 主要設計決策

### 1. 非阻塞優先

模型屬於高成本資源，不應作為主畫面可互動的前置條件。

### 2. 共享而非散落建立

模型實例由單一提供者管理，避免多處自行初始化導致狀態不一致。

### 3. Lazy Load OCR

只在需要某語言 OCR 時才初始化對應引擎，避免啟動時載入不必要成本。

### 4. UI 與模型狀態解耦

模型完成後可以刷新需要模型的部分，但不應無條件重置畫廊與瀏覽上下文。

---

## 什麼情況要改這份鏈路

1. 冷啟動時間明顯回升。
2. IndexerWorker 再次出現等待模型的阻塞行為。
3. 切換模型後的索引一致性規則要改。
4. OCR 初始化時機改變。

---

## 關聯文件

1. `INDEXER.md`：索引流程與背景工作。
2. `MODULES_CORE.md`：core 模組索引。
3. `PERFORMANCE_NOTES.md`：已完成優化與量化結果。
4. `ROADMAP.md`：尚未完成的模型與重索引相關規劃。

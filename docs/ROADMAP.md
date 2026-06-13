# ROADMAP.md — 未來規劃、優先級與風險

> 這份文件只回答：EyeSeeMore 接下來要做什麼、為什麼做、優先順序如何。
> 不涵蓋完整模組細節、已完成優化的技術設計或歷史長篇回顧；若要看已完成優化，請改讀 PERFORMANCE_NOTES.md、MODEL_LOADING.md 與各專題文件。

---

## 目前定位

EyeSeeMore 已完成 Phase 1 到 Phase 3-G 的主要重構與效能修復，現階段重點不再是把主程式拆模組，而是：

1. 補齊流程專題文件，讓 docs 與現況一致。
2. 穩定搜尋、索引、OCR 與 Win32 整合的長期維護成本。
3. 把已完成的成果從 roadmap 分流到功能文、模組文與效能筆記。

---

## 已完成里程碑摘要

### Phase 1 — 資料存取與釘選

1. `core/pin_manager.py`
2. `core/ocr_repository.py`
3. `core/collection_manager.py`

### Phase 2 — UI 反饋與控制

1. `core/search_history_manager.py`
2. `core/eta_progress_controller.py`
3. `core/indexing_lifecycle.py`
4. `ui/gallery_view_controller.py`
5. `ui/window_state_manager.py`

### Phase 3 — 主檔拆分、非阻塞模型與效能修正

1. `core/model_provider.py`
2. `core/image_search_engine.py`
3. `core/taskbar_controller.py`
4. `core/win_event_filters.py`
5. `core/workers.py`
6. `ui/gallery_model.py`
7. `ui/preview_overlay.py`
8. `ui/settings_dialog.py`
9. `ui/sidebar_widget.py`
10. `ui/widgets/empty_state.py`
11. `ui/widgets/feature_widgets.py`
12. `ui/widgets/image_delegate.py`
13. `ui/widgets/ocr_widgets.py`

### Phase 3-G — 快取統一、資料庫索引、import 瘦身與 FAISS 持久化

1. L2 縮圖快取路徑統一至 `core/paths.py`（修復 indexer 與 UI 的快取分裂）
2. `init_db()` 補上 `idx_ocr_file_id`、`idx_files_folder` 索引
3. 主檔頂層 import 瘦身與重模組延後（含 onnxruntime DLL 順序保護）
4. FAISS HNSW 索引磁碟快取
5. `benchmarks/` 效能測試套件（量測與優化驗收）

> 詳細完成紀錄與量化改善，統一維護於 PERFORMANCE_NOTES.md。

---

## 目前優先級

### P0 — 文件結構收斂

1. 將大型總表拆為索引文與專題文。
2. 讓 README、ROADMAP、CONTRIBUTION、MODULES_* 各自只承擔單一責任。
3. 補上搜尋流程、OCR 流程、Win32 整合等專題文（模型加載專題文已完成，見 MODEL_LOADING.md）。

### P1 — 功能鏈路文件補齊

> 模型加載與共享策略已由 `MODEL_LOADING.md` 涵蓋，以下為尚未產出者。

1. 搜尋查詢從輸入到結果顯示的完整文件。
2. OCR 推論、存取、編輯與 UI 顯示的完整文件。
3. Win32 原生整合與視窗狀態文件。

### P2 — 中期維護性改善

1. 釐清資料一致性與 migration 規則。
2. 讓模組索引文與專題文建立穩定交叉連結。
3. 補上更具體的測試與驗證文檔入口。

---

## 已知風險與待處理議題

### 1. 模型切換後的重索引一致性

- 現況：切換 CLIP 模型後，現有 embeddings 可能仍對應舊模型。
- 風險：搜尋品質與使用者預期不一致。
- 方向：建立明確的重新向量化流程與 UI 提示。

### 2. 搜尋歷史刪除持久化流程

- 現況：刪除歷史紀錄的 UI 與持久化行為曾經脫節。
- 風險：使用者誤以為刪除失敗或資料回滾。
- 方向：讓 UI 動作與 `search_history_manager` 的資料操作保持單一路徑。

### 3. Win32 整合的回歸成本

- 現況：置頂、最大化、標題列、事件過濾都與原生 API 緊密耦合。
- 風險：未來 UI 改版容易觸發平台專屬回歸。
- 方向：將 Win32 行為集中記錄於獨立專題文，降低知識分散。

---

## 下一階段建議產出

### 文件面

> 已完成項（`MODULES_CORE/UI.md` 索引化、`CONTRIBUTION.md` 收斂、新增 `MODEL_LOADING.md`）
> 已移至上方「已完成里程碑摘要」。以下僅保留尚未產出的專題文。

1. 新增 `WINDOW_INTEGRATION.md`（Win32、工作列、原生事件與視窗狀態整合）。
2. 新增 `OCR_FLOW.md`（OCR 推論、存取、編輯與 UI 顯示鏈路）。
3. 新增 `SEARCH_FLOW.md`（搜尋查詢從輸入到結果顯示的完整流程）。

### 程式面

1. 明確定義模型切換後的重索引觸發規則。
2. 建立更穩定的資料庫與向量索引一致性檢查。
3. 逐步把跨模組流程的驗證方式文件化。

---

## 文件維護規則

1. 這份文件只記錄未來規劃、優先級、風險與簡短里程碑摘要。
2. 若內容開始變成已完成技術詳解，應搬到對應專題文。
3. 若內容開始變成模組百科，應搬到模組索引文或功能流程文。

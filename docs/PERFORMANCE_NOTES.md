# PERFORMANCE_NOTES.md — 已完成優化、量測與設計取捨

> 這份文件只回答：已經完成的效能與互動優化是什麼、帶來什麼改善、設計取捨在哪裡。
> 不涵蓋未來優先級規劃；若要看接下來要做什麼，請改讀 ROADMAP.md。

---

## 收錄範圍

本文件集中維護下列已完成主題：

1. Phase 3-A 非阻塞模型加載。
2. Phase 3-B 啟動畫廊提早渲染。
3. Phase 3-C TopBar 響應式寬度改善。
4. Phase 3-D 啟動、索引與搜尋效能熱點修復。
5. Phase 3-E 畫廊互動渲染 quick wins。
6. Phase 3-F 主檔拆分成果摘要。
7. Phase 3-G 快取統一、資料庫索引、import 瘦身與 FAISS 持久化。
8. Phase 3-H 掃描階段優化與資料夾拆分任務。

---

## Phase 3-A — 非阻塞模型加載

### 問題

- 舊架構中，IndexerWorker 會等待模型 ready，造成冷啟動期間掃描與索引延遲。

### 解法

1. 引入 `core/model_provider.py` 作為模型加載與共享中心。
2. 將模型加載改成背景非阻塞流程。
3. OCR 引擎採 Lazy Load，需要時才初始化。

### 影響

1. IndexerWorker 不再被模型加載阻塞。
2. 使用者可先看到可互動的畫面，再等待模型完成。

---

## Phase 3-B — 啟動畫廊提早渲染

### 問題

- 模型完成後的 UI 重置會覆蓋先前已顯示的隨機圖像結果。

### 解法

1. `ALL` 模式保持先前的初始畫廊顯示，不因模型完成而重置。
2. 指定資料夾模式的過濾原本延到 `_on_models_loaded()` 才套用。

### 結果

1. 畫廊可在早期顯示，不再等模型完成才出現。
2. sidebar 與 collections 仍可在模型完成後正常刷新。

> **Phase 3-G 後續修正：** 上述「指定資料夾模式延到模型載入後才過濾」會造成
> 初始顯示忽略 `default_startup_folder`，且讓使用者誤以為要互動才會載入模型。
> 現已改由 `_on_initial_data_ready()` 在資料就緒時立即套用啟動資料夾，
> `_on_models_loaded()` 不再重複過濾。詳見 MODEL_LOADING.md「初始資料夾顯示與模型解耦」。

---

## Phase 3-C — TopBar 響應式寬度

### 問題

- 麵包屑與狀態列的長文字撐大最小視窗寬度。

### 解法

1. 新增 `ui/widgets/elided_label.py`。
2. 讓 `minimumSizeHint().width()` 可回傳 0。
3. 將搜尋膠囊最小寬度下修。

### 結果

1. 視窗可縮小到合理範圍。
2. 長文字透過省略與 tooltip 保留可讀性。

---

## Phase 3-D — 啟動、索引與搜尋熱點修復

### 問題清單

1. 啟動時對每張圖個別做檔案存在檢查。
2. 軌道 C 的 SQLite 查詢存在 N+1 round-trip。
3. 大量資料時仍固定使用暴力搜尋索引。

### 主要改動

1. `os.scandir` 預掃描父目錄，降低大量 syscall。
2. 批次 `IN` 查詢取代逐張查詢。
3. 超過 10,000 筆時切換 HNSW 搜尋索引。

### 量化改善摘要

| 類別 | 改善前 | 改善後 |
|------|--------|--------|
| 啟動 I/O（1 萬張，SSD） | 約 50ms | 約 5ms |
| 啟動 I/O（1 萬張，HDD） | 約 3000ms | 約 50ms |
| 軌道 C 查詢（100 張） | 200 次 round-trip | 2 次 round-trip |
| FAISS 搜尋（5 萬張） | 約 40ms | 約 3ms |
| FAISS 搜尋（20 萬張） | 約 160ms | 約 5ms |

### 設計取捨

1. HNSW 建構較慢，但只在啟動或重建索引時發生。
2. `efSearch=64` 在 recall 與延遲間取平衡。
3. 向量先做 L2 正規化，確保內積與 cosine 語義一致。

---

## Phase 3-E — 畫廊互動渲染 Quick Wins

### 核心調整

1. `on_limit_changed` 只截斷現有結果，不重跑 FAISS。
2. 排序改用 `layoutAboutToBeChanged/layoutChanged`，減少全量重設。
3. 移除 `processEvents()`，改以 `QTimer.singleShot(0, ...)` 避免重入。
4. `adjust_layout` 使用 `_last_layout` 快取避免無效 relayout。
5. `_ensure_icon_column` 以 class-level 旗標避免重複 schema 檢查。

### 結果

1. 切換 limit、排序、切換側欄與縮放視窗時更平順。
2. 排序閃爍、無效 setter 與額外 SQL 次數下降。

### 注意事項

1. 排序後若未維護 persistent index 映射，選取狀態可能偏移。
2. `_icon_column_ensured` 的共享前提是單一程序只操作同一 DB。

---

## Phase 3-F — 主檔拆分成果摘要

### 問題

- `Blur-main.py` 在拆分前仍承載大量與 MainWindow 無關的 class 定義，導致導覽困難與維護成本偏高。

### 成果摘要

| 指標 | 拆分前 | 拆分後 |
|------|--------|--------|
| `Blur-main.py` 行數 | 6391 行 | 1398 行 |
| `Blur-main.py` 中的 class 數 | 32 個 | 1 個 |
| 拆出的模組數 | 0 | 12+ |

### 拆出模組類型

1. 核心引擎與背景工作者。
2. 工作列與 Win32 原生整合。
3. 畫廊 model、預覽層、設定對話框、側邊欄。
4. 多個原子 widget 與繪製代理。

---

## Phase 3-G — 快取統一、資料庫索引、import 瘦身與 FAISS 持久化

### 問題清單

1. L2 縮圖快取路徑分裂：indexer 寫入 `<root>/.cache/thumbnails`，UI 的 ThumbnailLoader 以自身 `__file__` 計算而讀取 `ui/widgets/.cache/thumbnails`，54,136 張預產縮圖從未被 UI 命中，每張卡片首次顯示都退化成全圖解碼。
2. `init_db()` 未建立任何二級索引：`ocr_results` 缺 `file_id` 索引，導致 `files` 級聯刪除逐檔全表掃描、軌道 C 批查與預覽 OCR JOIN 全表掃描。
3. 主檔頂層 import 過重：`transformers`（冷 import 實測 28 秒）與 `faiss` 在主檔未使用仍被 import；`core/workers.py` 頂層 import indexer 連帶拉入 cv2 / onnxruntime / onnx_ocr。
4. FAISS HNSW 索引每次啟動從零重建（2 萬筆約 1 秒，隨量增長）。
5. 搜尋的資料夾過濾每次對全量 data_store 做 `os.path.normpath`。

### 主要改動

1. `core/paths.py` 新增 `CACHE_DIR / THUMBNAIL_CACHE_DIR / FAISS_CACHE_DIR`，indexer 與 ThumbnailLoader 共用；UI 端舊快取已遷移合併。
2. `init_db()` 新增 `idx_ocr_file_id`、`idx_files_folder` 兩個索引（冪等）。實測 `embeddings(model_name)` 索引反而拖慢 `update_folder_stats`，刻意不建。
3. 主檔頂層僅保留輕量模組；`ImageSearchEngine` 延後至 `load_engine()`（背景執行緒）import；`IndexerService` 延後至 `IndexerWorker.run()` 內 lazy 建立。
4. `build_faiss_index()` 對 HNSW 加入磁碟快取（`faiss.write_index` + 內容指紋驗證），指紋不符自動重建。
5. `load_data_from_db()` 為每筆資料預快取 `norm_path` 欄位，搜尋／過濾／釘選改用快取值；`rename_file` 與 `remove_folder_data` 同步維護。

### 量化改善摘要（實測，benchmarks/ 套件）

> **版本綁定（Phase 3-G 起的標準）：** benchmarks JSON 現會自動記錄
> `sysinfo.git_commit`。效能數據表上方應標註「基準 Commit → 優化 Commit」兩個短
> hash，讓每筆數據可回溯、可 `git bisect`。下表於版本綁定啟用前產生，故記為未追蹤。
>
> 基準 Commit：`未追蹤` → 優化 Commit：`未追蹤`

| 類別 | 改善前 | 改善後 |
|------|--------|--------|
| 級聯刪除 300 檔（8k 圖） | 約 1.05s | 約 3ms（363x） |
| 預覽 OCR 框查詢 200 次 | 約 660ms | 約 2ms（322x） |
| 主檔頂層 import（暖快取） | 1.07s | 0.20s（5.4x；冷啟動另省 transformers 28s） |
| HNSW 啟動建構（2 萬筆） | 約 1.2s 重建 | 約 32ms 載入（38x） |
| 資料夾過濾（2 萬筆/次） | 約 31ms | 約 1.7ms（18x） |
| 縮圖首次顯示（快取命中後） | 全圖解碼約 5.8ms/張 | WebP 載入約 0.6ms/張（9.4x） |

### 設計取捨與注意事項

1. **`import onnxruntime` 必須保留在主檔最頂端、任何 PyQt6 模組之前**：實測 PyQt6 先載入後 onnxruntime 的 DLL 初始化必定失敗。此行是 DLL 順序保護，不可移除或下移。
2. FAISS 快取指紋為「筆數 × 維度 × 內容雜湊」，向量任何增刪改（含順序變動）都會自動重建，不會出現索引與 data_store 錯位。
3. `data_store` 項目新增 `norm_path` 欄位後，任何改動 `path` 的程式碼都必須同步更新 `norm_path`。
4. 驗證方式：`benchmarks/run_all.py` 量測、`bench_db_indexes.py --check-real` 與 `bench_thumbnail_cache.py --check-dirs` 為 PASS/FAIL 驗收檢查。

---

## Phase 3-H — 掃描階段優化與資料夾拆分任務

### 掃描優化（`scan_for_new_files`，不改變分類語意）

1. 副檔名比對改 `str.endswith(tuple)`，省去每檔 `os.path.splitext` 字串配置。
2. 無資料夾啟用 OCR 時跳過載入整張 `ocr_results`；有需要也只撈相關語系。
3. 交叉比對走 `_match_folder_langs_norm`（輸入已正規化），免每張圖重複 normpath。
4. 缺尺寸 metadata 補齊改用執行緒池平行讀取（I/O 密集）。
5. 本次掃描無新增／補算／刪除／補欄位時，跳過 `update_folder_stats` 重建。

### 新增：資料夾拆分任務

- `split_into_folder_tasks()` 把多資料夾來源拆成「每頂層資料夾一個任務」（normpath 去重、
  巢狀歸併、保留子資料夾 OCR 語系），`scan_folder_task()` 逐任務掃描。
- 安全取捨：逐資料夾掃描以 `prune_missing=False` 執行，**不做**全庫刪除偵測，避免誤刪
  其他資料夾；失蹤檔清理仍走完整 config 的掃描。

> 行為與 API 細節以 INDEXER.md 為準（唯一真理源）。本次屬結構性／一次性成本優化，
> 量化基準待補：可先新增 `benchmarks/bench_scan.py` 量測後，再依下方標準格式補上數據表。
>
> 基準 Commit：`未量測` → 優化 Commit：`未量測`

### 向量建立路徑 baseline（profiling，優化尚未實作）

以 `benchmarks/bench_vectorize.py` 對 CLIP 向量建立路徑做基準剖析，得到一個**推翻直覺**的結論：

- 模型 image encoder 為**動態 batch 軸**（`['batch_size',3,224,224]`），可自由調大 batch。
- 但在本機 **DML GPU** 上，batch 1→16 的吞吐幾乎持平（每張推論約 38–58ms，~25 張/秒）——
  **調大 batch 在此環境幾乎不增吞吐**，原先「Tier 1：加大 batch」的假設被實測否定。
- 真正瓶頸是 **CPU 前處理**：「解碼+轉正+RGB+`NumpyPreprocess`」單張約為 GPU 推論的 **~3 倍**
  （其中 `NumpyPreprocess` 的 `cv2.resize(INTER_CUBIC)` 佔顯著比重）。目前 CPU、GPU **序列**執行。

→ 優化方向應改為:**多執行緒平行化 CPU 前處理 + CPU/GPU 管線化(pipelining)**，而非加大 batch。
（絕對數字隨機器/GPU 而異,故此處只記錄相對結論;量測機制與重現方式見 benchmarks/README.md
「向量建立量測」。實作優化後再以 baseline→optimized 對照補數據表。）

---

## 維護規則

1. 這份文件只收錄已完成的優化與量化結果。
2. 若某主題開始擴大成完整流程，應拆成獨立專題文。
3. 若內容是未來規劃，應回到 ROADMAP.md。
4. **效能數據表標準格式（版本綁定）：** 新增量化表時，於表格上方標註基準與優化
   Commit，commit hash 取自 benchmarks 報告 JSON 的 `sysinfo.git_commit`：

   > 基準 Commit：`abc1234` → 優化 Commit：`def5678`
   >
   > | 類別 | 改善前 | 改善後 |
   > |------|--------|--------|
   > | …    | …      | …      |

   這讓未來的效能紀錄都能精準對應程式碼版本，支援退化追蹤與 `git bisect`
   （量測與綁定機制見 benchmarks/README.md「Git 版本追蹤」）。

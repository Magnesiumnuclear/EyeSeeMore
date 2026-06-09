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

1. `_on_models_loaded()` 僅在指定資料夾模式下才重新套用過濾。
2. `ALL` 模式保持先前的初始畫廊顯示，不因模型完成而重置。

### 結果

1. 畫廊可在早期顯示，不再等模型完成才出現。
2. sidebar 與 collections 仍可在模型完成後正常刷新。

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

## 維護規則

1. 這份文件只收錄已完成的優化與量化結果。
2. 若某主題開始擴大成完整流程，應拆成獨立專題文。
3. 若內容是未來規劃，應回到 ROADMAP.md。

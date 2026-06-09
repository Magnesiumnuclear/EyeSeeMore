# MODULES_CORE.md — core 模組索引

> 這份文件只回答：core 層有哪些模組、各自負責什麼、什麼情境下應該去讀或修改它。
> 不涵蓋完整流程細節；若要看索引流程請讀 INDEXER.md，若要看模型加載請讀 MODEL_LOADING.md，若要看資料表設計請讀 DATABASE_SCHEMA.md。

---

## 如何使用這份索引

1. 先用 `LAYERS.md` 確認問題是否屬於 `core/`。
2. 再用下表找到最可能的模組。
3. 若問題跨越多個模組，改讀對應流程文，而不是把索引文當完整規格書。

---

## 基礎設施與入口模組

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `config_manager.py` | 管理 `config.json` 的載入、讀寫與合併 | 改設定欄位、啟動參數、預設值 | `ARCHITECTURE.md` |
| `paths.py` | 專案路徑常數中心 | 發現重複路徑計算、修正資源定位 | `ARCHITECTURE.md` |
| `win_titlebar.py` | 自訂標題列橋接 DLL | 調整原生標題列與 hit-test | 後續建議拆到 `WINDOW_INTEGRATION.md` |
| `search_orchestrator.py` | SearchWorker 的生命週期管理 | 搜尋取消、切換搜尋、worker 退役問題 | 後續建議拆到 `SEARCH_FLOW.md` |

---

## 資料與領域模組

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `pin_manager.py` | 釘選狀態切換與排序置頂 | 釘選行為錯誤、data store 參照問題 | `DESIGN_PATTERNS.md` |
| `ocr_repository.py` | OCR 結果 CRUD | OCR 編輯、儲存、框資料同步 | `DATABASE_SCHEMA.md` |
| `collection_manager.py` | 虛擬資料夾與集合項目管理 | 收藏夾、圖示、集合成員問題 | `DATABASE_SCHEMA.md` |
| `search_history_manager.py` | 搜尋歷史 JSON 與 MRU 行為 | 搜尋歷史新增、刪除、持久化 | `CONTRIBUTION.md` |

---

## 掃描、進度與生命週期模組

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `eta_progress_controller.py` | 掃描進度與 ETA 展示控制 | 進度條、ETA、平滑行為問題 | `DESIGN_PATTERNS.md` |
| `indexing_lifecycle.py` | 索引暫停、恢復、取消與 DB reload | 掃描完成後 UI 刷新、雙緩衝問題 | `INDEXER.md` |
| `model_provider.py` | 模型背景加載與共享 | 冷啟動、模型 ready、Lazy Load OCR | `MODEL_LOADING.md` |
| `workers.py` | QThread/QRunnable 工作者群 | 背景任務切分、執行緒協調 | `INDEXER.md` |

---

## 搜尋、AI 與平台整合模組

| 模組 | 主要責任 | 何時應該讀它 | 相關文件 |
|------|----------|--------------|----------|
| `image_search_engine.py` | CLIP、向量化、FAISS 搜尋與資料載入 | 搜尋品質、向量索引、引擎初始化 | `INDEXER.md` |
| `taskbar_controller.py` | Windows 工作列進度與狀態整合 | 工作列進度顯示、平台互動 | 後續建議拆到 `WINDOW_INTEGRATION.md` |
| `win_event_filters.py` | 原生事件過濾與 Jump List | Win32 訊息、快捷操作、外殼整合 | 後續建議拆到 `WINDOW_INTEGRATION.md` |
| `image_action_manager.py` | 圖片右鍵選單動作集中處理 | 檔案操作與 context menu 行為 | `MODULES_UI.md` |

---

## 快速判斷規則

### 先看 `core/` 模組索引的情況

1. 問題不需要直接操作 widget。
2. 修改涉及資料存取、向量搜尋、掃描、背景工作或平台橋接。
3. 修改可能影響資料一致性、執行緒或共享狀態。

### 不要只停留在索引文的情況

1. 你要理解完整的索引、模型加載或資料流。
2. 問題牽涉 `core/` 與 `ui/` 的互動鏈。
3. 你需要掌握設計取捨，而不是只知道檔名。

---

## 文件維護規則

1. 這份文件是索引，不是完整模組百科。
2. 每個模組只保留責任、入口與閱讀時機，不展開大量實作細節。
3. 若單一主題需要長篇說明，應拆到專題文，而不是繼續堆在這裡。

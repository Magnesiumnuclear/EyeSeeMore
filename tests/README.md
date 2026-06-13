# tests/ — 自動化測試套件

> 目的：把「手動測試容易遺漏」的回歸項目固定成可重複執行的測試，
> 特別涵蓋資料層、索引分類、以及近期修過的 bug（快取分裂、DB 索引、
> import 衛生與 DLL 順序、啟動資料夾顯示、FAISS 快取、norm_path）。
>
> 框架：Python 標準庫 `unittest`（**零額外依賴**，pytest 未安裝也能跑）。
> 所有測試都在暫存目錄操作，**絕不觸碰**專案的 `images.db`、`config.json` 與 `.cache`。

## 執行方式

```powershell
# 用專案的 Python（擇一存在者）
.venv\Scripts\python.exe run_tests.py            # 全部
.venv\Scripts\python.exe run_tests.py -v          # 顯示每個測試
.venv\Scripts\python.exe run_tests.py test_db_schema   # 只跑單一模組

# 或標準 unittest 探索
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```

`run_tests.py` 會自動把專案根目錄加入 `sys.path`，並先 `import onnxruntime`
（DLL 順序保護，必須早於任何 PyQt6）。

## 測試項目一覽

| 測試檔 | 涵蓋項目 | 對應修復 / 防護 |
|--------|----------|-----------------|
| `test_paths.py` | `CACHE_DIR / THUMBNAIL_CACHE_DIR / FAISS_CACHE_DIR` 位置與從屬關係、常數齊備 | 快取路徑統一 |
| `test_db_schema.py` | 建表齊全、`idx_ocr_file_id`/`idx_files_folder` 存在、**不**建 `idx_emb_model`、缺欄位遷移、級聯刪除 | Phase 3-G DB 索引 |
| `test_indexer_scan.py` | 三軌道分類（新圖/缺向量/缺 OCR）、磁碟消失檔刪除、無語系不進 OCR 軌 | 索引核心分流 |
| `test_pin_manager.py` | toggle / is_pinned / reload 持久化 / 釘選置頂去重 | 釘選資料層 |
| `test_ocr_repository.py` | upsert 合併、get、改文字（±2px 容忍）、刪框、未知檔處理 | OCR CRUD |
| `test_collection_manager.py` | 新增/重名拒絕、成員寫入取回、icon 冪等遷移、刪除級聯 | 虛擬資料夾 |
| `test_search_history_manager.py` | MRU 排序、去重、上限裁切、刪除、持久化、空字串忽略 | 搜尋歷史 |
| `test_config_manager.py` | 深層合併補預設、舊 `use_ocr`→`enabled_langs` 遷移、資料夾增刪、語系切換 | 設定載入（隔離真實 config） |
| `test_cache_path_consistency.py` | indexer 與 image_delegate 共用 `THUMBNAIL_CACHE_DIR`、不再以 `__file__` 自組 .cache | **快取分裂回歸** |
| `test_import_hygiene.py` | 全專案無 `Blur_main`、settings 從 core.workers 取 OCRImportWorker、onnxruntime 先於 PyQt6、主檔頂層無 transformers/faiss、workers 不頂層 import indexer | **import/DLL 回歸** |
| `test_search_engine.py` | FlatIP（≤1萬）、HNSW + 磁碟快取往返（指紋一致才命中、改內容即失效）、`load_data_from_db` 預快取 `norm_path` 並建索引 | Phase 3-G FAISS 快取 / norm_path |

目前共 **48 個測試案例**，整體執行約 1 秒。

## 撰寫新測試的慣例

1. 一律用暫存目錄/檔案，禁止寫入專案真實資料（`images.db` / `config.json` / `.cache`）。
2. 需要資料庫時用 `tests/_helpers.build_real_db()`（透過 `IndexerService.init_db()`
   建立，與正式 schema 同源，避免漂移）。
3. 需要重量級模組（faiss / onnxruntime / PyQt6）時，依賴 `tests/__init__.py`
   已先載入 onnxruntime 的 DLL 順序保護；QObject 測試請先取得 `QCoreApplication`。
4. 會改寫全域/類別旗標的（如 `CollectionManager._icon_column_ensured`）要在 `setUp` 重置。

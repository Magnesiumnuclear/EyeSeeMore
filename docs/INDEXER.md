# indexer.py 詳解

> 本文件專門說明 [indexer.py](../indexer.py) 的職責、資料流、資料表互動、效能設計與修改注意事項。

## 定位

[indexer.py](../indexer.py) 是 EyeSeeMore 的背景索引引擎，負責把磁碟上的圖片轉成可搜尋資料。

它的工作不是 UI，也不是搜尋排序；它只專注於以下流程：

1. 掃描來源資料夾中的圖片檔
2. 與 SQLite 現況比對，判斷哪些圖片需要新增、補算或刪除
3. 讀取圖片尺寸、EXIF 與檔案大小
4. 生成縮圖快取
5. 執行 CLIP 圖片向量化
6. 執行多語系 OCR
7. 把結果寫入資料庫與統計表

在整體架構中，它通常由主程式中的 IndexerWorker 於背景執行緒呼叫，但真正的索引邏輯集中在 [indexer.py](../indexer.py) 的 IndexerService。

## 模組結構

[indexer.py](../indexer.py) 可分成四個區塊：

| 區塊 | 內容 | 目的 |
|------|------|------|
| 影像輔助函式 | get_image_metadata、rotate_ocr_box、pil_to_rgb_safe | 處理 EXIF、透明通道與 OCR 座標基礎能力 |
| 預處理與快取 | NumpyPreprocess、generate_l2_cache | 為 CLIP 與 UI 縮圖建立低成本資料路徑 |
| 效能控制 | ENABLE_PROFILING、perf_print、optional_mem_profile | 讓效能觀測可開關，不污染正常流程 |
| 核心服務 | IndexerService | 負責 DB 初始化、掃描分類、AI 處理、模型載入、統計更新 |

## 外部依賴

[indexer.py](../indexer.py) 直接依賴以下能力：

- Pillow：圖片開啟、EXIF、旋轉修正、模式轉換
- NumPy：CLIP 前處理與 embedding 張量組裝
- OpenCV：高效 resize 與 BGR 轉換
- onnxruntime：執行 CLIP ONNX 推論
- [onnx_ocr.py](../onnx_ocr.py)：OCR 引擎包裝
- sqlite3：索引資料庫寫入與遷移

它也會讀取專案內的模型檔：

- models/onnx_clip/{model_name}_image.onnx

## IndexerService 核心責任

### 1. 初始化與效能參數

`IndexerService.__init__()` 會建立索引服務的執行環境：

- 記錄 `db_path`、`model_name`、`use_gpu_ocr`
- 檢查 ONNX Runtime 是否可使用 DirectML，決定 `device`
- 從 `perf_config` 讀取：
  - `indexing_batch_size`
  - `db_commit_threshold`

這兩個參數決定每次推論的批次大小與資料庫 commit 的節奏，是索引效能的重要旋鈕。

### 2. 建立資料庫連線

`_get_conn()` 是所有 DB 存取的共用入口，固定套用三個 pragma：

- `journal_mode=WAL`：允許前景讀與背景寫併行
- `synchronous=NORMAL`：降低同步成本
- `foreign_keys=ON`：確保關聯刪除與約束生效

此外，連線帶有 15 秒 timeout，用於承受背景索引與前景讀取同時進行時的鎖競爭。

### 3. 建表與遷移

`init_db()` 不只是建表，也承擔舊版資料庫升級責任。

它會建立或確認下列表存在：

- `files`
- `embeddings`
- `model_stats`
- `collections`
- `collection_items`
- `pinned`
- `ocr_results`

它也包含兩個 migration 行為：

1. 若 `files` 缺少 `width`、`height`、`file_size`，就補欄位
2. 若舊版 `ocr_text`、`ocr_data` 還殘留在 `files`，就嘗試移除

這代表 [indexer.py](../indexer.py) 同時是索引引擎與索引資料庫 schema 的守門人。

## 掃描階段：scan_for_new_files()

`scan_for_new_files(source_folders_config)` 的任務是「分類」，不是「做 AI」。

輸入是資料夾設定陣列，每個元素至少包含：

- `path`
- `enabled_langs`

輸出是五個值：

1. `files_full`：完全新圖，DB 裡沒有紀錄
2. `files_emb_only`：已有 files 資料，但缺當前模型的 CLIP embedding
3. `files_ocr_only`：已有基本資料與 embedding，但缺部分 OCR 語系
4. `deleted_count`：磁碟消失、已從 DB 刪除的檔案數
5. `folder_ocr_map`：資料夾到 OCR 語系的對應表

### 掃描流程

#### 1. 建立資料夾與語系對照

函式先把 `source_folders_config` 轉成 `folder_ocr_map`，格式為：

`資料夾絕對路徑 -> 啟用語系列表`

後續所有 OCR 決策都依賴這張表。

#### 2. 遍歷磁碟

它使用 `os.walk()` 遞迴掃描資料夾，蒐集以下副檔名：

- `.jpg`
- `.jpeg`
- `.png`
- `.webp`
- `.bmp`

結果存入 `disk_paths` 集合。

#### 3. 讀取資料庫現況

函式接著讀取三組資料：

- `files`：用來知道哪些檔案已存在於索引中
- `embeddings`：用來知道哪些檔案已有目前模型的 embedding
- `ocr_results`：用來知道每張圖哪些語系已完成 OCR

#### 4. 清理已刪檔案

若檔案存在於 DB 但已不在磁碟，就從 `files` 刪除。由於其他表有外鍵級聯，相關 embedding 與 OCR 記錄也會一併清掉。

#### 5. 分成三條待處理軌道

交叉比對後得到三類工作：

- `files_full`：新圖，需做完整流程
- `files_emb_only`：只缺 embedding，通常出現在切換模型後
- `files_ocr_only`：只缺 OCR 某些語系，通常出現在資料夾 OCR 設定變更後

#### 6. 補齊缺失 metadata

最後它會額外查一次 `files`，找出 `width` 或 `file_size` 為空的舊資料，重新讀圖補齊：

- 原始寬高
- EXIF orientation
- 視覺正確的寬高
- 檔案大小

這個步驟讓舊資料庫可以漸進升級，而不需要另開一次性 migration script。

## 路徑對應規則：_get_folder_ocr_setting()

`_get_folder_ocr_setting(path, folder_ocr_map)` 會找出某張圖應套用哪個資料夾的 OCR 設定。

規則是「最長前綴匹配」：

- 若巢狀資料夾都命中，使用更深層那個
- 若沒有命中，回傳空陣列

這使得父資料夾與子資料夾可以有不同 OCR 語系策略。

## AI 處理主流程：run_ai_processing()

`run_ai_processing()` 是 [indexer.py](../indexer.py) 的核心。它只處理 `scan_for_new_files()` 已分類好的工作，不重新做磁碟判斷。

### 輸入

- `files_full`
- `files_emb_only`
- `files_ocr_only`
- `folder_ocr_map`
- `progress_callback`
- `shared_model`
- `shared_preprocess`
- `shared_ocr_engines`

### 執行前準備

函式會：

1. 建立 DB 連線
2. 計算總工作量與目前進度
3. 建立 `commit_counter` 做 lazy commit
4. 優先使用來自主程式的共享 CLIP 模型；若沒有，再自行載入 ONNX 模型
5. 建立 OCR 引擎快取 dict，並透過 `ensure_ocr_engine()` 做 lazy load

這裡的設計重點是：CLIP 與 OCR 都盡量重用現有資源，避免每輪掃描都從零初始化。

## 三條處理軌道

### 軌道 A：Full AI

對象是 `files_full`，也就是完全新圖。

每批次會做以下事情：

1. 只讀一次硬碟圖片
2. 讀取 EXIF orientation 與原始尺寸
3. `ImageOps.exif_transpose()` 轉正圖片
4. 生成 L2 磁碟縮圖快取
5. `pil_to_rgb_safe()` 轉為 OCR 與 CLIP 都可用的 RGB
6. 寫入 `files`
7. 批次計算 CLIP embedding，寫入 `embeddings`
8. 依資料夾設定跑多語系 OCR，寫入 `ocr_results`

這條軌道是最完整也最昂貴的流程。

### 軌道 B：Fast CLIP

對象是 `files_emb_only`，也就是資料已存在、只缺當前模型 embedding 的圖片。

它不碰 OCR，只做：

1. 讀圖與 EXIF 轉正
2. 生成 L2 快取
3. 做 CLIP 前處理
4. 批次寫入 `embeddings`

這是模型切換後的大量補算路徑，因此被設計成最小成本。

### 軌道 C：Backfill OCR

對象是 `files_ocr_only`，也就是已有基本資料與 embedding、但缺部分 OCR 語系的圖片。

這條軌道有兩個重點：

1. 先用批次 SQL 取出 `path -> file_id` 與 `file_id -> done_langs`，避免 N+1 查詢
2. 只補缺少的語系，不重跑已存在的 OCR 結果

這條路徑專門處理設定變更後的「精準補算」。

## 影像處理細節

### EXIF 轉正

索引流程大量依賴 `ImageOps.exif_transpose()`，原因是：

- CLIP 看見的圖片方向必須與使用者視覺一致
- OCR 輸出的框座標也必須以視覺方向為基準
- `files.width`、`files.height` 要寫入使用者看到的實際方向

### 透明通道安全轉 RGB

`pil_to_rgb_safe()` 專門避免透明 PNG/WebP 在轉 RGB 時，透明像素被錯誤合成成黑底，進而污染：

- CLIP 向量
- OCR 輸入
- 視覺品質

目前策略是把透明像素合成到白色背景。

### L2 快取

`generate_l2_cache()` 會把圖片縮成最多 256x256，存進：

- `.cache/thumbnails/{md5(file_path)}.webp`

這不是索引正確性所必需，但對 UI 卡片預覽與後續載入延遲有幫助。

## CLIP 推論路徑

### NumpyPreprocess

`NumpyPreprocess` 取代傳統 PIL 管線，目的是降低 Python 端前處理開銷。

其步驟為：

1. 將 PIL Image 轉成 NumPy 陣列
2. 依短邊對齊 224 做縮放
3. 取中心裁切
4. 轉 float32、正規化、轉成 CHW

### _compute_clip()

`_compute_clip()` 的特點：

- 使用 `np.concatenate()` 聚合批次，不依賴 torch
- 用 ONNX Runtime 執行 image encoder
- 對輸出 embedding 做 L2 normalization
- 最後轉成 `float32.tobytes()`，直接存入 SQLite BLOB

## OCR 推論路徑

OCR 使用 [onnx_ocr.py](../onnx_ocr.py) 的 ONNXOCR 類別。

目前設計為 lazy load：

- 只有當某個語系真的需要時，才建立該語系 OCR engine
- engine 會保留在 `ocr_engines` dict 中供同一輪掃描重用

這是為了避免冷啟動時先把所有語系引擎都載進來，造成延遲與 VRAM 壓力。

## 寫入的資料表

[indexer.py](../indexer.py) 直接維護四張與索引最密切的表：

### files

每張圖一筆，包含：

- `file_path`
- `filename`
- `folder_path`
- `mtime`
- `width`
- `height`
- `file_size`

### embeddings

每張圖可對多個 `model_name` 各有一筆 embedding。

主鍵是：

- `(file_id, model_name)`

### ocr_results

每張圖可對多個語系各有多筆 OCR 結果，但現行流程基本上是每個 `file_id + lang` 寫一筆當前結果。

欄位包含：

- `lang`
- `ocr_text`
- `ocr_data`
- `confidence`

### model_stats

索引完成後，`update_folder_stats()` 會重建當前模型的每資料夾統計，用於 UI 顯示「這個資料夾已索引多少張」。

## 交易與效能設計

### Lazy commit

索引不是每處理一張就 commit，而是透過 `commit_threshold` 累積到一定數量才提交，最後再補一次保底 commit。

這可以顯著減少 SQLite transaction 開銷。

### WAL 模式

因為 UI 會同時讀資料庫，所以 `WAL` 是這支程式能在背景穩定跑索引的關鍵前提。

### 批次 SQL

軌道 C 刻意先批次拉出 id 與已完成語系，避免每張圖都再查一次資料庫。

### 單次讀圖，多重派送

軌道 A 的一個核心原則是：

- 一次開圖
- 同一份記憶體資料分派給 metadata、縮圖、CLIP、OCR

這能壓低磁碟 I/O 與重複 decode 成本。

## 與其他模組的邊界

[indexer.py](../indexer.py) 負責：

- 背景索引與資料寫入
- 圖片前處理與模型推論
- 索引資料庫結構初始化與局部 migration

它不負責：

- UI 狀態更新
- 掃描生命週期事件協調
- 搜尋排序與查詢 orchestration
- 畫廊刷新

這些通常由其他模組處理：

- 掃描生命週期：docs/MODULES_CORE.md 中的 indexing_lifecycle
- 搜尋流程：search_orchestrator 與主程式中的搜尋 worker
- UI 呈現：ui/ 與 Blur-main.py

## 修改 indexer.py 時的注意事項

### 1. 不要破壞三軌道分工

新增功能前先判斷它應進哪條軌道：

- 新圖完整流程：軌道 A
- 僅 embedding 補算：軌道 B
- 僅 OCR 補算：軌道 C

若把所有事都塞回 full scan，效能會明顯退化。

### 2. 保持 EXIF 一致性

任何新邏輯只要看圖像內容或存圖像座標，都應基於 `ImageOps.exif_transpose()` 之後的結果，否則：

- OCR 座標會歪
- embedding 會和畫面方向不一致
- 寬高可能錯置

### 3. 保持透明圖安全

若新增新的影像前處理步驟，不要直接 `convert('RGB')` 忽略透明度，否則透明 PNG 類圖片的內容可能被黑底污染。

### 4. 優先批次化

涉及 DB 查詢或 AI 推論時，應先找能否維持目前的批次模式，而不是對每張圖 individually 處理。

### 5. 小心 OCR engine 生命週期

程式內已有註解說明不要輕易清空 `ocr_engines`，特別是 DirectML 環境可能出現 GPU 狀態污染。

## 建議閱讀順序

如果你要修改 [indexer.py](../indexer.py)，建議順序如下：

1. 先讀本文件
2. 再讀 [docs/DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md)
3. 若牽涉掃描狀態與 UI 更新，再讀 [docs/MODULES_CORE.md](./MODULES_CORE.md)
4. 若牽涉整體分層，再讀 [docs/ARCHITECTURE.md](./ARCHITECTURE.md)

## 摘要

[indexer.py](../indexer.py) 是專案中最靠近「圖片進資料庫」的引擎層。它的本質不是單純掃描器，而是一個結合：

- 檔案系統差異比對
- 圖像前處理
- ONNX CLIP 推論
- 多語系 OCR
- SQLite 寫入與統計更新

的批次索引服務。

理解它時，最重要的是抓住兩個軸：

1. 先分類，再處理
2. 依工作型態拆成 A、B、C 三條軌道

掌握這兩點，後續無論是修 bug、加欄位、改 OCR 邏輯或做效能優化，都比較不容易破壞既有架構。
# DATABASE_SCHEMA.md — SQLite 資料庫完整 Schema

> SQLite 資料庫（`images.db`）是 EyeSeeMore 的索引下層。所有搜尋、篩選、釘選、虛擬資料夾都基於此資料庫建立。
> Schema 的唯一真理源是 `indexer.py` 的 `init_db()`（含冪等遷移）；本文件內容以其實際 DDL 為準。

---

## 完整 Schema

### 1. `files` — 圖片元資料主表

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE,               -- 絕對路徑
    filename TEXT,                       -- 檔案名稱
    folder_path TEXT,                    -- 所屬資料夾
    mtime REAL,                          -- 修改時間戳（用於變更檢測）
    width INTEGER,                       -- 圖片寬度（視覺方向，EXIF 轉正後）
    height INTEGER,                      -- 圖片高度（視覺方向，EXIF 轉正後）
    file_size INTEGER                    -- 檔案大小（bytes）
);

CREATE INDEX idx_files_folder ON files(folder_path);
```

**用途：** 存儲所有索引的圖片基本信息

**關鍵欄位：**
- `file_path` — UNIQUE 約束確保不重複索引（自動產生唯一索引）
- `mtime` — 用來偵測檔案是否被修改（增量索引）
- `width / height / file_size` — 舊資料庫缺欄位時由 `init_db()` 冪等補齊

**注意：** 舊版資料庫可能殘留 `is_pinned` 欄位（釘選功能已改由獨立的 `pinned` 表承載，此欄位不再使用）。縮圖不存在 DB，而是存於 `.cache/thumbnails/` 磁碟快取（見 INDEXER.md）。

---

### 2. `embeddings` — CLIP 向量表

```sql
CREATE TABLE embeddings (
    file_id INTEGER,
    model_name TEXT,                     -- 例："xlm-roberta-large-ViT-H-14"
    embedding BLOB,                      -- float32 向量（二進制，已 L2 正規化）
    PRIMARY KEY (file_id, model_name),
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);
```

**用途：** 儲存 CLIP 模型生成的圖片視覺向量

**特點：**
- 複合主鍵 `(file_id, model_name)`：每個圖片 + 模型組合一條向量，同一張圖可同時持有多個模型的向量
- BLOB 格式：numpy 的 float32 陣列序列化（indexer 寫入前已做 L2 正規化）
- 用於 FAISS 索引的相似度搜尋
- **刻意不建 `model_name` 索引**：實測它反而拖慢 `update_folder_stats` 的 GROUP BY JOIN，且掃描階段的過濾選擇度太低無益（詳見 PERFORMANCE_NOTES.md Phase 3-G）

**向量讀寫範例：**
```python
import numpy as np

# 寫入
embedding = np.array([0.1, 0.2, ...], dtype=np.float32)
conn.execute(
    "INSERT INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)",
    (file_id, "ViT-B/32", embedding.tobytes())
)

# 讀取
row = conn.execute("SELECT embedding FROM embeddings WHERE file_id = ?", (file_id,)).fetchone()
embedding = np.frombuffer(row[0], dtype=np.float32)
```

---

### 3. `ocr_results` — OCR 框資料

```sql
CREATE TABLE ocr_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    lang TEXT,                           -- 語言代碼，例："ch", "en", "japan"
    ocr_text TEXT,                       -- 整份文字（冗餘，用於搜尋）
    ocr_data TEXT,                       -- JSON 陣列（每框一筆，見下方格式）
    confidence REAL,                     -- 信心度 (0-1)
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX idx_ocr_file_id ON ocr_results(file_id);
```

**用途：** 儲存 PaddleOCR 辨識結果（每張圖片可有多語系辨識）

**資料格式（`ocr_data`）：**
```json
[
    {
        "box": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
        "text": "單行辨識文字",
        "conf": 0.95
    }
]
```

**場景：**
- 同一圖片可用多種語言 OCR（取決於各來源資料夾的 `enabled_langs` 設置）
- 每個 `(file_id, lang)` 組合由索引流程維持一筆當前結果（無 UNIQUE 約束，唯一性由軌道 C 的「缺哪國補哪國」邏輯保證）
- `ocr_text` 冗餘儲存整份文字方便全文搜尋
- `idx_ocr_file_id` 是級聯刪除與單圖查詢的關鍵索引：沒有它時，刪除 `files` 會對本表逐檔全表掃描（實測 8k 圖刪 300 檔 1.05s → 3ms，見 PERFORMANCE_NOTES.md Phase 3-G）

---

### 4. `pinned` — 釘選清單

```sql
CREATE TABLE pinned (
    file_path TEXT PRIMARY KEY           -- 釘選檔案的絕對路徑
);
```

**用途：** 記錄使用者釘選過的圖片

**特點：**
- 極簡設計：只存路徑，PRIMARY KEY 即唯一索引
- 釘選圖片在任何搜尋結果中永遠置頂（記憶體合併由 `pin_manager.py` 處理）

---

### 5. `collections` — 虛擬資料夾

```sql
CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,                    -- 集合名稱
    created_at REAL,                     -- 建立時間戳
    icon TEXT NOT NULL DEFAULT '🏷️'      -- emoji 圖示（由冪等遷移補欄位）
);
```

**用途：** 定義虛擬資料夾（使用者自訂的圖片分組）

**特點：**
- name 必須 UNIQUE（同一使用者不能有重名集合，自動產生唯一索引）
- `icon` 欄位由 `collection_manager.py` 的 `_ensure_icon_column()` 冪等遷移補上（Phase 1-C）

---

### 6. `collection_items` — 虛擬資料夾成員表

```sql
CREATE TABLE collection_items (
    collection_id INTEGER,
    file_path TEXT,                      -- 檔案絕對路徑
    PRIMARY KEY (collection_id, file_path),
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);
```

**用途：** 紀錄某集合包含哪些文件

**特點：**
- ON DELETE CASCADE：刪除集合時自動刪所有成員
- file_path 是「文字參照」而非 FK（因為可指向未索引的檔案或已刪檔案）
- 複合主鍵保證同一檔案在同一集合只能加一次

---

### 7. `model_stats` — 模型掃描統計

```sql
CREATE TABLE model_stats (
    model_name TEXT,                     -- 例："xlm-roberta-large-ViT-H-14"
    folder_path TEXT,                    -- 例："E:\Photos"
    image_count INTEGER,                 -- 該資料夾已索引的圖片數
    last_scanned TEXT,                   -- 最後掃描時間（datetime 字串）
    PRIMARY KEY (model_name, folder_path)
);
```

**用途：** 追蹤各模型在各資料夾的掃描進度（每次掃描結束由 `update_folder_stats()` 重建）

**相關場景：**
- 側邊欄顯示「這個資料夾已索引多少張」
- 模型切換：快速判斷哪些資料夾需重新向量化

---

## 資料流 Workflow

### 索引流程（`indexer.py`）

```
1. 掃描資料夾 → 取所有圖片路徑
   ↓
2. 對每張圖片：
   a. INSERT INTO files (file_path, folder_path, ...)
      → 取 ID
   b. CLIP 向量化 → INSERT INTO embeddings
   c. OCR 辨識 → INSERT INTO ocr_results
   d. 更新 model_stats
   ↓
3. 建立 FAISS 索引（聚集所有向量）
```

### 搜尋流程（`search_orchestrator.py` + FAISS）

```
1. 啟動時：load_data_from_db() 一次撈出 embeddings + files + ocr_text
   → 建立記憶體 data_store 與 FAISS 索引
   （≤10,000 筆用 IndexFlatIP；>10,000 筆用 IndexHNSWFlat，
     並以磁碟快取避免重建，見下方「FAISS 索引建立」）
   ↓
2. 使用者輸入搜尋詞
   ↓
3. 編碼搜尋查詢 (CLIP text encoder) → 向量
   ↓
4. faiss_index.search(query_vec, k)  → 返回 Top-k 候選
   ↓
5. 與 OCR / 檔名文字命中合併計分（資料來自記憶體 data_store，不再查 DB）
   ↓
6. GalleryViewController 過濾 + 排序 + 分頁
```

### 釘選流程（`pin_manager.py`）

```
1. 使用者點「釘選」按鈕
   ↓
2. PinManager.toggle(file_path)
   a. 檢查 pinned 表是否存在
   b. 存在 → DELETE；不存在 → INSERT
   c. 發訊號
   ↓
3. GalleryViewController 接收訊號
   ↓
4. 重新排序結果（釘選項置頂）
```

---

## WAL 模式與併發控制

### 為什麼用 WAL（Write-Ahead Logging）？

```python
# 所有 core/ 內的 DB 模組都使用此模式
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn
```

**優勢：**
| 模式 | 讀性能 | 寫性能 | 併發性 |
|------|---------|---------|-----------|
| DELETE (默認) | ✅ | ❌ 慢 | ❌ 競態嚴重 |
| **WAL** | ✅ | ✅ | ✅ 讀寫並行 |

**運作原理：**
- 寫操作先寫 `.wal` 日誌檔，再寫主 DB
- 讀操作可以從 `.wal` 和主 DB 的一致快照讀取
- 允許一個寫者 + 多個讀者並行

### timeout 參數

```python
sqlite3.connect(db_path, timeout=15.0)  # 15 秒
```

- 若 DB 被鎖定（另一進程在寫），等待最多 15 秒
- IndexerWorker 在背景索引時會持久化鎖定，必須給足夠 timeout

---

## FAISS 索引建立

實作位置：`core/image_search_engine.py` 的 `build_faiss_index()`。

### L2 正規化 + 內積 = Cosine 相似度

向量在 `indexer.py` 寫入 DB **之前**就已做 L2 正規化，因此引擎端直接用內積
（`METRIC_INNER_PRODUCT`）即等同 cosine 相似度，無需再正規化。

### 動態演算法選擇 + 磁碟快取（Phase 3-D / 3-G）

```python
HNSW_THRESHOLD = 10_000
if n > HNSW_THRESHOLD:
    # 先嘗試磁碟快取：指紋（筆數×維度×內容雜湊）一致就 read_index 直接載入
    index = self._load_cached_hnsw(embeddings_matrix)
    if index is None:
        index = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        index.add(embeddings_matrix.astype(np.float32))
        self._save_hnsw_cache(index, embeddings_matrix)   # faiss.write_index
    index.hnsw.efSearch = 64
else:
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings_matrix.astype(np.float32))
```

| 資料量 | 演算法 | 精度 | 啟動成本 |
|--------|--------|------|---------|
| ≤10,000 | IndexFlatIP（暴力） | 100% | 毫秒級，無需快取 |
| >10,000 | IndexHNSWFlat (M=32, efSearch=64) | ~98% | 重建秒級～分鐘級；命中 `.cache/faiss/` 快取時約 30ms |

**快取一致性：** 指紋對向量內容（含順序）敏感，embeddings 任何增刪改都會自動重建並覆寫快取，不會出現索引與 data_store 錯位。快取檔位於 `.cache/faiss/{model_name}.index` + `.meta`（路徑常數見 `core/paths.py`）。

---

## 常見查詢範例

### 取某資料夾的所有圖片

```sql
SELECT file_path, width, height, mtime
FROM files
WHERE folder_path = 'E:\Photos'
ORDER BY mtime DESC;
```

### 取某圖片的所有 OCR 結果

```sql
SELECT lang, ocr_text, ocr_data
FROM ocr_results
WHERE file_id = ?;
```

### 找出某集合內所有圖片

```sql
SELECT f.file_path, f.width, f.height
FROM collection_items ci
JOIN files f ON ci.file_path = f.file_path
WHERE ci.collection_id = ?;
```

### 釘選項永遠置頂

```sql
SELECT f.file_path, CASE WHEN p.file_path IS NOT NULL THEN 0 ELSE 1 END AS pin_priority
FROM files f
LEFT JOIN pinned p ON f.file_path = p.file_path
ORDER BY pin_priority, f.mtime DESC;
```

（實際程式中釘選置頂是在記憶體由 `pin_manager.merge_pinned_to_top()` 合併，不走 SQL。）

---

## 相關詳細文檔

- **核心模組（相關表操作）** → [MODULES_CORE.md](./MODULES_CORE.md)
  - `ocr_repository.py` — OCR 框 CRUD
  - `collection_manager.py` — 集合管理
  - `pin_manager.py` — 釘選
- **建制腳本參考** → [CONTRIBUTION.md](./CONTRIBUTION.md#背景服務獨立腳本)

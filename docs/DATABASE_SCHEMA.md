# DATABASE_SCHEMA.md — SQLite 資料庫完整 Schema

> SQLite 資料庫（`images.db`）是 EyeSeeMore 的索引下層。所有搜尋、篩選、釘選、虛擬資料夾都基於此資料庫建立。

---

## 完整 Schema

### 1. `files` — 圖片元資料主表

```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,      -- 絕對路徑
    folder_path TEXT NOT NULL,           -- 所屬資料夾
    filename TEXT NOT NULL,              -- 檔案名稱
    mtime REAL NOT NULL,                 -- 修改時間戳（用於變更檢測）
    width INTEGER,                       -- 圖片寬度（像素）
    height INTEGER,                      -- 圖片高度（像素）
    thumbnail BLOB                       -- 縮圖 (可選)
);

CREATE INDEX idx_files_folder_path ON files(folder_path);
CREATE INDEX idx_files_mtime ON files(mtime);
```

**用途：** 存儲所有索引的圖片基本信息

**關鍵欄位：**
- `file_path` — UNIQUE 約束確保不重複索引
- `mtime` — 用來偵測檔案是否被修改（增量索引）
- `thumbnail` — 可選的縮圖快取（節省重複解碼）

---

### 2. `embeddings` — CLIP 向量表

```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL UNIQUE,
    model_name TEXT NOT NULL,            -- 例："ViT-B/32", "ViT-L/14"
    embedding BLOB NOT NULL,             -- float32 向量（二進制）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX idx_embeddings_model ON embeddings(model_name);
```

**用途：** 儲存 CLIP 模型生成的圖片視覺向量

**特點：**
- 每個圖片 + 模型組合一條向量
- BLOB 格式：numpy 的 float32 陣列序列化
- 用於 FAISS 索引的相似度搜尋

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
    lang TEXT NOT NULL,                  -- 語言代碼，例："zh_TW", "en"
    ocr_text TEXT,                       -- 整份文字（冗餘，用於搜尋）
    ocr_data TEXT NOT NULL,              -- JSON 格式：{"boxes": [...]}
    confidence REAL,                     -- 平均信心度 (0-1)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    UNIQUE(file_id, lang)
);

CREATE INDEX idx_ocr_results_lang ON ocr_results(lang);
```

**用途：** 儲存 PaddleOCR 辨識結果（每張圖片可有多語系辨識）

**資料格式：**
```json
{
    "boxes": [
        {
            "text": "單個文字或詞",
            "bbox": [x1, y1, x2, y2],
            "confidence": 0.95
        },
        ...
    ],
    "page_height": 1080,
    "page_width": 1920
}
```

**場景：**
- 同一圖片可用多種語言 OCR（取決於 `auto_tasks_page.py` 的設置）
- UNIQUE 約束：每個（file_id, lang）組合只有一筆記錄
- ocr_text 冗餘儲存整份文字方便全文搜尋

---

### 4. `pinned` — 釘選清單

```sql
CREATE TABLE pinned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,      -- 釘選檔案的絕對路徑
    pinned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pinned_file_path ON pinned(file_path);
```

**用途：** 記錄使用者釘選過的圖片

**特點：**
- 簡單的黑名單表（不存一堆中繼資料）
- pinned_at 時間戳用於排序（最新釘選優先）
- 釘選圖片在任何搜尋結果中永遠置頂

---

### 5. `collections` — 虛擬資料夾

```sql
CREATE TABLE collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,           -- 集合名稱
    icon TEXT,                           -- 圖示 (可選，格式待定)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_collections_name ON collections(name);
```

**用途：** 定義虛擬資料夾（使用者自訂的圖片分組）

**特點：**
- name 必須 UNIQUE（同一使用者不能有重名集合）
- icon 欄位可選（Phase 1-C 配套冪等遷移）
- 與 collection_items 配套使用

---

### 6. `collection_items` — 虛擬資料夾成員表

```sql
CREATE TABLE collection_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,             -- 檔案絕對路徑
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
    UNIQUE(collection_id, file_path)
);

CREATE INDEX idx_collection_items_col_id ON collection_items(collection_id);
CREATE INDEX idx_collection_items_file_path ON collection_items(file_path);
```

**用途：** 紀錄某集合包含哪些文件

**特點：**
- ON DELETE CASCADE：刪除集合時自動刪所有成員
- file_path 是「文字參照」而非 FK（因為可指向未索引的檔案或已刪檔案）
- UNIQUE 約束：同一檔案在同一集合只能加一次

---

### 7. `model_stats` — 模型掃描統計

```sql
CREATE TABLE model_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,            -- 例："ViT-B/32"
    folder_path TEXT NOT NULL,           -- 例："E:\Photos"
    image_count INTEGER DEFAULT 0,       -- 該資料夾已索引的圖片數
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(model_name, folder_path)
);

CREATE INDEX idx_model_stats_model ON model_stats(model_name);
```

**用途：** 追蹤各模型在各資料夾的掃描進度

**相關場景：**
- 增量掃描：檢查是否有新檔案需索引
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
1. 使用者輸入搜尋詞
   ↓
2. 獲取 embeddings 表所有向量 → 建 FAISS 索引
   ↓
3. 編碼搜尋查詢 (CLIP text encoder) → 向量
   ↓
4. FAISS IndexFlatIP.search(query_vec, k=100)
   → 返回 Top-100 file_id
   ↓
5. JOIN files 表取檔案路徑、尺寸、修改時間
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

### L2 正規化 + IndexFlatIP（內積 = Cosine 相似度）

```python
# 從 embeddings 表取所有向量
embeddings = []
for row in conn.execute("SELECT embedding FROM embeddings"):
    vec = np.frombuffer(row[0], dtype=np.float32)
    embeddings.append(vec)

embeddings = np.array(embeddings)

# L2 正規化
from sklearn.preprocessing import normalize
embeddings_norm = normalize(embeddings, norm='l2')

# 建 FAISS 索引（內積等同於 cosine similarity）
import faiss
index = faiss.IndexFlatIP(embeddings.shape[1])
index.add(embeddings_norm)
```

**為什麼 L2 + IndexFlatIP？**
- 正規化後的 L2 距離 = cosine 相似度
- IndexFlatIP 直接計算內積（最快）
- 無需訓練，支援動態添加向量

**搜尋：**
```python
query_vec = clip_text_encoder(user_query)
query_vec = normalize([query_vec], norm='l2')[0]

distances, indices = index.search(query_vec.reshape(1, -1), k=100)
# indices: [file_id, file_id, ...]（按相似度遞減）
```

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
WHERE ci.collection_id = ?
ORDER BY ci.added_at DESC;
```

### 釘選項永遠置頂

```sql
SELECT f.file_path, CASE WHEN p.id IS NOT NULL THEN 0 ELSE 1 END AS pin_priority
FROM files f
LEFT JOIN pinned p ON f.file_path = p.file_path
ORDER BY pin_priority, f.mtime DESC;
```

---

## 相關詳細文檔

- **核心模組（相關表操作）** → [MODULES_CORE.md](./MODULES_CORE.md)
  - `ocr_repository.py` — OCR 框 CRUD
  - `collection_manager.py` — 集合管理
  - `pin_manager.py` — 釘選
- **建制腳本參考** → [CONTRIBUTION.md](./CONTRIBUTION.md#背景服務獨立腳本)

"""
bench_db_indexes.py — 資料庫索引效能驗證
==========================================
驗證目標（效能分析 P0-2：資料庫零二級索引）：

indexer.init_db() 未建立任何二級索引（DATABASE_SCHEMA.md 記載的索引從未實作），導致：
  1. 刪除 files 時 ON DELETE CASCADE 對 ocr_results「每刪一檔全表掃描一次」
  2. 軌道 C 的 `WHERE file_id IN (...)` 批查全表掃描
  3. get_ocr_data_by_path 的 JOIN（ocr_results.file_id）全表掃描
  4. update_folder_stats / remove_folder_data 的 folder_path 過濾全表掃描

本腳本在「暫存目錄」建立與 indexer.init_db() 完全相同 schema 的合成資料庫，
分別在「無索引（現況）」與「建議索引（優化後）」兩種狀態下量測上述操作，
證明加索引的效益。絕不觸碰真實 images.db（僅以唯讀模式檢查索引是否已建立）。

建議索引（優化內容）：
    CREATE INDEX IF NOT EXISTS idx_ocr_file_id  ON ocr_results(file_id);
    CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_path);

注意：曾評估 idx_emb_model ON embeddings(model_name)，但實測顯示它讓
update_folder_stats 的 GROUP BY JOIN 變慢（查詢計畫改走隨機讀），且
scan 階段的 model_name 過濾選擇度約 50%，索引無益 → 不建議建立。

用法：
    python bench_db_indexes.py [--files 20000] [--label baseline]
    python bench_db_indexes.py --check-real     # 只檢查真實 DB 是否已建立索引
"""

import argparse
import os
import random
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import (PROJECT_ROOT, print_speedup, print_table,
                          save_results, timeit)

MODEL_NAME = "xlm-roberta-large-ViT-H-14"
RECOMMENDED_INDEXES = [
    ("idx_ocr_file_id", "CREATE INDEX IF NOT EXISTS idx_ocr_file_id ON ocr_results(file_id)"),
    ("idx_files_folder", "CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_path)"),
]
# 評估後不建議：讓 update_folder_stats 變慢、scan 過濾選擇度太低無益
EVALUATED_NOT_RECOMMENDED = [
    ("idx_emb_model", "CREATE INDEX IF NOT EXISTS idx_emb_model ON embeddings(model_name)"),
]


def connect(db_path):
    """與 indexer._get_conn() 相同的連線設定。"""
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def build_synthetic_db(db_path, n_files):
    """建立與 indexer.init_db() 相同 schema 的合成資料庫。

    資料形狀模擬真實使用：8 個來源資料夾、每檔 1~2 個模型 embedding、
    每檔 0~2 個語系的 OCR 結果（ocr_data 約 500B JSON）。
    """
    conn = connect(db_path)
    cur = conn.cursor()
    # ── schema 與 indexer.init_db() 一致（無二級索引） ──
    cur.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE, filename TEXT, folder_path TEXT,
        mtime REAL, width INTEGER, height INTEGER, file_size INTEGER)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS embeddings (
        file_id INTEGER, model_name TEXT, embedding BLOB,
        PRIMARY KEY (file_id, model_name),
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS model_stats (
        model_name TEXT, folder_path TEXT, image_count INTEGER, last_scanned TEXT,
        PRIMARY KEY (model_name, folder_path))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS ocr_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL, lang TEXT, ocr_text TEXT, ocr_data TEXT,
        confidence REAL,
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE)''')

    rng = random.Random(42)
    folders = [f"D:\\photos\\folder_{i}" for i in range(8)]
    fake_emb = bytes(4096)  # 1024 維 float32
    fake_ocr_json = ('[{"box": [[10, 10], [200, 10], [200, 40], [10, 40]], '
                     '"text": "synthetic ocr line for benchmark", "conf": 0.97}]' * 3)

    files_rows, emb_rows, ocr_rows = [], [], []
    for i in range(n_files):
        folder = folders[i % len(folders)]
        path = f"{folder}\\img_{i:07d}.jpg"
        files_rows.append((path, f"img_{i:07d}.jpg", folder,
                           1700000000.0 + i, 1920, 1080, 500000 + i))
    cur.executemany(
        "INSERT INTO files (file_path, filename, folder_path, mtime, width, height, file_size) "
        "VALUES (?,?,?,?,?,?,?)", files_rows)

    cur.execute("SELECT id FROM files")
    ids = [r[0] for r in cur.fetchall()]
    for fid in ids:
        emb_rows.append((fid, MODEL_NAME, fake_emb))
        if fid % 2 == 0:  # 一半的圖還有第二個模型的向量
            emb_rows.append((fid, "ViT-B-32", fake_emb))
        n_langs = rng.choice((0, 1, 1, 2))
        for lang in ("ch", "en")[:n_langs]:
            ocr_rows.append((fid, lang, "synthetic ocr text for benchmark",
                             fake_ocr_json, 1.0))
    cur.executemany(
        "INSERT INTO embeddings (file_id, model_name, embedding) VALUES (?,?,?)", emb_rows)
    cur.executemany(
        "INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) "
        "VALUES (?,?,?,?,?)", ocr_rows)
    conn.commit()
    counts = {
        "files": len(files_rows),
        "embeddings": len(emb_rows),
        "ocr_results": len(ocr_rows),
    }
    conn.close()
    return counts


def apply_indexes(db_path):
    conn = connect(db_path)
    for _, sql in RECOMMENDED_INDEXES:
        conn.execute(sql)
    conn.commit()
    conn.close()


def drop_indexes(db_path):
    conn = connect(db_path)
    for name, _ in RECOMMENDED_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────
#  量測場景（皆以交易 + ROLLBACK 包裹寫入，保持資料不變可重複量測）
# ──────────────────────────────────────────────────────────
def scenario_cascade_delete(db_path, n_delete=300):
    """模擬掃描時清理已刪檔案：DELETE FROM files → 級聯刪 embeddings / ocr_results。"""
    conn = connect(db_path)
    paths = [r[0] for r in conn.execute(
        "SELECT file_path FROM files ORDER BY id LIMIT ?", (n_delete,))]

    def run():
        cur = conn.cursor()
        cur.execute("BEGIN")
        BATCH = 200
        for i in range(0, len(paths), BATCH):
            batch = paths[i:i + BATCH]
            ph = ",".join("?" * len(batch))
            cur.execute(f"DELETE FROM files WHERE file_path IN ({ph})", batch)
        conn.rollback()

    stats = timeit(run, repeat=3, warmup=1)
    conn.close()
    return stats


def scenario_track_c_lookup(db_path, n_batches=50, batch_size=4):
    """模擬軌道 C：批次 path→id 後，以 file_id IN (...) 查 ocr_results 已完成語系。"""
    conn = connect(db_path)
    all_paths = [r[0] for r in conn.execute(
        "SELECT file_path FROM files ORDER BY id LIMIT ?", (n_batches * batch_size,))]

    def run():
        cur = conn.cursor()
        for i in range(0, len(all_paths), batch_size):
            batch = all_paths[i:i + batch_size]
            ph = ",".join("?" * len(batch))
            cur.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({ph})", batch)
            ids = [r[1] for r in cur.fetchall()]
            ph_id = ",".join("?" * len(ids))
            cur.execute(f"SELECT file_id, lang FROM ocr_results WHERE file_id IN ({ph_id})", ids)
            cur.fetchall()

    stats = timeit(run, repeat=3, warmup=1)
    conn.close()
    return stats


def scenario_ocr_by_path(db_path, n_lookups=200):
    """模擬 OcrRepository.get_by_path：預覽圖時 JOIN 撈單張 OCR 框。"""
    conn = connect(db_path)
    paths = [r[0] for r in conn.execute(
        "SELECT file_path FROM files WHERE id % 37 = 0 LIMIT ?", (n_lookups,))]

    def run():
        cur = conn.cursor()
        for p in paths:
            cur.execute(
                "SELECT o.lang, o.ocr_data FROM ocr_results o "
                "JOIN files f ON o.file_id = f.id WHERE f.file_path = ?", (p,))
            cur.fetchall()

    stats = timeit(run, repeat=3, warmup=1)
    conn.close()
    return stats


def scenario_folder_stats(db_path):
    """模擬 update_folder_stats：每次掃描結束都會執行的統計重建。"""
    conn = connect(db_path)

    def run():
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM model_stats WHERE model_name = ?", (MODEL_NAME,))
        cur.execute("""
            INSERT INTO model_stats (model_name, folder_path, image_count, last_scanned)
            SELECT e.model_name, f.folder_path, COUNT(f.id), datetime('now', 'localtime')
            FROM files f JOIN embeddings e ON f.id = e.file_id
            WHERE e.model_name = ? GROUP BY f.folder_path
        """, (MODEL_NAME,))
        conn.rollback()

    stats = timeit(run, repeat=3, warmup=1)
    conn.close()
    return stats


def run_all_scenarios(db_path):
    return {
        "cascade_delete_300_files": scenario_cascade_delete(db_path),
        "track_c_lookup_50_batches": scenario_track_c_lookup(db_path),
        "ocr_get_by_path_200_lookups": scenario_ocr_by_path(db_path),
        "update_folder_stats": scenario_folder_stats(db_path),
    }


def check_real_db():
    """唯讀檢查真實 images.db 是否已建立建議索引（優化完成的驗收標準）。"""
    real_db = os.path.join(PROJECT_ROOT, "images.db")
    print("\n=== 真實資料庫索引檢查（唯讀） ===")
    if not os.path.exists(real_db):
        print("  images.db 不存在，略過。")
        return None
    conn = sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)
    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    all_ok = True
    status = {}
    for name, _ in RECOMMENDED_INDEXES:
        ok = name in existing
        status[name] = ok
        all_ok = all_ok and ok
        print(f"  {name:<22} {'PASS（已建立）' if ok else 'FAIL（缺失）'}")
    print(f"  結論: {'PASS — 索引優化已套用' if all_ok else 'FAIL — 尚未套用索引優化'}")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=20000, help="合成資料庫的 files 筆數")
    parser.add_argument("--label", default="baseline", help="結果標籤（baseline / optimized）")
    parser.add_argument("--check-real", action="store_true", help="只檢查真實 DB 索引狀態")
    args = parser.parse_args()

    if args.check_real:
        check_real_db()
        return

    with tempfile.TemporaryDirectory(prefix="esm_bench_db_") as tmp:
        db_path = os.path.join(tmp, "bench.db")
        print(f"建立合成資料庫（{args.files:,} files）...")
        counts = build_synthetic_db(db_path, args.files)
        print(f"  rows: {counts}")

        print("\n[第一輪] 無索引（= 目前 init_db() 的現況）")
        no_idx = run_all_scenarios(db_path)
        print_table("無索引", list(no_idx.items()))

        print("\n[第二輪] 套用建議索引")
        apply_indexes(db_path)
        with_idx = run_all_scenarios(db_path)
        print_table("有索引", list(with_idx.items()))

        print("\n=== 加速倍率 ===")
        metrics = {}
        for key in no_idx:
            metrics[f"{key}__no_index"] = no_idx[key]
            metrics[f"{key}__indexed"] = with_idx[key]
            print_speedup(key, no_idx[key], with_idx[key])

        real_status = check_real_db()
        save_results("db_indexes", args.label, metrics,
                     extra={"synthetic_rows": counts,
                            "real_db_index_status": real_status})


if __name__ == "__main__":
    main()

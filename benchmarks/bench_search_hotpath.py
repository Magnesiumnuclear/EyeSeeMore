"""
bench_search_hotpath.py — 搜尋熱路徑與 FAISS 索引效能驗證
============================================================
驗證目標（效能分析 P1-4 / P1-5）：

  P1-4  FAISS 索引每次啟動都從零重建（build_faiss_index）。
        HNSW 在 >10,000 筆時建構成本高（分鐘級），但搜尋只要毫秒級。
        → 優化：faiss.write_index() 持久化，啟動時 read_index() 直接載入。
        本腳本量測「重建 vs 載入」差距，證明持久化的效益。

  P1-5  search_hybrid 每次搜尋都做兩件 O(N) Python 迴圈：
        a. 全量子字串掃描 item["ocr_text"] / item["filename"]
        b. 資料夾過濾時對每筆做 os.path.normpath()
        → 優化：載入時預先快取 norm_path；文字掃描改 FTS5 或預建索引。
        本腳本量測這兩個迴圈的單次搜尋成本，與快取版的差距。

用法：
    python bench_search_hotpath.py [--items 50000] [--dim 1024] [--label baseline]
    python bench_search_hotpath.py --quick      # items=20000，較快
"""

import argparse
import os
import random
import string
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import (fmt_seconds, print_speedup, print_table,
                          save_results, timeit, timeit_once)

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False


def make_embeddings(n, dim, seed=42):
    rng = np.random.default_rng(seed)
    emb = rng.standard_normal((n, dim), dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    return emb


def make_data_store(n, seed=42):
    """模擬 load_data_from_db 後的 data_store 形狀。"""
    rng = random.Random(seed)
    folders = [f"D:\\photos\\folder_{i}" for i in range(8)]
    letters = string.ascii_lowercase + " "
    data = []
    for i in range(n):
        folder = folders[i % len(folders)]
        path = f"{folder}\\img_{i:07d}.jpg"
        data.append({
            "path": path,
            "filename": f"img_{i:07d}.jpg",
            "ocr_text": "".join(rng.choices(letters, k=200)),
            "mtime": 1700000000.0 + i,
            "width": 1920, "height": 1080,
        })
    return data


# ──────────────────────────────────────────────────────────
#  FAISS：重建 vs 持久化載入
# ──────────────────────────────────────────────────────────
def bench_faiss(emb, tmp_dir):
    dim = emb.shape[1]
    n = len(emb)
    metrics = {}
    query = emb[:1].copy()

    # IndexFlatIP（現況 ≤10k 筆時的路徑）
    flat = None

    def build_flat():
        nonlocal flat
        flat = faiss.IndexFlatIP(dim)
        flat.add(emb)

    metrics["faiss_flat_build"] = timeit_once(build_flat)
    metrics["faiss_flat_search_k1000"] = timeit(
        lambda: flat.search(query, min(1000, n)), repeat=20, warmup=3)

    # IndexHNSWFlat（現況 >10k 筆時「每次啟動」都要付的建構成本）
    hnsw = None

    def build_hnsw():
        nonlocal hnsw
        hnsw = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        hnsw.hnsw.efSearch = 64
        hnsw.add(emb)

    metrics["faiss_hnsw_build"] = timeit_once(build_hnsw)
    metrics["faiss_hnsw_search_k1000"] = timeit(
        lambda: hnsw.search(query, min(1000, n)), repeat=20, warmup=3)

    # 持久化（優化後啟動路徑：read_index 取代重建）
    idx_path = os.path.join(tmp_dir, "bench.faiss")
    metrics["faiss_write_index"] = timeit_once(
        lambda: faiss.write_index(hnsw, idx_path))
    metrics["faiss_read_index"] = timeit(
        lambda: faiss.read_index(idx_path), repeat=3, warmup=1)
    metrics_extra = {"index_file_mb": round(os.path.getsize(idx_path) / 1048576, 1)}

    print_table("FAISS（重建 vs 持久化）", list(metrics.items()))
    print_speedup("HNSW 重建 → read_index 載入",
                  metrics["faiss_hnsw_build"], metrics["faiss_read_index"])
    return metrics, metrics_extra


# ──────────────────────────────────────────────────────────
#  search_hybrid 的 O(N) Python 迴圈
# ──────────────────────────────────────────────────────────
def bench_text_scan(data_store):
    """與 search_hybrid 內的文字命中掃描完全相同的迴圈。"""
    query_lower = "qzx"  # 幾乎不命中 → 最壞情況（無 early exit）

    def scan():
        return [
            i for i, item in enumerate(data_store)
            if (query_lower in item["ocr_text"]) or (query_lower in item["filename"].lower())
        ]

    return timeit(scan, repeat=10, warmup=2)


def bench_folder_filter(data_store):
    """資料夾過濾：現況（每次 normpath）vs 優化（載入時預快取 norm_path）。"""
    target = os.path.normpath("D:\\photos\\folder_3")

    def current():
        return [
            i for i, item in enumerate(data_store)
            if os.path.normpath(item["path"]).startswith(target)
        ]

    stats_current = timeit(current, repeat=10, warmup=2)

    # 優化版：load_data_from_db 時一次算好 norm_path
    for item in data_store:
        item["norm_path"] = os.path.normpath(item["path"])

    def cached():
        return [
            i for i, item in enumerate(data_store)
            if item["norm_path"].startswith(target)
        ]

    stats_cached = timeit(cached, repeat=10, warmup=2)
    return stats_current, stats_cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=50000)
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--quick", action="store_true", help="items=20000 的快速模式")
    args = parser.parse_args()
    n = 20000 if args.quick else args.items

    print(f"產生 {n:,} 筆合成資料（dim={args.dim}）...")
    data_store = make_data_store(n)
    metrics = {}
    extra = {"items": n, "dim": args.dim}

    if HAS_FAISS:
        emb = make_embeddings(n, args.dim)
        with tempfile.TemporaryDirectory(prefix="esm_bench_faiss_") as tmp:
            faiss_metrics, faiss_extra = bench_faiss(emb, tmp)
        metrics.update(faiss_metrics)
        extra.update(faiss_extra)
        del emb
    else:
        print("[警告] faiss 未安裝，略過 FAISS 量測。")

    print("\n量測 search_hybrid 的 O(N) Python 迴圈...")
    metrics["text_scan_per_search"] = bench_text_scan(data_store)
    cur, cached = bench_folder_filter(data_store)
    metrics["folder_filter_normpath_per_search"] = cur
    metrics["folder_filter_cached_per_search"] = cached

    print_table("每次搜尋的 Python 迴圈成本", [
        ("text_scan_per_search（OCR+檔名子字串掃描）", metrics["text_scan_per_search"]),
        ("folder_filter（現況：每次 normpath）", cur),
        ("folder_filter（優化：預快取 norm_path）", cached),
    ])
    print_speedup("資料夾過濾 normpath → 預快取", cur, cached)

    save_results("search_hotpath", args.label, metrics, extra=extra)


if __name__ == "__main__":
    main()

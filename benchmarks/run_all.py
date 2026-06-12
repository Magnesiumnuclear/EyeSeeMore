"""
run_all.py — 一鍵執行全部效能測試
====================================
依序執行四個 bench 腳本，結果統一寫入 benchmarks/results/。

工作流程：
    1. 優化前：  python run_all.py --label baseline
    2. 套用優化（加索引 / 修快取路徑 / 刪頂層 import / FAISS 持久化）
    3. 優化後：  python run_all.py --label optimized
    4. 對照：    python compare.py --latest db_indexes
                python compare.py --latest search_hotpath
                python compare.py --latest thumbnail_cache
                python compare.py --latest startup_imports

用法：
    python run_all.py [--label baseline] [--quick]
"""

import argparse
import os
import subprocess
import sys

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--quick", action="store_true",
                        help="縮小資料規模以加快執行（趨勢不變）")
    args = parser.parse_args()

    jobs = [
        ["bench_db_indexes.py", "--label", args.label] +
        (["--files", "8000"] if args.quick else []),
        ["bench_search_hotpath.py", "--label", args.label] +
        (["--quick"] if args.quick else []),
        ["bench_thumbnail_cache.py", "--label", args.label],
        ["bench_startup_imports.py", "--label", args.label],
    ]

    failed = []
    for job in jobs:
        script = job[0]
        print(f"\n{'=' * 70}\n>>> {' '.join(job)}\n{'=' * 70}")
        proc = subprocess.run([sys.executable, os.path.join(BENCH_DIR, script)] + job[1:],
                              cwd=BENCH_DIR)
        if proc.returncode != 0:
            failed.append(script)

    print(f"\n{'=' * 70}")
    if failed:
        print(f"完成，但以下腳本失敗: {', '.join(failed)}")
        sys.exit(1)
    print(f"全部完成（label={args.label}）。結果位於 benchmarks/results/。")
    print("優化後請以 --label optimized 重跑，再用 compare.py 對照。")


if __name__ == "__main__":
    main()

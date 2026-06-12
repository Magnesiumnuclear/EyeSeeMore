"""
compare.py — 優化前後結果對照
================================
比較兩份 bench 結果 JSON（同一個 bench 的 baseline vs optimized），
逐指標印出耗時變化與加速倍率。

用法：
    python compare.py results\db_indexes_baseline_xxx.json results\db_indexes_optimized_yyy.json
    python compare.py --latest db_indexes            # 自動取該 bench 最新的兩份結果
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import RESULTS_DIR, fmt_seconds


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_latest_pair(bench_name):
    pattern = os.path.join(RESULTS_DIR, f"{bench_name}_*.json")
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    if len(files) < 2:
        print(f"[錯誤] {bench_name} 的結果不足兩份（找到 {len(files)} 份），"
              f"請先以不同 --label 跑兩次。")
        sys.exit(1)
    return files[-2], files[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="兩份結果 JSON 路徑（舊在前、新在後）")
    parser.add_argument("--latest", metavar="BENCH",
                        help="自動比較指定 bench 最新的兩份結果")
    args = parser.parse_args()

    if args.latest:
        old_path, new_path = find_latest_pair(args.latest)
    elif len(args.files) == 2:
        old_path, new_path = args.files
    else:
        parser.print_help()
        sys.exit(1)

    old, new = load(old_path), load(new_path)
    print(f"基準: {os.path.basename(old_path)}  (label={old['label']})")
    print(f"對照: {os.path.basename(new_path)}  (label={new['label']})")

    keys = [k for k in old["metrics"] if k in new["metrics"]]
    if not keys:
        print("[錯誤] 兩份結果沒有共同指標。")
        sys.exit(1)

    print(f"\n{'指標':<48} {'基準':>12} {'對照':>12} {'倍率':>8}")
    print("-" * 84)
    for key in keys:
        a = old["metrics"][key]["median"]
        b = new["metrics"][key]["median"]
        ratio = (a / b) if b > 0 else float("inf")
        marker = ""
        if ratio >= 1.3:
            marker = "  << 變快"
        elif ratio <= 0.77:
            marker = "  >> 變慢"
        print(f"{key:<48} {fmt_seconds(a):>12} {fmt_seconds(b):>12} {ratio:>7.2f}x{marker}")


if __name__ == "__main__":
    main()

"""
bench_common.py — 效能測試共用工具
====================================
提供計時、系統資訊、結果 JSON 寫入的共用基礎。

所有 bench_*.py 共用此模組。結果寫入 benchmarks/results/，
檔名格式：{bench}_{label}_{timestamp}.json，
供 compare.py 做「優化前 / 優化後」對照。
"""

import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BENCH_DIR)
RESULTS_DIR = os.path.join(BENCH_DIR, "results")


def timeit(fn, repeat=5, warmup=1):
    """重複執行 fn 並回傳統計（秒）。

    warmup 次數不列入統計，避免冷快取／JIT 干擾。
    回傳 dict: {"min", "mean", "median", "max", "repeat"}
    """
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return {
        "min": min(samples),
        "mean": statistics.fmean(samples),
        "median": statistics.median(samples),
        "max": max(samples),
        "repeat": repeat,
    }


def timeit_once(fn):
    """單次計時（用於建構類、不可重複的操作）。回傳與 timeit 相同結構。"""
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    return {"min": elapsed, "mean": elapsed, "median": elapsed, "max": elapsed, "repeat": 1}


def sysinfo():
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def save_results(bench_name, label, metrics, extra=None):
    """將量測結果寫入 results/ 目錄，回傳檔案路徑。

    metrics: {metric_key: stats_dict}，stats_dict 需含 median 欄位。
    """
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "bench": bench_name,
        "label": label,
        "timestamp": ts,
        "sysinfo": sysinfo(),
        "metrics": metrics,
    }
    if extra:
        payload["extra"] = extra
    path = os.path.join(RESULTS_DIR, f"{bench_name}_{label}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[結果已存檔] {path}")
    return path


def fmt_seconds(s):
    if s >= 1.0:
        return f"{s:9.3f} s "
    return f"{s * 1000:9.2f} ms"


def print_table(title, rows):
    """rows: list of (name, stats_dict)。"""
    print(f"\n=== {title} ===")
    for name, val in rows:
        if isinstance(val, dict):
            print(f"  {name:<48} median={fmt_seconds(val['median'])}  min={fmt_seconds(val['min'])}")
        else:
            print(f"  {name:<48} {fmt_seconds(val)}")


def print_speedup(title, before, after):
    """印出兩個 stats_dict 的加速倍率。"""
    if after["median"] > 0:
        ratio = before["median"] / after["median"]
        print(f"  >> {title}: {ratio:,.1f}x 加速 "
              f"({fmt_seconds(before['median']).strip()} -> {fmt_seconds(after['median']).strip()})")

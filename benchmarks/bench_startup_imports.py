"""
bench_startup_imports.py — 啟動 import 成本量測
==================================================
驗證目標（效能分析 P0-3：主檔頂層 import 過重）：

  Blur-main.py 頂層 import 了多個重量級函式庫，全部在第一個視窗
  出現之前付費，其中部分（transformers.AutoTokenizer、faiss）在
  主檔中根本沒有使用：

    from transformers import AutoTokenizer   # 未使用（ModelProvider 才需要）
    import faiss                              # 未使用（engine 內部才需要）
    from indexer import IndexerService        # 連帶拉入 cv2 / onnxruntime /
                                              # psutil / onnx_ocr → shapely / pyclipper

本腳本做兩件事：
  1. 在「全新子行程」中逐一量測各重量級模組的 import 時間
     → 看出每個頂層 import 的真實成本。
  2. 以 AST 解析 Blur-main.py 的「實際頂層 import 清單」，
     在全新子行程中整批執行並計時 → 這就是 UI 出現前必付的 import 總成本。
     優化（刪除/延後 import）後重跑，同一指標直接反映改善。

用法：
    python bench_startup_imports.py [--label baseline]
"""

import argparse
import ast
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench_common import PROJECT_ROOT, fmt_seconds, save_results

HEAVY_MODULES = [
    "numpy",
    "PIL.Image",
    "cv2",
    "onnxruntime",
    "faiss",
    "transformers",
    "PyQt6.QtWidgets",
    "shapely.geometry",
    "psutil",
    "indexer",   # 專案模組：間接拉入 cv2 / onnxruntime / onnx_ocr
]


def time_import_in_subprocess(stmt, cwd):
    """在全新 Python 子行程中執行 import 敘述並回傳耗時（秒）。

    顯式把專案根目錄插入 sys.path：embedded Python（含 ._pth）
    不會自動把工作目錄加入搜尋路徑，否則 import indexer 會失敗。
    """
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {cwd!r})\n"
        "t0 = time.perf_counter()\n"
        f"{stmt}\n"
        "print(time.perf_counter() - t0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=cwd, timeout=300,
    )
    if proc.returncode != 0:
        return None, proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
    try:
        return float(proc.stdout.strip().splitlines()[-1]), None
    except ValueError:
        return None, "無法解析輸出"


def extract_top_level_imports(py_path):
    """以 AST 抽出檔案最頂層的 import 敘述原文（不含 if/函式內的）。"""
    with open(py_path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    stmts = []
    for node in tree.body:  # 只看 Module.body 的直接子節點
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            seg = ast.get_source_segment(source, node)
            if seg:
                stmts.append(seg)
    return stmts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()

    metrics = {}

    # ── 1. 各重量級模組逐一量測（全新子行程 = 冷 import） ──
    print("=== 各重量級模組冷 import 時間（每個都在全新子行程） ===")
    for mod in HEAVY_MODULES:
        elapsed, err = time_import_in_subprocess(f"import {mod}", cwd=PROJECT_ROOT)
        if elapsed is None:
            print(f"  {mod:<24} 失敗: {err}")
        else:
            print(f"  {mod:<24} {fmt_seconds(elapsed)}")
            metrics[f"import_{mod}"] = {
                "min": elapsed, "mean": elapsed, "median": elapsed,
                "max": elapsed, "repeat": 1,
            }

    # ── 2. Blur-main.py 實際頂層 import 整批計時 ──
    main_file = os.path.join(PROJECT_ROOT, "Blur-main.py")
    stmts = extract_top_level_imports(main_file)
    print(f"\n=== Blur-main.py 頂層 import 整批計時（共 {len(stmts)} 條敘述） ===")
    combined = "\n".join(stmts)
    elapsed, err = time_import_in_subprocess(combined, cwd=PROJECT_ROOT)
    if elapsed is None:
        print(f"  失敗: {err}")
    else:
        print(f"  UI 出現前必付的 import 總成本: {fmt_seconds(elapsed)}")
        metrics["blur_main_top_level_imports"] = {
            "min": elapsed, "mean": elapsed, "median": elapsed,
            "max": elapsed, "repeat": 1,
        }

    save_results("startup_imports", args.label, metrics,
                 extra={"top_level_import_count": len(stmts)})


if __name__ == "__main__":
    main()

"""一鍵執行全部自動化測試。

用法（用專案的 Python）：
    .venv\\Scripts\\python.exe run_tests.py            # 全部
    .venv\\Scripts\\python.exe run_tests.py -v          # 顯示每個測試
    .venv\\Scripts\\python.exe run_tests.py test_db_schema   # 只跑單一模組

等同於 `python -m unittest discover -s tests -t .`，但額外做兩件事：
  1. 把專案根目錄插入 sys.path（embedded Python 不會自動加入 cwd）。
  2. 先 import onnxruntime（DLL 順序保護，必須早於任何 PyQt6）。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import onnxruntime  # noqa: F401  DLL 順序保護
except Exception as e:  # pragma: no cover
    print(f"[warn] onnxruntime 載入失敗，部分測試可能 skip: {e}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbosity = 2 if ("-v" in sys.argv or "--verbose" in sys.argv) else 1
    loader = unittest.TestLoader()
    if args:
        names = [a if a.startswith("tests.") else f"tests.{a}" for a in args]
        suite = loader.loadTestsFromNames(names)
    else:
        suite = loader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()

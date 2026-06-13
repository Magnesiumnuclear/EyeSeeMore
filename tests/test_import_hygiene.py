"""回歸：import 衛生與 DLL 載入順序（防止這幾輪修過的問題復發）。

涵蓋：
  • 全專案無 `Blur_main`（含連字號的主檔無法 import，曾導致設定頁崩潰）
  • settings_dialog 從 core.workers 取得 OCRImportWorker
  • Blur-main.py 的 onnxruntime 必須在任何 PyQt6 / core / ui import 之前
  • Blur-main.py 頂層不得 import 重量級且未使用的 transformers / faiss
  • core/workers.py 頂層不得 import indexer（已改為 run() 內 lazy 建立）
"""

import ast
import os
import re
import unittest

from tests import _helpers

ROOT = _helpers.PROJECT_ROOT
SKIP_DIRS = {".venv", ".venv-onnx", "User_Environment", "__pycache__",
             ".git", "node_modules", "build", "tests"}


def _iter_project_py():
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if fn.endswith(".py"):
                yield os.path.join(dp, fn)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _top_level_imports(src):
    """回傳 [(lineno, module_or_name), ...]，只看模組頂層的 import。"""
    out = []
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((node.lineno, a.name))
        elif isinstance(node, ast.ImportFrom):
            out.append((node.lineno, node.module or ""))
    return out


class TestImportHygiene(unittest.TestCase):
    def test_no_blur_main_references(self):
        offenders = [os.path.relpath(p, ROOT) for p in _iter_project_py()
                     if re.search(r"\bBlur_main\b", _read(p))]
        self.assertEqual(offenders, [], f"仍有 Blur_main 引用: {offenders}")

    def test_settings_dialog_imports_from_core_workers(self):
        src = _read(os.path.join(ROOT, "ui", "settings_dialog.py"))
        self.assertIn("from core.workers import OCRImportWorker", src)
        self.assertNotIn("from Blur_main", src)

    def test_onnxruntime_before_pyqt_in_main(self):
        imports = _top_level_imports(_read(os.path.join(ROOT, "Blur-main.py")))
        onnx = [ln for ln, m in imports if m == "onnxruntime"]
        heavy = [ln for ln, m in imports
                 if m.startswith("PyQt6") or m.startswith("core.") or m.startswith("ui.")]
        self.assertTrue(onnx, "Blur-main.py 頂層未 import onnxruntime（DLL 順序保護遺失）")
        self.assertTrue(heavy, "Blur-main.py 應有 PyQt6/core/ui import")
        self.assertLess(min(onnx), min(heavy),
                        "onnxruntime 必須在任何 PyQt6/core/ui import 之前")

    def test_main_top_level_has_no_unused_heavy_imports(self):
        mods = {m for _ln, m in _top_level_imports(_read(os.path.join(ROOT, "Blur-main.py")))}
        self.assertNotIn("transformers", mods, "transformers 不應在主檔頂層 import")
        self.assertNotIn("faiss", mods, "faiss 不應在主檔頂層 import")

    def test_workers_does_not_import_indexer_at_top(self):
        mods = {m for _ln, m in _top_level_imports(
            _read(os.path.join(ROOT, "core", "workers.py")))}
        self.assertNotIn("indexer", mods,
                         "core/workers.py 不應在頂層 import indexer（應 run() 內 lazy）")


if __name__ == "__main__":
    unittest.main()

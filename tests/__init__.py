"""EyeSeeMore 自動化測試套件。

⚠️ DLL 順序保護：onnxruntime 必須在任何 PyQt6 模組之前 import
（與 Blur-main.py 相同的約束，否則 onnxruntime 的 pybind DLL 初始化會失敗）。
測試行程一律先在此載入 onnxruntime，確保後續任何測試 import core/ui 都安全。
"""

try:
    import onnxruntime  # noqa: F401
except Exception:  # pragma: no cover - 環境缺 onnxruntime 時讓個別測試自行 skip
    pass

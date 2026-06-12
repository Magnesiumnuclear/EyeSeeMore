"""
EyeSeeMore — Entry Point
========================
由於主程式檔名含有連字號 (Blur-main.py)，無法直接 import，
故透過 runpy.run_path() 啟動。
"""
import os
import runpy
import sys

if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    # embedded Python（._pth 隔離模式）不會自動把腳本目錄加入 sys.path，
    # 需顯式插入專案根目錄，core/ui 等套件才找得到
    if root not in sys.path:
        sys.path.insert(0, root)
    runpy.run_path(os.path.join(root, "Blur-main.py"), run_name="__main__")

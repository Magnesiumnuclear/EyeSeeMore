"""
EyeSeeMore — Entry Point
========================
由於主程式檔名含有連字號 (Blur-main.py)，無法直接 import，
故透過 runpy.run_path() 啟動。
"""
import os
import runpy

if __name__ == "__main__":
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Blur-main.py")
    runpy.run_path(script, run_name="__main__")

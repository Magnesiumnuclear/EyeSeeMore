"""
core/paths.py  –  專案路徑常數中心
======================================
所有子模組應從這裡匯入路徑常數，避免各自計算 __file__ 層數。

目錄結構假設：
    <project_root>/
    ├── core/
    │   └── paths.py   ← 此檔案
    ├── ui/
    ├── utils/
    ├── models/
    ├── languages/
    ├── themes/
    └── config.json
"""

import os

# core/paths.py 位於 <root>/core/，向上一層即為根目錄
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS_DIR       = os.path.join(BASE_DIR, "models")
LANGS_DIR        = os.path.join(BASE_DIR, "languages")
THEMES_DIR       = os.path.join(BASE_DIR, "themes")
CONFIG_PATH      = os.path.join(BASE_DIR, "config.json")
DB_PATH          = os.path.join(BASE_DIR, "images.db")

# 快取路徑：indexer（寫入端）與 UI ThumbnailLoader（讀取端）必須共用同一目錄，
# 各自以 __file__ 計算會導致快取分裂（indexer 在根目錄、UI 在 ui/widgets/）
CACHE_DIR           = os.path.join(BASE_DIR, ".cache")
THUMBNAIL_CACHE_DIR = os.path.join(CACHE_DIR, "thumbnails")
FAISS_CACHE_DIR     = os.path.join(CACHE_DIR, "faiss")

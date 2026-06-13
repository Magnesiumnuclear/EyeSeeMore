"""測試共用工具：暫存 DB / schema 建立 / 小圖產生。

所有 DB 測試都在暫存目錄操作，**絕不觸碰專案的 images.db 與 .cache**。
schema 一律透過 IndexerService.init_db() 建立，與正式環境同源，避免 schema 漂移。
"""

import os
import sqlite3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_real_db(db_path, model_name="TESTMODEL"):
    """以 IndexerService.init_db() 建立與正式環境一致的 schema，回傳 service。"""
    from indexer import IndexerService
    svc = IndexerService(db_path=db_path, model_name=model_name)
    conn = svc.init_db()
    conn.close()
    return svc


def connect(db_path, foreign_keys=True):
    """測試用連線（預設開啟 foreign_keys 以驗證 cascade 行為）。"""
    conn = sqlite3.connect(db_path, timeout=15.0)
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def make_tiny_png(path, size=(8, 8), color=(123, 200, 50)):
    """產生一張可被 PIL/解碼器正常開啟的小 PNG。"""
    from PIL import Image
    Image.new("RGB", size, color).save(path, "PNG")


def insert_file(conn, file_path, folder=None, mtime=1700000000.0, with_meta=False):
    """插入一筆 files 記錄，回傳 file id。"""
    folder = folder if folder is not None else os.path.dirname(file_path)
    if with_meta:
        cur = conn.execute(
            "INSERT INTO files (file_path, filename, folder_path, mtime, width, height, file_size)"
            " VALUES (?,?,?,?,?,?,?)",
            (file_path, os.path.basename(file_path), folder, mtime, 8, 8, 100),
        )
    else:
        cur = conn.execute(
            "INSERT INTO files (file_path, filename, folder_path, mtime) VALUES (?,?,?,?)",
            (file_path, os.path.basename(file_path), folder, mtime),
        )
    return cur.lastrowid

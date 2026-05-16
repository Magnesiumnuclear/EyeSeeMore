"""
PinManager  –  圖片釘選 (Pinning) 功能管理器
================================================
從 ImageSearchEngine 抽離的職責：
  • pinned 資料表的 CRUD 操作（INSERT / DELETE / SELECT）
  • 釘選路徑的記憶體快取 (pinned_paths set)
  • 將釘選圖片以「合併去重」方式置頂至搜尋結果

設計原則：
  • 零 PyQt 依賴，純 Python + sqlite3
  • 依賴注入：db_conn_factory / data_store_provider
  • data_store 採 callable 模式，避免持有過期參照
    （ImageSearchEngine.load_data_from_db() 會重新指派 data_store，
     若直接持有 list 參照會出現舊資料）

使用方式：
    pin_mgr = PinManager(
        db_path=config.db_path,
        db_conn_factory=engine.get_db_conn,           # 共用 WAL 連線工廠
        data_store_provider=lambda: engine.data_store, # 動態取得最新 data_store
    )
    pin_mgr.reload()                       # 載入快取
    pin_mgr.toggle("D:/path/to/img.jpg")   # 切換釘選
    results = pin_mgr.merge_pinned_to_top(search_results)
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Callable, Dict, List


class PinManager:
    """圖片釘選功能的獨立管理器。

    負責維護 SQLite `pinned` 資料表與記憶體快取 (set) 的同步，
    並提供將釘選圖片置頂至搜尋結果的合併工具。
    """

    def __init__(
        self,
        db_path: str,
        db_conn_factory: Callable[[], sqlite3.Connection],
        data_store_provider: Callable[[], List[Dict[str, Any]]],
    ) -> None:
        """建立 PinManager 實例。

        Args:
            db_path: SQLite 資料庫的絕對路徑，用於 reload 時的存在性檢查。
            db_conn_factory: 回傳 WAL 模式 sqlite3.Connection 的 callable。
                             通常傳入 engine.get_db_conn 以共用連線設定。
            data_store_provider: 回傳當前 data_store list 的 callable。
                                 採 callable 模式（而非直接傳 list）以避免
                                 上游重新指派 data_store 後出現舊參照。
        """
        self._db_path: str = db_path
        self._get_db_conn: Callable[[], sqlite3.Connection] = db_conn_factory
        self._get_data_store: Callable[[], List[Dict[str, Any]]] = data_store_provider
        self.pinned_paths: set[str] = set()

    # ------------------------------------------------------------------
    #  快取同步
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """從 pinned 資料表重新載入所有釘選路徑到記憶體集合。

        若資料庫檔案尚未建立則靜默清空快取，不拋出例外。
        """
        self.pinned_paths = set()
        if not os.path.exists(self._db_path):
            return
        try:
            conn = self._get_db_conn()
            rows = conn.execute("SELECT file_path FROM pinned").fetchall()
            conn.close()
            for (fp,) in rows:
                self.pinned_paths.add(os.path.normpath(fp))
        except Exception as e:
            print(f"[PinManager] reload error: {e}")

    # ------------------------------------------------------------------
    #  狀態切換
    # ------------------------------------------------------------------
    def toggle(self, file_path: str) -> bool:
        """切換指定圖片的釘選狀態，並同步更新資料庫與記憶體快取。

        Args:
            file_path: 圖片完整路徑。

        Returns:
            True  → 現在已釘選（剛新增）。
            False → 現在未釘選（剛取消）。
            若資料庫操作失敗，回傳當前快取中的狀態作為 fallback。
        """
        norm = os.path.normpath(file_path)
        try:
            conn = self._get_db_conn()
            if norm in self.pinned_paths:
                conn.execute("DELETE FROM pinned WHERE file_path = ?", (file_path,))
                conn.commit()
                conn.close()
                self.pinned_paths.discard(norm)
                return False
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO pinned (file_path) VALUES (?)",
                    (file_path,),
                )
                conn.commit()
                conn.close()
                self.pinned_paths.add(norm)
                return True
        except Exception as e:
            print(f"[PinManager] toggle error: {e}")
            return norm in self.pinned_paths

    def is_pinned(self, file_path: str) -> bool:
        """查詢指定路徑是否處於釘選狀態（純記憶體查詢，O(1)）。

        Args:
            file_path: 圖片完整路徑。

        Returns:
            True 表示已釘選，False 表示未釘選。
        """
        return os.path.normpath(file_path) in self.pinned_paths

    # ------------------------------------------------------------------
    #  與搜尋結果合併
    # ------------------------------------------------------------------
    def get_pinned_results(self) -> List[Dict[str, Any]]:
        """將所有釘選圖片轉換為搜尋結果格式（無視資料夾範圍）。

        從 data_store_provider 動態取得目前的 data_store，
        過濾出已釘選的圖片並包裝成與 search_hybrid / search_image
        一致的字典格式（score=0.0, is_pinned=True）。

        Returns:
            搜尋結果字典清單。若無釘選圖或 data_store 為空則回傳 []。
        """
        if not self.pinned_paths:
            return []
        data_store = self._get_data_store()
        if not data_store:
            return []
        results: List[Dict[str, Any]] = []
        for item in data_store:
            if os.path.normpath(item["path"]) in self.pinned_paths:
                results.append({
                    "score": 0.0,
                    "clip_score": 0.0,
                    "ocr_bonus": 0.0,
                    "name_bonus": 0.0,
                    "is_ocr_match": False,
                    "is_pinned": True,
                    "path": item["path"],
                    "filename": item["filename"],
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0),
                })
        return results

    def merge_pinned_to_top(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """將釘選圖片置頂，與一般搜尋結果合併並去除重複項目。

        Args:
            results: 一般搜尋演算法產生的結果列表。

        Returns:
            合併後的結果列表：釘選圖永遠在前，已存在於釘選清單中的
            原始結果會被剔除以避免重複顯示。
        """
        pinned = self.get_pinned_results()
        if not pinned:
            return results
        pinned_paths_set = {r["path"] for r in pinned}
        deduped = [r for r in results if r["path"] not in pinned_paths_set]
        return pinned + deduped

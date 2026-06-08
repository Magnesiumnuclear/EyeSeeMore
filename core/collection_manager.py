"""
CollectionManager  –  虛擬資料夾 (Collections) 管理器
========================================================
從 ImageSearchEngine 抽離的職責：
  • collections 資料表的 CRUD 操作（新增 / 查詢 / 刪除 / 更新圖示）
  • collection_items 資料表的批次寫入（拖曳將圖片加入虛擬資料夾）
  • 取得虛擬資料夾內的圖片清單（與 data_store 比對後回傳完整 metadata）
  • collections.icon 欄位的冪等遷移

設計原則：
  • 零 PyQt 依賴，純 Python + sqlite3
  • 內建 WAL 模式連線工廠，與 OcrRepository / engine.get_db_conn() 行為一致
  • data_store 採 by-reference 傳址，呼叫端需確保不對 list 進行 rebinding
    （配套：engine.load_data_from_db 已改為就地 clear()+extend()）
  • _ensure_icon_column 保留接收外部 conn 的設計，以便能在同一交易中執行遷移

使用方式：
    collection_mgr = CollectionManager(
        db_path=config.db_path,
        data_store=engine.data_store,  # 直接共享同一個 list 參照
    )
    collection_mgr.add_collection("我的最愛", icon="⭐")
    rows = collection_mgr.get_collections()       # [(id, name, icon, count), ...]
    collection_mgr.add_to_virtual_folder(1, ["D:/img.jpg"])
    imgs = collection_mgr.get_virtual_folder_images(1)
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Tuple, Union


class CollectionManager:
    """虛擬資料夾 (Collections) 的獨立管理器。

    同時負責 collections（虛擬資料夾本身）與 collection_items
    （資料夾內的圖片清單）兩張資料表的所有讀寫操作。
    """

    _icon_column_ensured: bool = False  # class-level flag，避免重複 PRAGMA 查詢

    def __init__(self, db_path: str, data_store: List[Dict[str, Any]]) -> None:
        """建立 CollectionManager 實例。

        Args:
            db_path: SQLite 資料庫的絕對路徑。
            data_store: ImageSearchEngine 的記憶體圖片清單。
                        採 by-reference 傳址，呼叫端必須使用就地修改
                        (list.clear() + list.extend()) 而非 rebinding，
                        否則 get_virtual_folder_images 會比對到舊資料。
        """
        self._db_path: str = db_path
        self._data_store: List[Dict[str, Any]] = data_store  # by-reference

    # ------------------------------------------------------------------
    #  內部 helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """建立具備 WAL 模式與高容忍度的資料庫連線（內部使用）。

        與 ImageSearchEngine.get_db_conn() 及 OcrRepository._connect()
        三者行為完全一致：timeout=15s, WAL 模式, synchronous=NORMAL。
        """
        conn = sqlite3.connect(self._db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _ensure_icon_column(self, conn: sqlite3.Connection) -> None:
        """冪等遷移：若 collections 尚無 icon 欄位則自動新增。

        保留接收外部 conn 的設計，讓 add_collection / get_collections /
        update_collection_icon 能在同一個交易中完成「遷移 + 業務操作」，
        減少連線開銷。

        Args:
            conn: 外部提供的 sqlite3 連線（已開啟交易）。
        """
        if CollectionManager._icon_column_ensured:
            return
        cols = [row[1] for row in conn.execute("PRAGMA table_info(collections)").fetchall()]
        if "icon" not in cols:
            conn.execute("ALTER TABLE collections ADD COLUMN icon TEXT DEFAULT '🏷️'")
            conn.commit()
        CollectionManager._icon_column_ensured = True

    # ------------------------------------------------------------------
    #  虛擬資料夾 CRUD（新版 API）
    # ------------------------------------------------------------------
    def add_collection(self, name: str, icon: str = "🏷️") -> bool:
        """新增一個虛擬資料夾（含 icon 欄位自動遷移）。

        Args:
            name: 虛擬資料夾名稱（資料表中為 UNIQUE，重複會引發例外）。
            icon: emoji 圖示字串，預設為 🏷️。

        Returns:
            True 表示新增成功，False 表示失敗（例如名稱重複）。
        """
        try:
            with self._connect() as conn:
                self._ensure_icon_column(conn)
                conn.execute(
                    "INSERT INTO collections (name, icon, created_at) VALUES (?, ?, ?)",
                    (name, icon, time.time()),
                )
            return True
        except Exception as e:
            print(f"[CollectionManager] add_collection error: {e}")
            return False

    def get_collections(self) -> List[Tuple[int, str, str, int]]:
        """回傳所有虛擬資料夾，含每個資料夾的圖片數量。

        Returns:
            [(id, name, icon, count), ...] 依 created_at 升冪排序。
            若無資料或例外則回傳 []。
        """
        try:
            conn = self._connect()
            try:
                self._ensure_icon_column(conn)
                rows = conn.execute(
                    """
                    SELECT c.id,
                           c.name,
                           COALESCE(c.icon, '🏷️') AS icon,
                           COUNT(ci.file_path)       AS cnt
                    FROM collections c
                    LEFT JOIN collection_items ci ON c.id = ci.collection_id
                    GROUP BY c.id
                    ORDER BY c.created_at ASC
                    """
                ).fetchall()
                return rows
            finally:
                conn.close()
        except Exception as e:
            print(f"[CollectionManager] get_collections error: {e}")
            return []

    def remove_collection(self, collection_id: int) -> bool:
        """刪除虛擬資料夾，並清除所有關聯的 collection_items。

        啟用 PRAGMA foreign_keys 後 ON DELETE CASCADE 會自動清理子表，
        為保險起見再手動 DELETE 一次（儀式防呆）。

        Args:
            collection_id: 要刪除的虛擬資料夾 ID。

        Returns:
            True 表示刪除成功，False 表示失敗。
        """
        try:
            conn = self._connect()
            try:
                # 啟用外鍵約束，確保 ON DELETE CASCADE 生效
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
                # 儀式防呆：若 PRAGMA 未生效，手動清理子表
                conn.execute(
                    "DELETE FROM collection_items WHERE collection_id = ?",
                    (collection_id,),
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as e:
            print(f"[CollectionManager] remove_collection error: {e}")
            return False

    def update_collection_icon(self, collection_id: int, icon: str) -> bool:
        """更新虛擬資料夾的 emoji 圖示。

        Args:
            collection_id: 目標虛擬資料夾 ID。
            icon: 新的 emoji 圖示字串。

        Returns:
            True 表示更新成功，False 表示失敗。
        """
        try:
            with self._connect() as conn:
                self._ensure_icon_column(conn)
                conn.execute(
                    "UPDATE collections SET icon = ? WHERE id = ?",
                    (icon, collection_id),
                )
            return True
        except Exception as e:
            print(f"[CollectionManager] update_collection_icon error: {e}")
            return False

    # ------------------------------------------------------------------
    #  舊版 API（保留以維持向後相容；目前外部無呼叫）
    # ------------------------------------------------------------------
    def create_virtual_folder(self, name: str) -> Tuple[bool, Union[int, str]]:
        """[舊版] 建立新的虛擬資料夾（不含 icon 欄位）。

        Args:
            name: 虛擬資料夾名稱。

        Returns:
            (True, new_id) 表示成功；
            (False, error_message) 表示失敗（例如名稱已存在）。
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO collections (name, created_at) VALUES (?, ?)",
                (name, time.time()),
            )
            conn.commit()
            return True, cursor.lastrowid
        except sqlite3.IntegrityError:
            return False, "該名稱已存在！"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def get_virtual_folders(self) -> List[Tuple[int, str, int]]:
        """[舊版] 取得所有虛擬資料夾與其包含的圖片數量（不含 icon）。

        Returns:
            [(id, name, count), ...] 依 created_at 升冪排序。
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT c.id, c.name, COUNT(ci.file_path)
                FROM collections c
                LEFT JOIN collection_items ci ON c.id = ci.collection_id
                GROUP BY c.id
                ORDER BY c.created_at ASC
                """
            )
            return cursor.fetchall()
        except Exception as e:
            print(f"[CollectionManager] get_virtual_folders error: {e}")
            return []
        finally:
            conn.close()

    # ------------------------------------------------------------------
    #  collection_items：資料夾內的圖片
    # ------------------------------------------------------------------
    def add_to_virtual_folder(self, collection_id: int, file_paths: List[str]) -> bool:
        """將多張圖片加入虛擬資料夾（支援拖曳寫入）。

        所有路徑寫入前統一正規化（os.path.normpath + abspath），
        修正斜線並統一磁碟代號大小寫。使用 INSERT OR IGNORE 確保
        重複寫入同一張圖不會引發 UNIQUE 衝突。

        Args:
            collection_id: 目標虛擬資料夾 ID。
            file_paths: 要加入的圖片路徑清單。

        Returns:
            True 表示寫入成功；False 表示空輸入或例外。
        """
        if not file_paths:
            return False
        conn = self._connect()
        try:
            cursor = conn.cursor()
            # [防禦] 寫入前統一正規化路徑
            normalized = [os.path.normpath(os.path.abspath(p)) for p in file_paths]
            data = [(collection_id, p) for p in normalized]
            # 使用 INSERT OR IGNORE，重複把同一張圖丟進同一個資料夾也不會報錯
            cursor.executemany(
                "INSERT OR IGNORE INTO collection_items (collection_id, file_path) VALUES (?, ?)",
                data,
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[CollectionManager] add_to_virtual_folder error: {e}")
            return False
        finally:
            conn.close()

    def get_virtual_folder_images(self, collection_id: int) -> List[Dict[str, Any]]:
        """取得特定虛擬資料夾內的所有圖片，用於顯示在畫廊。

        建立正規化查詢表（同時收錄原始路徑與正規化路徑），相容舊資料；
        接著直接從記憶體 data_store 抽取完整 metadata（O(N)，但極快）。

        Args:
            collection_id: 目標虛擬資料夾 ID。

        Returns:
            搜尋結果字典清單，按 mtime 倒序排列（最新修改在前）。
            若資料夾為空或例外則回傳 []。
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_path FROM collection_items WHERE collection_id = ?",
                (collection_id,),
            )
            raw_paths = [row[0] for row in cursor.fetchall()]

            # [防禦] 建立正規化查詢表：同時收錄原始路徑與正規化路徑，相容歷史舊資料
            paths: set[str] = set()
            for p in raw_paths:
                paths.add(p)
                paths.add(os.path.normpath(os.path.abspath(p)))

            # 直接從 O(1) 的記憶體 data_store 中把圖片資訊抽出來！極度快速！
            results: List[Dict[str, Any]] = []
            for item in self._data_store:
                item_path = item["path"]
                item_path_norm = os.path.normpath(os.path.abspath(item_path))
                if item_path in paths or item_path_norm in paths:
                    results.append({
                        "score": 0.0,
                        "clip_score": 0.0,
                        "ocr_bonus": 0.0,
                        "name_bonus": 0.0,
                        "is_ocr_match": False,
                        "path": item["path"],
                        "filename": item["filename"],
                        "mtime": item.get("mtime", 0),
                        "width": item.get("width", 0),
                        "height": item.get("height", 0),
                    })
            # 按時間排序 (最新修改的排前面)
            results.sort(key=lambda x: x["mtime"], reverse=True)
            return results
        except Exception as e:
            print(f"[CollectionManager] get_virtual_folder_images error: {e}")
            return []
        finally:
            conn.close()

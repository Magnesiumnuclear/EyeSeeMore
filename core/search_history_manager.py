"""
SearchHistoryManager  –  搜尋歷史紀錄管理器
=============================================
從 MainWindow 抽離的職責：
  • search_history.json 的讀取與寫入（純檔案 I/O）
  • 內部維護最近 N 筆查詢字串的清單
  • 提供新增 / 刪除 / 查詢的純資料介面

設計原則：
  • 零 PyQt 依賴，純 Python + json + os
  • 建構子接收檔案路徑後立即自動載入（與原始 MainWindow.load_history
    在 __init__ 階段呼叫的行為一致）
  • add / delete 自動寫回檔案並回傳更新後的清單，
    讓上層 UI 元件（SearchCapsule）能直接接收最新狀態。

使用方式：
    history_mgr = SearchHistoryManager(history_file_path)
    history_mgr.add("貓咪")              # 回傳更新後的 list[str]
    history_mgr.delete("舊查詢")         # 回傳更新後的 list[str]
    all_items = history_mgr.get_all()    # 取得目前完整清單
"""

from __future__ import annotations

import json
import os
from typing import List


class SearchHistoryManager:
    """搜尋歷史紀錄的獨立管理器。

    僅負責檔案 I/O 與 list 操作，不持有任何 Qt 物件或 UI 元件參照。
    所有的 UI 同步（例如 SearchCapsule.set_history）由呼叫端依據
    add / delete 的回傳值自行處理。
    """

    #: 最多保留的歷史紀錄筆數；超過時會自動剔除最舊的項目
    MAX_ITEMS: int = 10

    def __init__(self, history_file_path: str) -> None:
        """建立 SearchHistoryManager 實例並立即從磁碟載入歷史紀錄。

        Args:
            history_file_path: search_history.json 的絕對路徑。
                              若檔案不存在則內部清單初始化為空 list。
        """
        self._path: str = history_file_path
        self._history: List[str] = []
        self.load()

    # ------------------------------------------------------------------
    #  檔案 I/O
    # ------------------------------------------------------------------
    def load(self) -> None:
        """從 JSON 檔案讀取歷史紀錄到內部清單。

        若檔案不存在則保持內部清單為空；若 JSON 解析失敗則重置為空 list
        並靜默處理（與原 MainWindow.load_history 的 bare except 行為一致）。
        """
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._history = json.load(f)
        except Exception:
            self._history = []

    def save(self) -> None:
        """將內部清單序列化為 JSON 並寫入檔案。

        寫入失敗時靜默處理，不向上拋出例外（與原行為一致，
        避免因磁碟暫時鎖死導致搜尋流程中斷）。
        """
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._history, f, ensure_ascii=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  公開資料介面
    # ------------------------------------------------------------------
    def add(self, query: str) -> List[str]:
        """新增一筆查詢至清單頂端（MRU 行為）。

        若該查詢已存在則先移除舊位置再插入到最前，確保最近搜尋的項目
        永遠在最上方。超過 MAX_ITEMS 上限時會自動剔除尾端最舊的項目。
        每次呼叫都會自動寫回檔案。

        Args:
            query: 要新增的查詢字串。空字串會被忽略，不做任何變更。

        Returns:
            更新後的歷史清單副本（list[str]，便於 UI 直接顯示）。
        """
        if not query:
            return list(self._history)
        if query in self._history:
            self._history.remove(query)
        self._history.insert(0, query)
        if len(self._history) > self.MAX_ITEMS:
            self._history = self._history[: self.MAX_ITEMS]
        self.save()
        return list(self._history)

    def delete(self, query: str) -> List[str]:
        """從清單中刪除指定查詢。

        若查詢不存在則不做任何變更，但仍會回傳目前清單。
        刪除成功時會自動寫回檔案。

        Args:
            query: 要刪除的查詢字串。

        Returns:
            更新後的歷史清單副本（list[str]，便於 UI 直接顯示）。
        """
        if query in self._history:
            self._history.remove(query)
            self.save()
        return list(self._history)

    def get_all(self) -> List[str]:
        """取得目前完整的歷史清單。

        Returns:
            歷史清單的副本（list[str]），呼叫端修改不會影響內部狀態。
        """
        return list(self._history)

"""
OcrRepository  –  OCR 框資料的 SQLite 資料存取層
==================================================
從 ImageSearchEngine 抽離的職責：
  • 從 ocr_results 資料表讀取單張圖片的所有 OCR 框
  • 將框選 OCR 結果合併寫入（upsert，逐語系處理）
  • 刪除指定框（含 ±2px 容忍度比對）
  • 更新指定框的辨識文字（座標不變）

設計原則：
  • 零 PyQt 依賴，純 Python + sqlite3 + json
  • 內建 WAL 模式連線工廠，與 ImageSearchEngine.get_db_conn() 行為一致
  • ±2px 比對邏輯抽出為 @staticmethod，DRY 處理 delete/update 共用程式碼

使用方式：
    ocr_repo = OcrRepository(db_path=config.db_path)
    boxes = ocr_repo.get_by_path("D:/img.jpg")
    ocr_repo.upsert("D:/img.jpg", [{"lang": "ch", "box": [...], "text": "...", "conf": 0.98}])
    ocr_repo.delete_box("D:/img.jpg", "ch", [[10,20],[100,20],[100,40],[10,40]])
    ocr_repo.update_box_text("D:/img.jpg", "ch", box, "修正後的文字")
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List


class OcrRepository:
    """OCR 框資料的資料存取層 (Data Access Layer)。

    負責 ocr_results 資料表的所有 CRUD 操作。為了與 ImageSearchEngine
    的資料庫存取行為保持一致，內部連線同樣啟用 WAL 模式與
    NORMAL 同步等級。
    """

    def __init__(self, db_path: str) -> None:
        """建立 OcrRepository 實例。

        Args:
            db_path: SQLite 資料庫的絕對路徑。
        """
        self._db_path: str = db_path

    # ------------------------------------------------------------------
    #  內部 helpers
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """建立具備 WAL 模式與高容忍度的資料庫連線（內部使用）。

        timeout=15.0：硬碟阻塞時最多等待 15 秒；
        WAL 模式：讀寫分離，前端讀取不會阻塞後台寫入；
        synchronous=NORMAL：大幅減少硬碟同步等待，提升寫入速度。
        """
        conn = sqlite3.connect(self._db_path, timeout=15.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @staticmethod
    def _boxes_match(b1: List[List[float]], b2: List[List[float]], tol: int = 2) -> bool:
        """以 ±tol 像素的容忍度比對兩個 4 點框是否相同。

        比對前先對 4 個點進行字典序排序，使得結果不受點儲存順序影響
        （相容 PaddleOCR 原始順序與 _sort_points 後的順序）。

        Args:
            b1: 第一個 4 點框 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]。
            b2: 第二個 4 點框，格式同上。
            tol: 像素容忍度（預設 2px），用於防止浮點數誤差。

        Returns:
            True 表示兩框可視為相同位置，False 則不同。
            若資料結構異常（例如不是 4 點）則回傳 False。
        """
        try:
            s1 = sorted(b1, key=lambda p: (p[0], p[1]))
            s2 = sorted(b2, key=lambda p: (p[0], p[1]))
            return all(
                abs(s1[i][0] - s2[i][0]) < tol and abs(s1[i][1] - s2[i][1]) < tol
                for i in range(4)
            )
        except Exception:
            return False

    # ------------------------------------------------------------------
    #  公開 CRUD 介面
    # ------------------------------------------------------------------
    def get_by_path(self, file_path: str) -> List[Dict[str, Any]]:
        """[懶加載] 根據檔案路徑取得該圖片所有語系的 OCR 框資料。

        從 ocr_results 撈出該圖每個語系的 ocr_data JSON 字串並解析，
        為每個 box dict 注入 lang 欄位以便上層識別來源。

        Args:
            file_path: 圖片完整路徑（必須存在於 files 資料表中）。

        Returns:
            扁平的 box dict 列表：
                [{"lang": "ch", "box": [...], "text": "...", "conf": 0.98}, ...]
            若該圖無 OCR 資料或解析失敗則回傳 []。
        """
        conn = self._connect()
        cursor = conn.cursor()
        ocr_boxes: List[Dict[str, Any]] = []
        try:
            cursor.execute(
                """
                SELECT o.lang, o.ocr_data
                FROM ocr_results o
                JOIN files f ON o.file_id = f.id
                WHERE f.file_path = ?
                """,
                (file_path,),
            )
            rows = cursor.fetchall()
            for lang, data_json in rows:
                if data_json and data_json != "[]" and data_json != "[NULL]":
                    try:
                        parsed_data = json.loads(data_json)
                        if isinstance(parsed_data, list):
                            for item in parsed_data:
                                item["lang"] = lang
                                ocr_boxes.append(item)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[OcrRepository] get_by_path error: {e}")
        finally:
            conn.close()
        return ocr_boxes

    def upsert(self, file_path: str, new_items: List[Dict[str, Any]]) -> bool:
        """將框選 OCR 結果合併寫入資料庫（每個語系單獨處理）。

        若該語系已有舊資料：取出 ocr_data 反序列化後追加新框並回寫；
        若該語系尚無資料：新增一筆 ocr_results 記錄。
        ocr_text 欄位會以空白串接所有 box 的文字以供關鍵字搜尋使用。

        Args:
            file_path: 圖片完整路徑（必須存在於 files 資料表中）。
            new_items: 新框列表，每筆需包含 {"lang", "box", "text", "conf"}。

        Returns:
            True 表示成功寫入，False 表示空輸入、找不到 file_id 或資料庫例外。
        """
        if not new_items:
            return False
        try:
            conn = self._connect()
            cur = conn.cursor()

            # 取 file_id
            cur.execute("SELECT id FROM files WHERE file_path=?", (file_path,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False
            file_id = row[0]

            # 把 new_items 按語系分組
            by_lang: Dict[str, List[Dict[str, Any]]] = {}
            for item in new_items:
                lang = item.get("lang", "unk")
                by_lang.setdefault(lang, []).append({
                    "box":  item["box"],
                    "text": item["text"],
                    "conf": item["conf"],
                })

            for lang, items in by_lang.items():
                cur.execute(
                    "SELECT id, ocr_text, ocr_data FROM ocr_results WHERE file_id=? AND lang=?",
                    (file_id, lang),
                )
                existing = cur.fetchone()

                if existing:
                    row_id, old_text, old_data_json = existing
                    try:
                        old_data = json.loads(old_data_json) if old_data_json else []
                    except Exception:
                        old_data = []
                    merged_data = old_data + items
                    merged_text = (old_text or "") + " " + " ".join(i["text"] for i in items)
                    cur.execute(
                        "UPDATE ocr_results SET ocr_text=?, ocr_data=? WHERE id=?",
                        (merged_text.strip(), json.dumps(merged_data, ensure_ascii=False), row_id),
                    )
                else:
                    ocr_text = " ".join(i["text"] for i in items)
                    ocr_data = json.dumps(items, ensure_ascii=False)
                    cur.execute(
                        "INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) VALUES (?,?,?,?,?)",
                        (file_id, lang, ocr_text, ocr_data, 1.0),
                    )

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[OcrRepository] upsert error: {e}")
            return False

    def delete_box(self, file_path: str, lang: str, box_to_delete: List[List[float]]) -> bool:
        """從指定語系的 ocr_data 中移除符合座標的框。

        採用 ±2px 容忍度比對（透過 _boxes_match），可防止浮點數誤差導致
        刪除失敗。比對前對 4 個點排序，與儲存順序無關。

        Args:
            file_path: 圖片完整路徑。
            lang: OCR 語系代碼（例如 "ch", "japan", "en"）。
            box_to_delete: 欲刪除的 4 點框。

        Returns:
            True 表示成功刪除，False 表示找不到符合的框、找不到 file_id
            或資料庫例外。
        """
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT id FROM files WHERE file_path=?", (file_path,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False
            file_id = row[0]
            cur.execute(
                "SELECT id, ocr_text, ocr_data FROM ocr_results WHERE file_id=? AND lang=?",
                (file_id, lang),
            )
            existing = cur.fetchone()
            if not existing:
                conn.close()
                return False
            row_id, old_text, old_data_json = existing
            try:
                items = json.loads(old_data_json) if old_data_json else []
            except Exception:
                items = []
            new_items = [
                it for it in items
                if not self._boxes_match(it.get("box", []), box_to_delete)
            ]
            if len(new_items) == len(items):
                conn.close()
                return False  # 沒找到相符的框
            new_text = " ".join(it.get("text", "") for it in new_items)
            cur.execute(
                "UPDATE ocr_results SET ocr_text=?, ocr_data=? WHERE id=?",
                (new_text, json.dumps(new_items, ensure_ascii=False), row_id),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[OcrRepository] delete_box error: {e}")
            return False

    def update_box_text(
        self,
        file_path: str,
        lang: str,
        box_to_match: List[List[float]],
        new_text: str,
    ) -> bool:
        """將指定框的辨識文字更新為 new_text（座標不變，confidence 重設為 1.0）。

        使用 ±2px 容忍度比對 box，並支援多框命中（理論上同語系不會有
        重複框，但若資料異常仍會全部更新）。ocr_text 欄位會重新串接。

        Args:
            file_path: 圖片完整路徑。
            lang: OCR 語系代碼。
            box_to_match: 欲更新文字的 4 點框。
            new_text: 新的辨識文字。

        Returns:
            True 表示成功更新；False 表示找不到相符的框、找不到 file_id
            或資料庫例外。
        """
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute("SELECT id FROM files WHERE file_path=?", (file_path,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return False
            file_id = row[0]
            cur.execute(
                "SELECT id, ocr_data FROM ocr_results WHERE file_id=? AND lang=?",
                (file_id, lang),
            )
            existing = cur.fetchone()
            if not existing:
                conn.close()
                return False
            row_id, old_data_json = existing
            try:
                items = json.loads(old_data_json) if old_data_json else []
            except Exception:
                items = []
            matched = False
            for it in items:
                if self._boxes_match(it.get("box", []), box_to_match):
                    it["text"] = new_text
                    it["conf"] = 1.0
                    matched = True
            if not matched:
                conn.close()
                return False
            full_text = " ".join(it.get("text", "") for it in items)
            cur.execute(
                "UPDATE ocr_results SET ocr_text=?, ocr_data=? WHERE id=?",
                (full_text, json.dumps(items, ensure_ascii=False), row_id),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[OcrRepository] update_box_text error: {e}")
            return False

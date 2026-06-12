import hashlib
import os
import sqlite3

import numpy as np
import onnxruntime as ort
import faiss
from PIL import Image

from core.paths import FAISS_CACHE_DIR

from core.config_manager import ConfigManager
from core.model_provider import ModelProvider
from core.pin_manager import PinManager
from core.ocr_repository import OcrRepository
from core.collection_manager import CollectionManager


# ==========================================
class ImageSearchEngine:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.device = "dml" if 'DmlExecutionProvider' in ort.get_available_providers() else "cpu"
        self.data_store = []

        # [修正] 預先定義 stored_embeddings
        self.stored_embeddings = None

        # [Refactor Phase 3-A] 模型加載委派至獨立的 ModelProvider
        # 支援非阻塞加載，MainWindow 透過訊號監聽加載完成
        self.model_provider = ModelProvider(self.config, parent=None)

        # [Refactor Phase 1-A] 釘選功能委派至 PinManager
        # 採 callable 模式取得 data_store，避免 load_data_from_db 重新指派後
        # PinManager 持有過期參照。get_db_conn 共享 WAL 連線設定。
        self.pin_manager = PinManager(
            db_path=self.config.db_path,
            db_conn_factory=self.get_db_conn,
            data_store_provider=lambda: self.data_store,
        )

        # [Refactor Phase 1-B] OCR 框資料存取委派至 OcrRepository
        # 採內建 WAL 連線（與 get_db_conn 行為一致），完全獨立於引擎其他狀態
        self.ocr_repo = OcrRepository(db_path=self.config.db_path)

        # [Refactor Phase 1-C] 虛擬資料夾管理委派至 CollectionManager
        # 採 by-reference 共享 data_store；配套 load_data_from_db 已改為
        # 就地 clear()+extend() 以保證 data_store 參照永遠新鮮。
        self.collection_mgr = CollectionManager(
            db_path=self.config.db_path,
            data_store=self.data_store,
        )

        # 1. 初始化資料庫
        print(f"[Engine] Initializing Database...")
        if os.path.exists(self.config.db_path):
            self.load_data_from_db()
        else:
            print(f"[Error] Database file not found: {self.config.db_path}")

    # ==========================================
    # 在 ImageSearchEngine 類別中，載入資料庫向量之後加入這段
    # ==========================================
    def build_faiss_index(self, embeddings_matrix):
        """
        將 Numpy 矩陣轉換為 FAISS 光速索引引擎
        :param embeddings_matrix: shape 為 (N, 1024) 的 Numpy 陣列
        """
        if len(embeddings_matrix) == 0:
            self.faiss_index = None
            return

        dimension = embeddings_matrix.shape[1]
        n = len(embeddings_matrix)

        #  由於您的 CLIP 向量在 indexer.py 中已經做過 L2 歸一化，
        # 這裡直接使用 IP (Inner Product 內積)，它在數學上等同於 Cosine Similarity！

        # [效能優化] 動態選擇演算法：
        # ≤10,000 張：IndexFlatIP (暴力, O(N), 精度100%)
        # >10,000 張：IndexHNSWFlat (圖形演算, O(log N), 精度~98%)
        HNSW_THRESHOLD = 10_000
        if n > HNSW_THRESHOLD:
            # [Perf Phase 3-G] HNSW 建構成本高（2 萬筆實測約 1 秒，隨量增長），
            # 但 read_index 載入只要毫秒級。指紋（筆數×維度×內容雜湊）一致時
            # 直接從磁碟載入，向量有任何增刪改都會自動重建。
            index = self._load_cached_hnsw(embeddings_matrix)
            if index is None:
                index = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)
                index.add(embeddings_matrix.astype(np.float32))
                self._save_hnsw_cache(index, embeddings_matrix)
            index.hnsw.efSearch = 64   # 提高搜尋品質（預設16，64在精度與速度間取得平衡）
            print(f"[FAISS] 資料量 {n} > {HNSW_THRESHOLD}，啟用 HNSW 圖索引 (efSearch=64)")
        else:
            index = faiss.IndexFlatIP(dimension)
            # 將所有向量加入引擎 (必須是 float32 格式)
            index.add(embeddings_matrix.astype(np.float32))

        self.faiss_index = index
        print(f"[FAISS] 成功建立 {self.faiss_index.ntotal} 筆向量索引！")

    # ==========================================
    #  [Perf Phase 3-G] HNSW 索引磁碟快取
    # ==========================================
    def _emb_fingerprint(self, embeddings_matrix) -> str:
        """以筆數×維度×內容雜湊作為索引快取指紋（順序敏感，與 data_store 對齊）。"""
        h = hashlib.blake2b(
            np.ascontiguousarray(embeddings_matrix, dtype=np.float32).tobytes(),
            digest_size=16,
        )
        return f"{embeddings_matrix.shape[0]}x{embeddings_matrix.shape[1]}-{h.hexdigest()}"

    def _faiss_cache_paths(self):
        model = self.config.get("model_name") or "default"
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in model)
        base = os.path.join(FAISS_CACHE_DIR, safe)
        return base + ".index", base + ".meta"

    def _load_cached_hnsw(self, embeddings_matrix):
        """指紋一致時載入磁碟上的 HNSW 索引；任何不符或例外都回 None 改為重建。"""
        try:
            idx_path, meta_path = self._faiss_cache_paths()
            if not (os.path.exists(idx_path) and os.path.exists(meta_path)):
                return None
            with open(meta_path, "r", encoding="utf-8") as f:
                if f.read().strip() != self._emb_fingerprint(embeddings_matrix):
                    return None
            index = faiss.read_index(idx_path)
            if index.ntotal != len(embeddings_matrix):
                return None
            print(f"[FAISS] 命中磁碟快取，跳過 HNSW 重建")
            return index
        except Exception as e:
            print(f"[FAISS] 快取載入失敗，改為重建: {e}")
            return None

    def _save_hnsw_cache(self, index, embeddings_matrix):
        """寫入索引檔與指紋。失敗不影響功能，只是下次仍需重建。"""
        try:
            idx_path, meta_path = self._faiss_cache_paths()
            os.makedirs(os.path.dirname(idx_path), exist_ok=True)
            faiss.write_index(index, idx_path)
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(self._emb_fingerprint(embeddings_matrix))
        except Exception as e:
            print(f"[FAISS] 快取寫入失敗（不影響功能）: {e}")

    # ==========================================
    #  [新增] 統一的 WAL 資料庫連線產生器
    # ==========================================
    def get_db_conn(self):
        """建立具備 WAL 模式與高容忍度的資料庫連線"""
        # timeout=15.0 表示如果硬碟真的卡住，前端願意等 15 秒而不直接報錯當機
        conn = sqlite3.connect(self.config.db_path, timeout=15.0)
        # 啟動 WAL 模式 (讀寫分離，前端讀取不阻塞後台寫入)
        conn.execute("PRAGMA journal_mode=WAL;")
        # 設定為 NORMAL，大幅減少硬碟同步等待時間，提升 10 倍以上寫入速度
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @property
    def is_ready(self) -> bool:
        """[委派] 檢查模型是否加載完成（取自 ModelProvider）"""
        return self.model_provider.is_ready if hasattr(self, 'model_provider') else False

    @property
    def preprocess(self):
        """[委派] 取得預處理器（取自 ModelProvider）"""
        return self.model_provider.preprocess if hasattr(self, 'model_provider') else None

    @property
    def tokenizer(self):
        """[委派] 取得 Tokenizer（取自 ModelProvider）"""
        return self.model_provider.tokenizer if hasattr(self, 'model_provider') else None

    @property
    def clip_image_session(self):
        """[委派] 取得 CLIP 影像 Session（取自 ModelProvider）"""
        return self.model_provider.clip_image_session if hasattr(self, 'model_provider') else None

    @property
    def clip_text_session(self):
        """[委派] 取得 CLIP 文字 Session（取自 ModelProvider）"""
        return self.model_provider.clip_text_session if hasattr(self, 'model_provider') else None

    @property
    def is_hf_tokenizer(self):
        """[委派] 檢查是否為 HuggingFace Tokenizer（取自 ModelProvider）"""
        return self.model_provider.is_hf_tokenizer if hasattr(self, 'model_provider') else False

    @property
    def shared_ocr_engines(self):
        """[委派] 取得 OCR 引擎快取（取自 ModelProvider）"""
        return self.model_provider.shared_ocr_engines if hasattr(self, 'model_provider') else {}

    def load_ai_models(self):
        """
        [委派] 非阻塞啟動模型加載

        此方法立刻返回，模型加載在背景執行緒進行。
        完成時會發射 model_provider.models_loaded 訊號。
        """
        print(f"[Engine] 啟動非阻塞模型加載...")
        self.model_provider.load_models_async()

    def get_all_images_sorted(self):
        """
        [高效能] 取得資料庫中所有圖片，並依時間 (新->舊) 排序。
        用於冷啟動時的瀑布流顯示。
        """
        #  [終極防呆：取得當下的指標快照，防止被雙緩衝覆蓋]
        current_data = getattr(self, 'data_store', [])
        if not current_data:
            return []

        print(f"[Engine] Sorting {len(current_data)} images by date...")

        # 1. 使用 Python 內建 Timsort 進行快速排序 (mtime 大的排前面)
        sorted_data = sorted(current_data, key=lambda x: x["mtime"], reverse=True)

        # 2. 轉換為 UI 需要的格式
        results = []
        for item in sorted_data:
            results.append({
                "score": 0.0, "clip_score": 0.0, "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                "path": item["path"], "filename": item["filename"],
                "mtime": item.get("mtime", 0),
                "width": item.get("width", 0),
                "height": item.get("height", 0)
            })
        return self._merge_pinned(results)

    def load_data_from_db(self):
        print(f"[Engine] Connecting to database: {self.config.db_path}...")
        conn = self.get_db_conn()
        cursor = conn.cursor()
        try:
            current_model = self.config.get("model_name")

            #  [效能封頂] 拔除了肥大的 JSON 組合，只保留純文字 ocr_text 用於搜尋
            cursor.execute("""
                SELECT f.file_path, e.embedding, f.mtime, f.width, f.height,
                       GROUP_CONCAT(o.ocr_text, ' ')
                FROM files f
                JOIN embeddings e ON f.id = e.file_id
                LEFT JOIN ocr_results o ON f.id = o.file_id
                WHERE e.model_name = ?
                GROUP BY f.id
            """, (current_model,))
            rows = cursor.fetchall()

            temp_data_store = []
            temp_embeddings_list = []
            temp_path_map = {}

            # [效能優化] 預先掃描所有父目錄，建立存在檔案的 Set，
            # 迴圈內改用 O(1) 記憶體查詢，消除 N 次 syscall 的 I/O 阻塞。
            unique_dirs: set = set()
            for row in rows:
                unique_dirs.add(os.path.dirname(os.path.normpath(row[0])))
            existing_paths: set = set()
            for d in unique_dirs:
                try:
                    if os.path.isdir(d):
                        with os.scandir(d) as it:
                            for entry in it:
                                if entry.is_file():
                                    existing_paths.add(os.path.normpath(entry.path))
                except OSError:
                    pass

            #  [效能封頂] 迴圈內不再做任何 json.loads()，啟動速度直接起飛！
            for path, blob, mtime, width, height, combined_text in rows:
                norm_path = os.path.normpath(path)
                if norm_path not in existing_paths: continue

                emb_array = np.frombuffer(blob, dtype=np.float32)
                temp_embeddings_list.append(emb_array)
                text_content = combined_text if combined_text else ""

                # [Perf Phase 3-G] norm_path 在載入時算一次並快取：
                # 搜尋的資料夾過濾每次對全量做 os.path.normpath 實測佔 40ms/次
                # （2 萬筆），預快取後降至 3ms
                temp_data_store.append({
                    "path": path,
                    "norm_path": norm_path,
                    "filename": os.path.basename(path),
                    "ocr_text": text_content.lower(),
                    "mtime": mtime,
                    "width": width if width else 0,
                    "height": height if height else 0
                })

                #  [核心魔法] 將「正規化後的路徑」作為 Key，對應到陣列的 Index
                temp_path_map[norm_path] = len(temp_data_store) - 1

            if temp_data_store and temp_embeddings_list:
                temp_emb_matrix = np.stack(temp_embeddings_list)
                self.stored_embeddings = temp_emb_matrix
                # [Refactor Phase 1-C] 改為就地修改 list，保留 PinManager /
                # CollectionManager 持有的同一個 list 參照（避免 rebinding）
                self.data_store.clear()
                self.data_store.extend(temp_data_store)
                self.path_map = temp_path_map
                self.build_faiss_index(temp_emb_matrix)
                self.pin_manager.reload()
                print(f"[Engine] Loaded {len(self.data_store)} records for model '{current_model}'.")
            else:
                self.stored_embeddings = None
                self.data_store.clear()  # 就地清空，維持 list 參照不變
                self.path_map = {}
                self.pin_manager.pinned_paths = set()

        except sqlite3.Error as e:
            print(f"[Error] Database query failed: {e}")
        finally:
            if conn: conn.close()

    # ==========================================
    # 釘選 (Pinning) 功能 — 已委派至 self.pin_manager (PinManager)
    # 保留原方法簽章作為 Thin Delegation Layer，確保 MainWindow 與其他
    # 呼叫端的程式碼完全向後相容（refactor Phase 1-A）。
    # ==========================================
    def _reload_pinned_cache(self):
        """[委派] 從 pinned 資料表重新載入所有釘選路徑到記憶體集合。"""
        self.pin_manager.reload()

    def toggle_pin(self, file_path: str) -> bool:
        """[委派] 切換圖片釘選狀態。回傳 True 表示現在已釘選，False 表示已取消。"""
        return self.pin_manager.toggle(file_path)

    def is_pinned(self, file_path: str) -> bool:
        """[委派] 回傳指定路徑是否處於釘選狀態。"""
        return self.pin_manager.is_pinned(file_path)

    def _get_pinned_results(self) -> list:
        """[委派] 將所有釘選圖片轉換為搜尋結果格式（無視資料夾範圍）。"""
        return self.pin_manager.get_pinned_results()

    def _merge_pinned(self, results: list) -> list:
        """[委派] 將釘選圖片置頂，與搜尋結果合併去重。"""
        return self.pin_manager.merge_pinned_to_top(results)

    def get_folder_stats(self):
        if not os.path.exists(self.config.db_path): return []
        try:
            conn = self.get_db_conn()
            cursor = conn.cursor()
            # [關鍵修復 2] 根據當前模型去 model_stats 抓取統計
            current_model = self.config.get("model_name")
            cursor.execute("SELECT folder_path, image_count FROM model_stats WHERE model_name = ? ORDER BY folder_path ASC", (current_model,))
            stats = cursor.fetchall()
            conn.close()
            return stats
        except Exception as e:
            print(f"[Error] Failed to get stats: {e}"); return []

    def remove_folder_data(self, folder_path: str) -> bool:
        """
        原子化移除資料夾：同時清理資料庫記錄與記憶體索引。
        :param folder_path: 要移除的資料夾路徑（需與 DB 中的 folder_path 完全一致）
        :return: True 表示成功
        """
        norm_folder = os.path.normpath(folder_path)
        try:
            # --- 1. 資料庫清理（foreign_keys 保護 cascade） ---
            conn = self.get_db_conn()
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("DELETE FROM files WHERE folder_path = ?", (folder_path,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Engine] remove_folder_data DB error: {e}")
            return False

        # --- 2. 記憶體索引同步 ---
        if not self.data_store:
            return True

        # 找出所有屬於此資料夾的索引位置
        keep_mask = [
            item["norm_path"] != norm_folder and
            not item["norm_path"].startswith(norm_folder + os.sep)
            for item in self.data_store
        ]

        new_data_store = [item for item, keep in zip(self.data_store, keep_mask) if keep]
        keep_indices = [i for i, keep in enumerate(keep_mask) if keep]

        if len(new_data_store) == len(self.data_store):
            # 沒有任何項目被移除（路徑可能不符），仍視為成功
            return True

        # 重建 path_map（新索引號與舊不同，需完整重建）
        new_path_map = {}
        for new_idx, item in enumerate(new_data_store):
            new_path_map[item["norm_path"]] = new_idx

        # 重建 stored_embeddings 與 FAISS
        if self.stored_embeddings is not None and len(keep_indices) > 0:
            new_emb = self.stored_embeddings[keep_indices]
            self.stored_embeddings = new_emb
            self.build_faiss_index(new_emb)
        else:
            self.stored_embeddings = None
            self.faiss_index = None

        self.data_store = new_data_store
        self.path_map = new_path_map
        print(f"[Engine] remove_folder_data: removed folder '{folder_path}', "
              f"{len(self.data_store)} records remain.")
        return True

    def rename_file(self, old_path, new_name):
        folder = os.path.dirname(old_path); new_path = os.path.join(folder, new_name)
        if os.path.exists(new_path): return False, "Target filename already exists."
        try:
            os.rename(old_path, new_path)
            conn = self.get_db_conn(); cursor = conn.cursor()
            # [關鍵修復 3] 改為更新 files 表
            cursor.execute("UPDATE files SET file_path = ?, filename = ? WHERE file_path = ?", (new_path, new_name, old_path))
            conn.commit(); conn.close()
            norm_new = os.path.normpath(new_path)
            for item in self.data_store:
                if item["path"] == old_path:
                    item["path"] = new_path; item["filename"] = new_name
                    item["norm_path"] = norm_new  # 快取欄位同步更新
                    break

            #  [新增] 同步更新 Hash Map 字典，維持 O(1) 搜尋的正確性
            if hasattr(self, 'path_map'):
                norm_old = os.path.normpath(old_path)
                if norm_old in self.path_map:
                    idx = self.path_map.pop(norm_old) # 抽出舊的
                    self.path_map[norm_new] = idx     # 塞入新的

            return True, new_path
        except Exception as e: return False, str(e)

    #  [新增] folder_path 參數
    def search_hybrid(self, query, top_k=50, use_ocr=True, weight_config=None, folder_path=None):
        current_embeddings = self.stored_embeddings
        current_data = self.data_store

        #  防呆檢查：確保 FAISS 引擎已經啟動
        if not self.is_ready or current_embeddings is None or not hasattr(self, 'faiss_index'):
            return []

        valid_indices = None
        if folder_path and folder_path != "ALL":
            norm_target = os.path.normpath(folder_path)
            valid_indices = [
                i for i, item in enumerate(current_data)
                if item["norm_path"].startswith(norm_target)
            ]
            if not valid_indices:
                return []

        query_lower = query.lower()
        try:
            if hasattr(self, 'last_text_query') and self.last_text_query == query and hasattr(self, 'last_text_features'):
                text_features = self.last_text_features
            else:
                inputs = self.tokenizer([query], padding="max_length", max_length=77, truncation=True, return_tensors="np")
                text_tokens = inputs.input_ids.astype(np.int64)
                input_name = self.clip_text_session.get_inputs()[0].name
                text_features = self.clip_text_session.run(None, {input_name: text_tokens})[0]
                text_features = text_features / np.linalg.norm(text_features, axis=-1, keepdims=True)

                self.last_text_query = query
                self.last_text_features = text_features

            query_vector = text_features.astype(np.float32)
            if len(query_vector.shape) == 1:
                query_vector = np.expand_dims(query_vector, axis=0)

            # ==========================================
            #  [關鍵修復 2] 動態發動 FAISS (支援「完全展開」)
            # 確保最少抓 1000 張當作文字緩衝，但如果 UI 選擇 All (top_k=100000)，就水門全開！
            # ==========================================
            k_results = min(max(1000, top_k), len(current_data))
            top_scores_matrix, top_indices_matrix = self.faiss_index.search(query_vector, k_results)
            top_scores = top_scores_matrix[0]
            top_indices = top_indices_matrix[0]

            # 建立 CLIP 分數對照表
            clip_score_map = {int(idx): float(score) for idx, score in zip(top_indices, top_scores)}

        except Exception as e:
            print(f"CLIP Search Error: {e}")
            clip_score_map = {}
            top_indices = []

        # ==========================================
        #  混合候選名單篩選 (Hybrid Selection)
        # ==========================================
        candidate_set = set(top_indices)

        # 光速篩選出文字或檔名命中的項目 (把它們也加入候選名單，保證文字搜尋絕對不漏接！)
        if query_lower:
            text_matched_indices = [
                i for i, item in enumerate(current_data)
                if (use_ocr and query_lower in item["ocr_text"]) or (query_lower in item["filename"].lower())
            ]
            candidate_set.update(text_matched_indices)

        # 如果有資料夾過濾，剔除不在該資料夾的圖片
        if valid_indices is not None:
            candidate_set = candidate_set.intersection(set(valid_indices))

        # ==========================================
        #  執行計分迴圈 (只針對幾千張的候選名單，不跑十萬張！)
        # ==========================================
        if weight_config is None:
            weight_config = {"mode": "multiply", "clip_w": 1.0, "ocr_w": 1.0, "name_w": 0.4, "thresh_mode": "auto", "thresh_val": 0.15}

        mode = weight_config.get("mode", "multiply")
        clip_w = weight_config.get("clip_w", 1.0)
        ocr_w = weight_config.get("ocr_w", 1.0)
        name_w = weight_config.get("name_w", 0.4)
        thresh_mode = weight_config.get("thresh_mode", "auto")
        thresh_val = weight_config.get("thresh_val", 0.15)

        raw_results = []
        max_score = 0.0

        for original_idx in candidate_set:
            item = current_data[original_idx]

            # 從對照表拿 CLIP 分數，沒在 Top 1000 裡的就當作 0 分
            clip_score = clip_score_map.get(original_idx, 0.0)

            has_ocr = use_ocr and (query_lower in item["ocr_text"])
            has_name = query_lower in item["filename"].lower()

            ocr_bonus = 0.0
            name_bonus = 0.0

            #  修復: 只要有文字命中，或者視覺分數及格，就給予加分！
            if clip_score >= 0.08 or has_ocr or has_name:
                if mode == "add":
                    ocr_bonus = (ocr_w / 2.0) if has_ocr else 0.0
                    name_bonus = (name_w / 2.0) if has_name else 0.0
                else:
                    ocr_bonus = (0.5 * ocr_w) if has_ocr else 0.0
                    name_bonus = (0.5 * name_w) if has_name else 0.0

            if mode == "add":
                final_score = clip_score + ocr_bonus + name_bonus
            else:
                final_score = (clip_score * clip_w) + ocr_bonus + name_bonus

            if final_score > max_score:
                max_score = final_score

            raw_results.append({
                "score": final_score, "clip_score": clip_score, "ocr_bonus": ocr_bonus, "name_bonus": name_bonus,
                "is_ocr_match": has_ocr, "path": item["path"], "filename": item["filename"],
                "mtime": item.get("mtime", 0),
                "width": item.get("width", 0),
                "height": item.get("height", 0)
            })

        if thresh_mode == "auto":
            actual_thresh = max_score * 0.5
        else:
            actual_thresh = thresh_val

        results = [r for r in raw_results if r["score"] >= actual_thresh]
        results.sort(key=lambda x: x["score"], reverse=True)
        return self._merge_pinned(results[:top_k])

    #  [修改] 新增 folder_path 參數 (上一階段已加)，並導入「O(1) 快取命中」邏輯
    def search_image(self, image_path, top_k=50, folder_path=None):
        current_embeddings = self.stored_embeddings
        current_data = self.data_store

        # 防呆檢查：確保 FAISS 引擎已經啟動
        if not self.is_ready or current_embeddings is None or not hasattr(self, 'faiss_index'):
            return []

        try:
            query_vector = None

            # ==========================================
            #  [效能封頂] 疑問 1 解決方案：記憶體 O(1) 特徵直接提取
            # ==========================================
            # 1. 嘗試在字典中瞬間尋找這張圖片
            target_idx = None
            norm_target_path = os.path.normpath(image_path)

            if hasattr(self, 'path_map') and norm_target_path in self.path_map:
                target_idx = self.path_map[norm_target_path]

            if target_idx is not None:
                # 2. 如果找到了！直接從記憶體把算好的向量抽出來 (0 毫秒)
                query_vector = np.expand_dims(current_embeddings[target_idx], axis=0)
            else:
                # 3. 如果找不到 (例如未來支援拖入外部圖片)，才啟動 ONNX 消耗算力
                #print(f"[Engine] 以圖搜圖：外部圖片，啟動 GPU 推論...")
                image = Image.open(image_path).convert('RGB')
                processed_image = np.expand_dims(self.preprocess(image), axis=0)

                input_name = self.clip_image_session.get_inputs()[0].name
                image_features = self.clip_image_session.run(None, {input_name: processed_image})[0]
                image_features = image_features / np.linalg.norm(image_features, axis=-1, keepdims=True)

                query_vector = image_features.astype(np.float32)

            # ==========================================
            #  發動 FAISS 以圖搜圖 (超額抓取與範圍過濾)
            # ==========================================
            # 為了確保「範圍過濾」後還有足夠的圖片，我們先跟 FAISS 要一大把
            fetch_limit = min(max(2000, top_k), len(current_data))
            top_scores_matrix, top_indices_matrix = self.faiss_index.search(query_vector, fetch_limit)

            top_scores = top_scores_matrix[0]
            top_indices = top_indices_matrix[0]

            # 準備過濾條件
            norm_target = os.path.normpath(folder_path) if (folder_path and folder_path != "ALL") else None

            results = []
            for i in range(fetch_limit):
                idx = top_indices[i]
                item = current_data[idx]

                # 如果有指定資料夾，且圖片不在該資料夾內，直接丟棄！
                if norm_target and not item["norm_path"].startswith(norm_target):
                    continue

                score = top_scores[i]
                results.append({
                    "score": float(score), "clip_score": float(score), "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                    "path": item["path"], "filename": item["filename"],
                    "mtime": item.get("mtime", 0),
                    "width": item.get("width", 0),
                    "height": item.get("height", 0)
                })

                # 收集滿目標數量就可以提早收工
                if len(results) >= top_k:
                    break

            return self._merge_pinned(results)
        except Exception as e:
            print(f"[Error] Image search failed: {e}"); return []

    # ==========================================
    # OCR 框資料 — 已委派至 self.ocr_repo (OcrRepository)
    # 保留原方法簽章作為 Thin Delegation Layer，確保 PreviewOverlay、
    # PreviewLoader、inspector_panel 等呼叫端完全向後相容（Phase 1-B）。
    # ==========================================
    def get_ocr_data_by_path(self, file_path):
        """[委派] 懶加載通道：只有在預覽時，才去資料庫把這張圖片的座標 JSON 撈出來。"""
        return self.ocr_repo.get_by_path(file_path)

    def upsert_crop_ocr(self, file_path: str, new_items: list) -> bool:
        """[委派] 將框選 OCR 結果合併寫入資料庫（每語系獨立處理 upsert）。"""
        return self.ocr_repo.upsert(file_path, new_items)

    def delete_ocr_box(self, file_path: str, lang: str, box_to_delete: list) -> bool:
        """[委派] 從指定語系的 ocr_data 中移除符合座標的框（±2px 容忍度比對）。"""
        return self.ocr_repo.delete_box(file_path, lang, box_to_delete)

    def update_ocr_box_text(self, file_path: str, lang: str, box_to_match: list, new_text: str) -> bool:
        """[委派] 將指定框的辨識文字更新為 new_text，座標不變（±2px 容忍度比對）。"""
        return self.ocr_repo.update_box_text(file_path, lang, box_to_match, new_text)

    def get_text_vector(self, text):
        """瞬間產生文字的 1024 維特徵 (約 0.05 秒)"""
        if not self.is_ready or not hasattr(self, 'clip_text_session'): return None
        inputs = self.tokenizer([text], padding="max_length", max_length=77, truncation=True, return_tensors="np")
        text_tokens = inputs.input_ids.astype(np.int64)
        input_name = self.clip_text_session.get_inputs()[0].name
        text_features = self.clip_text_session.run(None, {input_name: text_tokens})[0]
        return text_features[0] / np.linalg.norm(text_features[0], axis=-1, keepdims=True)

    # ==========================================
    #  [修復版] 多模態特徵組合搜尋 (Vector Arithmetic)
    # ==========================================
    def search_multi_vector(self, pos_features, neg_features, top_k=50, folder_path=None):
        if not self.is_ready or self.stored_embeddings is None: return []

        def get_vec(feat):
            if feat.vector is not None: return feat.vector # 命中預熱快取！(0毫秒)
            if feat.type == 'image':
                norm_target_path = os.path.normpath(feat.data)
                if hasattr(self, 'path_map') and norm_target_path in self.path_map:
                    feat.vector = self.stored_embeddings[self.path_map[norm_target_path]]
                    return feat.vector
                try:
                    image = Image.open(feat.data).convert('RGB')
                    processed = np.expand_dims(self.preprocess(image), axis=0)
                    input_name = self.clip_image_session.get_inputs()[0].name
                    vec = self.clip_image_session.run(None, {input_name: processed})[0]
                    feat.vector = vec[0] / np.linalg.norm(vec[0], axis=-1, keepdims=True)
                    return feat.vector
                except: return None
            elif feat.type == 'text':
                feat.vector = self.get_text_vector(feat.data)
                return feat.vector

        pos_vecs = [v for f in pos_features if (v := get_vec(f)) is not None]
        neg_vecs = [v for f in neg_features if (v := get_vec(f)) is not None]
        if not pos_vecs and not neg_vecs: return []

        dim = self.stored_embeddings.shape[1]
        v_pos = np.mean(pos_vecs, axis=0) if pos_vecs else np.zeros(dim, dtype=np.float32)
        v_neg = np.mean(neg_vecs, axis=0) if neg_vecs else np.zeros(dim, dtype=np.float32)

        query_vector = v_pos - (0.6 * v_neg)
        if not pos_vecs and neg_vecs: query_vector = -v_neg

        query_vector = np.expand_dims(query_vector, axis=0)
        query_vector = query_vector / np.linalg.norm(query_vector, axis=-1, keepdims=True)
        query_vector = query_vector.astype(np.float32)

        fetch_limit = min(max(2000, top_k), len(self.data_store))
        top_scores, top_indices = self.faiss_index.search(query_vector, fetch_limit)

        norm_folder = os.path.normpath(folder_path) if (folder_path and folder_path != "ALL") else None
        results = []
        for i in range(fetch_limit):
            idx = top_indices[0][i]
            item = self.data_store[idx]
            if norm_folder and not item["norm_path"].startswith(norm_folder): continue

            results.append({
                "score": float(top_scores[0][i]), "clip_score": float(top_scores[0][i]), "ocr_bonus": 0.0, "name_bonus": 0.0, "is_ocr_match": False,
                "path": item["path"], "filename": item["filename"], "mtime": item.get("mtime", 0),
                "width": item.get("width", 0), "height": item.get("height", 0)
            })
            if len(results) >= top_k: break
        return self._merge_pinned(results)

    # ==========================================
    #  虛擬資料夾 (Collections) 管理 API
    #  已委派至 self.collection_mgr (CollectionManager)
    #  保留原方法簽章作為 Thin Delegation Layer，確保 MainWindow 及
    #  ui/settings_pages/folders_page.py 等呼叫端完全向後相容（Phase 1-C）。
    # ==========================================

    def _ensure_icon_column(self, conn):
        """[委派] 冪等遷移：若 collections 尚無 icon 欄位則自動新增。"""
        self.collection_mgr._ensure_icon_column(conn)

    def add_collection(self, name: str, icon: str = "🏷️") -> bool:
        """[委派] 新增一個虛擬資料夾（含 icon 欄位自動遷移）。"""
        return self.collection_mgr.add_collection(name, icon)

    def get_collections(self) -> list:
        """[委派] 回傳 [(id, name, icon, count), ...]，供 UI 載入。"""
        return self.collection_mgr.get_collections()

    def remove_collection(self, collection_id: int) -> bool:
        """[委派] 刪除虛擬資料夾，並清除所有關聯的 collection_items。"""
        return self.collection_mgr.remove_collection(collection_id)

    def update_collection_icon(self, collection_id: int, icon: str) -> bool:
        """[委派] 更新虛擬資料夾的 emoji 圖示。"""
        return self.collection_mgr.update_collection_icon(collection_id, icon)

    def create_virtual_folder(self, name):
        """[委派] 建立新的虛擬資料夾（舊版 API，回傳 (success, id_or_error)）。"""
        return self.collection_mgr.create_virtual_folder(name)

    def get_virtual_folders(self):
        """[委派] 取得所有虛擬資料夾與其包含的圖片數量（舊版 API，不含 icon）。"""
        return self.collection_mgr.get_virtual_folders()

    def add_to_virtual_folder(self, collection_id, file_paths):
        """[委派] 將多張圖片加入虛擬資料夾（支援拖曳寫入）。"""
        return self.collection_mgr.add_to_virtual_folder(collection_id, file_paths)

    def get_virtual_folder_images(self, collection_id):
        """[委派] 取得特定虛擬資料夾內的所有圖片，用於顯示在畫廊。"""
        return self.collection_mgr.get_virtual_folder_images(collection_id)

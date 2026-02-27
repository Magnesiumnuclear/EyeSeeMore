import os
import sqlite3
import torch
from PIL import Image
import open_clip
import numpy as np
import logging
import json
import datetime
from paddleocr import PaddleOCR

class IndexerService:
    def __init__(self, db_path, model_name='xlm-roberta-large-ViT-H-14', pretrained_name='frozen_laion5b_s13b_b90k', use_gpu_ocr=False):
        self.db_path = db_path
        self.model_name = model_name
        self.pretrained_name = pretrained_name
        self.use_gpu_ocr = bool(use_gpu_ocr) # <--- 儲存使用者的 GPU 設定
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        logging.getLogger("ppocr").setLevel(logging.ERROR)

    def _get_conn(self):
        """取得資料庫連線，並強制開啟外鍵約束 (Foreign Key Constraints)"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self):
        """初始化全新三表架構資料庫"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        conn = self._get_conn()
        cursor = conn.cursor()
        
        # 表 A: files (實體檔案與 OCR 共用區)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            filename TEXT,
            folder_path TEXT,
            mtime REAL,
            ocr_text TEXT,
            ocr_data TEXT
        )
        ''')
        
        # 表 B: embeddings (AI 模型特徵區 - 綁定 files 的 id)
        # ON DELETE CASCADE 代表：當 files 裡的一筆資料被刪除，這裡對應的所有模型向量都會自動蒸發
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS embeddings (
            file_id INTEGER,
            model_name TEXT,
            embedding BLOB,
            PRIMARY KEY (file_id, model_name),
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        )
        ''')
        
        # 表 C: model_stats (統計與日期區)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_stats (
            model_name TEXT,
            folder_path TEXT,
            image_count INTEGER,
            last_scanned TEXT,
            PRIMARY KEY (model_name, folder_path)
        )
        ''')
        conn.commit()
        return conn

    # ==========================================
    #  功能 1: 智慧掃描與分類
    # ==========================================
    def scan_for_new_files(self, source_folders):
        """
        掃描磁碟，區分需要「完整掃描」與「僅算向量」的檔案。
        :return: (files_full: list, files_emb_only: list, deleted_count: int)
        """
        if not source_folders:
            return [], [], 0

        conn = self.init_db()
        cursor = conn.cursor()
        
        # 1. 取得 DB 內所有的實體檔案路徑
        cursor.execute("SELECT file_path FROM files")
        db_paths = set(row[0] for row in cursor.fetchall())
        
        # 2. 取得「當前模型」已經算過向量的檔案路徑
        cursor.execute("""
            SELECT f.file_path FROM files f
            JOIN embeddings e ON f.id = e.file_id
            WHERE e.model_name = ?
        """, (self.model_name,))
        db_paths_with_emb = set(row[0] for row in cursor.fetchall())
        
        # 3. 掃描實體硬碟
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        disk_paths = set()
        
        for folder in source_folders:
            if not os.path.exists(folder): continue
            for root, _, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_extensions:
                        full_path = os.path.abspath(os.path.join(root, file))
                        disk_paths.add(full_path)
        
        # 4. 處理刪除 (硬碟已經沒有的圖，從 files 表刪除，對應的向量會自動被 CASCADE 清除)
        to_delete = db_paths - disk_paths
        deleted_count = len(to_delete)
        if to_delete:
            to_delete_list = list(to_delete)
            BATCH = 900
            for i in range(0, len(to_delete_list), BATCH):
                batch = to_delete_list[i:i+BATCH]
                placeholders = ','.join(['?'] * len(batch))
                cursor.execute(f"DELETE FROM files WHERE file_path IN ({placeholders})", batch)
            conn.commit()
            
        # 5. 情境一：全新圖片 (硬碟有，但 DB files 裡面完全沒有) -> 需要跑 OCR + CLIP
        files_full = list(disk_paths - db_paths)
        
        # 6. 情境二：切換模型 (硬碟有，DB files 也有 OCR 了，但當前模型沒算過) -> 只要跑 CLIP
        files_emb_only = list((disk_paths & db_paths) - db_paths_with_emb)
        
        # 更新目前模型的統計
        self.update_folder_stats(conn)
        conn.close()
        
        return files_full, files_emb_only, deleted_count

    # ==========================================
    #  功能 2: 雙軌 AI 處理
    # ==========================================
    def run_ai_processing(self, files_full, files_emb_only, progress_callback=None, shared_model=None, shared_preprocess=None):
        """
        對指定檔案執行 AI 索引 (分為完整處理與僅補算特徵)
        """
        if not files_full and not files_emb_only:
            return

        conn = self._get_conn() # 這裡也要用 _get_conn 確保外鍵開啟
        cursor = conn.cursor()
        
        total_files = len(files_full) + len(files_emb_only)
        current_progress = 0
        
        # 載入模型 (如果只有 files_emb_only，OCR 就不需要載入，省資源！)
        try:
            if progress_callback: progress_callback(0, total_files, "Loading AI Models...")
            
            if shared_model and shared_preprocess:
                print("[Indexer] Using shared OpenCLIP model from main engine.")
                model = shared_model
                preprocess = shared_preprocess
                ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False, use_gpu=self.use_gpu_ocr) if files_full else None
            else:
                model, preprocess, ocr_engine = self.load_ai_models(need_ocr=bool(files_full))
                
        except Exception as e:
            print(f"Model Load Failed: {e}")
            conn.close()
            return

        BATCH_SIZE = 4
        
        # ---------------------------------------------------------
        #  階段 A: 完整處理全新圖片 (OCR + CLIP)
        # ---------------------------------------------------------
        for i in range(0, len(files_full), BATCH_SIZE):
            batch_paths = files_full[i : i + BATCH_SIZE]
            batch_images = []
            files_insert_data = []
            
            if progress_callback: progress_callback(current_progress, total_files, f"Full AI (OCR+CLIP): {current_progress}/{total_files}...")

            for path in batch_paths:
                try:
                    img = Image.open(path).convert('RGB')
                    processed_img = preprocess(img).unsqueeze(0)
                    
                    # 跑 OCR
                    ocr_text_final = ""
                    ocr_data_final = "[]"
                    if ocr_engine:
                        ocr_result = ocr_engine.ocr(path, cls=False)
                        detected_text_list = []
                        json_data_list = []
                        if ocr_result and ocr_result[0]:
                            for line in ocr_result[0]:
                                box, (text, conf) = line[0], line[1]
                                clean_box = [[int(pt[0]), int(pt[1])] for pt in box]
                                detected_text_list.append(text)
                                json_data_list.append({"box": clean_box, "text": text, "conf": round(float(conf), 4)})
                        ocr_text_final = " ".join(detected_text_list)
                        ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)
                    
                    batch_images.append(processed_img)
                    files_insert_data.append((
                        path, os.path.basename(path), os.path.dirname(path), 
                        os.path.getmtime(path), ocr_text_final, ocr_data_final
                    ))
                except Exception as e:
                    print(f"Skipping {path}: {e}")
                    continue

            if not batch_images: 
                current_progress += len(batch_paths)
                continue

            # 1. 寫入 files 表
            try:
                cursor.executemany('''
                    INSERT OR IGNORE INTO files (file_path, filename, folder_path, mtime, ocr_text, ocr_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', files_insert_data)
                conn.commit()
            except sqlite3.Error as e: print(f"DB Insert files Error: {e}")

            # 2. 跑 CLIP 算向量
            embeddings_list = self._compute_clip(model, batch_images)
            
            # 3. 從 DB 查回剛才寫入的 file_id
            paths_tuple = tuple(p[0] for p in files_insert_data)
            placeholders = ','.join(['?'] * len(paths_tuple))
            cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", paths_tuple)
            id_map = {row[0]: row[1] for row in cursor.fetchall()}
            
            # 4. 寫入 embeddings 表
            emb_insert_data = []
            for idx, item in enumerate(files_insert_data):
                path = item[0]
                file_id = id_map.get(path)
                if file_id is not None:
                    emb_insert_data.append((file_id, self.model_name, embeddings_list[idx]))
            
            try:
                cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
                conn.commit()
            except sqlite3.Error: pass

            current_progress += len(batch_paths)

        # ---------------------------------------------------------
        #  階段 B: 僅補算切換模型的向量 (光速 CLIP)
        # ---------------------------------------------------------
        for i in range(0, len(files_emb_only), BATCH_SIZE):
            batch_paths = files_emb_only[i : i + BATCH_SIZE]
            batch_images = []
            valid_paths = []
            
            if progress_callback: progress_callback(current_progress, total_files, f"Fast CLIP (No OCR): {current_progress}/{total_files}...")

            for path in batch_paths:
                try:
                    img = Image.open(path).convert('RGB')
                    processed_img = preprocess(img).unsqueeze(0)
                    batch_images.append(processed_img)
                    valid_paths.append(path)
                except Exception as e: continue

            if not batch_images: 
                current_progress += len(batch_paths)
                continue

            # 1. 跑 CLIP 算向量
            embeddings_list = self._compute_clip(model, batch_images)
            
            # 2. 查回 file_id (因為它們已經在 files 表裡了)
            paths_tuple = tuple(valid_paths)
            placeholders = ','.join(['?'] * len(paths_tuple))
            cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", paths_tuple)
            id_map = {row[0]: row[1] for row in cursor.fetchall()}
            
            # 3. 寫入 embeddings 表
            emb_insert_data = []
            for idx, path in enumerate(valid_paths):
                file_id = id_map.get(path)
                if file_id is not None:
                    emb_insert_data.append((file_id, self.model_name, embeddings_list[idx]))
            
            try:
                cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
                conn.commit()
            except sqlite3.Error: pass

            current_progress += len(batch_paths)

        # 最後更新一次統計
        self.update_folder_stats(conn)
        conn.close()

    def _compute_clip(self, model, batch_images):
        """內部輔助函式：執行 CLIP 推理並回傳 BLOB 列表"""
        with torch.no_grad():
            use_amp = (self.device == 'cuda')
            with torch.amp.autocast(device_type=self.device, enabled=use_amp):
                image_input = torch.cat(batch_images).to(self.device)
                image_features = model.encode_image(image_input)
                image_features /= image_features.norm(dim=-1, keepdim=True)
                image_features = image_features.cpu().numpy()
        return [emb.astype(np.float32).tobytes() for emb in image_features]

    def load_ai_models(self, need_ocr=True):
        print(f"Loading Models on {self.device}...")
        model, _, preprocess = open_clip.create_model_and_transforms(
            self.model_name, pretrained=self.pretrained_name, device=self.device
        )
        model.eval()
        ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False, use_gpu=self.use_gpu_ocr) if need_ocr else None

        # [新增] 攔截日誌：強制將 ppocr 的日誌層級設為 ERROR，這樣 WARNING 就不會顯示了
        if ocr_engine:
            logging.getLogger("ppocr").setLevel(logging.ERROR)

        return model, preprocess, ocr_engine

    def update_folder_stats(self, conn):
        """更新 model_stats，確保依據不同模型獨立統計"""
        cursor = conn.cursor()
        cursor.execute("DELETE FROM model_stats WHERE model_name = ?", (self.model_name,))
        cursor.execute("""
            INSERT INTO model_stats (model_name, folder_path, image_count, last_scanned)
            SELECT e.model_name, f.folder_path, COUNT(f.id), datetime('now', 'localtime')
            FROM files f
            JOIN embeddings e ON f.id = e.file_id
            WHERE e.model_name = ?
            GROUP BY f.folder_path
        """, (self.model_name,))
        conn.commit()
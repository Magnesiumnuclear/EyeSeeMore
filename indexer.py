import os
# [新增] 在最頂端限制 Paddle 的記憶體貪婪策略 (Auto Growth)
os.environ["FLAGS_allocator_strategy"] = "auto_growth"

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
        
        # ==========================================
        # [關鍵修復] 根據使用者設定，提前攔截 Paddle 的全域硬體佔用
        # ==========================================
        try:
            import paddle
            if not self.use_gpu_ocr:
                paddle.device.set_device('cpu') # 強制將 Paddle 全域設為 CPU，完全釋放 VRAM
            else:
                paddle.device.set_device('gpu') # 使用 GPU 時，配合頂部的 auto_growth 也能避免一次佔滿
        except Exception as e:
            pass
        # ==========================================

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
    #  功能 1: 智慧掃描與分類 (支援 3 軌道任務)
    # ==========================================
    def scan_for_new_files(self, source_folders_config):
        """
        掃描磁碟，區分需要「完整掃描」、「僅算向量」與「精準補算 OCR」的檔案。
        """
        if not source_folders_config:
            return [], [], [], 0, {}

        # 建立快速查詢表 (路徑 -> 是否使用 OCR)
        folder_ocr_map = {}
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        disk_paths = set()
        
        for f_conf in source_folders_config:
            folder = os.path.normpath(f_conf["path"])
            use_ocr = f_conf.get("use_ocr", True)
            folder_ocr_map[folder] = use_ocr
            
            if not os.path.exists(folder): continue
            for root, _, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_extensions:
                        full_path = os.path.normpath(os.path.join(root, file))
                        disk_paths.add(full_path)

        conn = self.init_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT file_path FROM files")
        db_paths = set(os.path.normpath(row[0]) for row in cursor.fetchall())
        
        cursor.execute("""
            SELECT f.file_path FROM files f
            JOIN embeddings e ON f.id = e.file_id
            WHERE e.model_name = ?
        """, (self.model_name,))
        db_paths_with_emb = set(os.path.normpath(row[0]) for row in cursor.fetchall())
        
        # 找出從未執行過 OCR (ocr_text IS NULL) 的圖片
        cursor.execute("SELECT file_path FROM files WHERE ocr_text IS NULL")
        db_paths_null_ocr = set(os.path.normpath(row[0]) for row in cursor.fetchall())
        
        # 處理刪除
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
            
        # 軌道 A：全新圖片
        files_full = list(disk_paths - db_paths)
        
        # 軌道 B：僅補算 CLIP 向量
        files_emb_only = list((disk_paths & db_paths) - db_paths_with_emb)
        
        # 軌道 C：精準補算 OCR (硬碟有、資料庫有、OCR 為 NULL，且該資料夾現在設定為 ON)
        potential_ocr_paths = (disk_paths & db_paths) & db_paths_null_ocr
        files_ocr_only = []
        for p in potential_ocr_paths:
            if self._get_folder_ocr_setting(p, folder_ocr_map):
                files_ocr_only.append(p)
        
        self.update_folder_stats(conn)
        conn.close()
        
        return files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map

    def _get_folder_ocr_setting(self, path, folder_ocr_map):
        """輔助函式：根據圖片路徑判斷其所屬資料夾的 OCR 設定"""
        path_norm = os.path.normpath(path)
        matched_folder = ""
        use_ocr = False
        for folder_path, setting in folder_ocr_map.items():
            if path_norm.startswith(folder_path) and len(folder_path) > len(matched_folder):
                matched_folder = folder_path
                use_ocr = setting
        return use_ocr

    # ==========================================
    #  功能 2: 三軌 AI 處理
    # ==========================================
    def run_ai_processing(self, files_full, files_emb_only, files_ocr_only, folder_ocr_map, progress_callback=None, shared_model=None, shared_preprocess=None):
        """
        三軌道 AI 處理引擎
        """
        if not files_full and not files_emb_only and not files_ocr_only:
            return

        conn = self._get_conn() 
        cursor = conn.cursor()
        total_files = len(files_full) + len(files_emb_only) + len(files_ocr_only)
        current_progress = 0
        
        # 判斷是否需要喚醒 OCR 引擎 (省記憶體關鍵)
        need_ocr = bool(files_ocr_only)
        if not need_ocr:
            for f in files_full:
                if self._get_folder_ocr_setting(f, folder_ocr_map):
                    need_ocr = True
                    break
                    
        try:
            if progress_callback: progress_callback(0, total_files, "Loading AI Models...")
            if shared_model and shared_preprocess:
                print("[Indexer] Using shared OpenCLIP model from main engine.")
                model = shared_model
                preprocess = shared_preprocess
                ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False, use_gpu=self.use_gpu_ocr) if need_ocr else None
            else:
                model, preprocess, ocr_engine = self.load_ai_models(need_ocr=need_ocr)
        except Exception as e:
            print(f"Model Load Failed: {e}"); conn.close(); return

        BATCH_SIZE = 4
        
        # --- 軌道 A: 全新圖片 (OCR + CLIP) ---
        for i in range(0, len(files_full), BATCH_SIZE):
            batch_paths = files_full[i : i + BATCH_SIZE]
            batch_images = []
            files_insert_data = []
            if progress_callback: progress_callback(current_progress, total_files, f"Full AI: {current_progress}/{total_files}...")

            for path in batch_paths:
                try:
                    img = Image.open(path).convert('RGB')
                    processed_img = preprocess(img).unsqueeze(0)
                    
                    use_ocr = self._get_folder_ocr_setting(path, folder_ocr_map)
                    ocr_text_final = None 
                    ocr_data_final = None 
                    
                    if use_ocr and ocr_engine:
                        ocr_result = ocr_engine.ocr(path, cls=False)
                        if ocr_result and ocr_result[0]:
                            detected_text_list = []
                            json_data_list = []
                            for line in ocr_result[0]:
                                box, (text, conf) = line[0], line[1]
                                detected_text_list.append(text)
                                json_data_list.append({"box": [[int(pt[0]), int(pt[1])] for pt in box], "text": text, "conf": round(float(conf), 4)})
                            ocr_text_final = " ".join(detected_text_list)
                            ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)
                        else:
                            ocr_text_final = "[NONE]"
                            ocr_data_final = "[]"
                    
                    batch_images.append(processed_img)
                    files_insert_data.append((path, os.path.basename(path), os.path.dirname(path), os.path.getmtime(path), ocr_text_final, ocr_data_final))
                except Exception as e: continue

            if batch_images:
                try:
                    cursor.executemany('INSERT OR IGNORE INTO files (file_path, filename, folder_path, mtime, ocr_text, ocr_data) VALUES (?, ?, ?, ?, ?, ?)', files_insert_data)
                    conn.commit()
                except sqlite3.Error as e: print(f"DB Error: {e}")

                embeddings_list = self._compute_clip(model, batch_images)
                paths_tuple = tuple(p[0] for p in files_insert_data)
                placeholders = ','.join(['?'] * len(paths_tuple))
                cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", paths_tuple)
                id_map = {row[0]: row[1] for row in cursor.fetchall()}
                
                emb_insert_data = [(id_map.get(item[0]), self.model_name, embeddings_list[idx]) for idx, item in enumerate(files_insert_data) if id_map.get(item[0]) is not None]
                try:
                    cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
                    conn.commit()
                except sqlite3.Error: pass
            current_progress += len(batch_paths)

        # --- 軌道 B: 切換模型補算 (光速 CLIP) ---
        for i in range(0, len(files_emb_only), BATCH_SIZE):
            batch_paths = files_emb_only[i : i + BATCH_SIZE]
            batch_images = []; valid_paths = []
            if progress_callback: progress_callback(current_progress, total_files, f"Fast CLIP: {current_progress}/{total_files}...")
            for path in batch_paths:
                try:
                    img = Image.open(path).convert('RGB')
                    batch_images.append(preprocess(img).unsqueeze(0)); valid_paths.append(path)
                except Exception: continue

            if batch_images:
                embeddings_list = self._compute_clip(model, batch_images)
                paths_tuple = tuple(valid_paths)
                placeholders = ','.join(['?'] * len(paths_tuple))
                cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", paths_tuple)
                id_map = {row[0]: row[1] for row in cursor.fetchall()}
                emb_insert_data = [(id_map.get(p), self.model_name, embeddings_list[idx]) for idx, p in enumerate(valid_paths) if id_map.get(p) is not None]
                try:
                    cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
                    conn.commit()
                except sqlite3.Error: pass
            current_progress += len(batch_paths)

        # --- 軌道 C: 精準補算文字 (OCR Only) ---
        for i in range(0, len(files_ocr_only), BATCH_SIZE):
            batch_paths = files_ocr_only[i : i + BATCH_SIZE]
            if progress_callback: progress_callback(current_progress, total_files, f"Backfill OCR: {current_progress}/{total_files}...")
            update_data = []
            for path in batch_paths:
                try:
                    ocr_text_final = "[NONE]"
                    ocr_data_final = "[]"
                    if ocr_engine:
                        ocr_result = ocr_engine.ocr(path, cls=False)
                        if ocr_result and ocr_result[0]:
                            detected_text_list = []
                            json_data_list = []
                            for line in ocr_result[0]:
                                box, (text, conf) = line[0], line[1]
                                detected_text_list.append(text)
                                json_data_list.append({"box": [[int(pt[0]), int(pt[1])] for pt in box], "text": text, "conf": round(float(conf), 4)})
                            ocr_text_final = " ".join(detected_text_list)
                            ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)
                    update_data.append((ocr_text_final, ocr_data_final, path))
                except Exception as e: print(f"Skipping OCR {path}: {e}")
            
            if update_data:
                try:
                    cursor.executemany('UPDATE files SET ocr_text=?, ocr_data=? WHERE file_path=?', update_data)
                    conn.commit()
                except sqlite3.Error as e: print(f"Update OCR Error: {e}")
            current_progress += len(batch_paths)

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
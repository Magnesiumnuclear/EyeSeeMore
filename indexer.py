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
    def __init__(self, db_path, model_name='xlm-roberta-large-ViT-H-14', pretrained_name='frozen_laion5b_s13b_b90k'):
        self.db_path = db_path
        self.model_name = model_name
        self.pretrained_name = pretrained_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        logging.getLogger("ppocr").setLevel(logging.ERROR)

    def init_db(self):
        """初始化資料庫"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            filename TEXT,
            folder_path TEXT,
            mtime REAL,
            embedding BLOB,
            ocr_text TEXT,
            ocr_data TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS folder_stats (
            folder_path TEXT PRIMARY KEY,
            image_count INTEGER,
            last_updated TEXT
        )
        ''')
        conn.commit()
        return conn

    # ==========================================
    #  功能 1: 快速掃描是否有新圖片
    # ==========================================
    def scan_for_new_files(self, source_folders):
        """
        掃描磁碟與資料庫比對。
        :return: (files_to_add: list, deleted_count: int)
        """
        if not source_folders:
            return [], 0

        conn = self.init_db()
        cursor = conn.cursor()
        
        # 1. 取得資料庫內現有的檔案路徑
        cursor.execute("SELECT file_path FROM images")
        db_paths = set(row[0] for row in cursor.fetchall())
        
        # 2. 掃描硬碟
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        disk_paths = set()
        
        for folder in source_folders:
            if not os.path.exists(folder): continue
            for root, _, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_extensions:
                        full_path = os.path.abspath(os.path.join(root, file))
                        disk_paths.add(full_path)
        
        # 3. 處理刪除 (DB有，硬碟無)
        to_delete = db_paths - disk_paths
        deleted_count = len(to_delete)
        if to_delete:
            to_delete_list = list(to_delete)
            BATCH = 900
            for i in range(0, len(to_delete_list), BATCH):
                batch = to_delete_list[i:i+BATCH]
                placeholders = ','.join(['?'] * len(batch))
                cursor.execute(f"DELETE FROM images WHERE file_path IN ({placeholders})", batch)
            conn.commit()
            
        # 4. 找出新增 (硬碟有，DB無)
        to_add = list(disk_paths - db_paths)
        
        # 更新統計數據
        self.update_folder_stats(conn)
        conn.close()
        
        return to_add, deleted_count

    # ==========================================
    #  功能 2: 跑 OpenCLIP + OCR (耗時)
    # ==========================================
    def run_ai_processing(self, files_to_process, progress_callback=None, shared_model=None, shared_preprocess=None):
        """
        對指定檔案列表執行 AI 索引
        :param files_to_process: 檔案路徑列表
        :param progress_callback: 回呼函式 function(current, total, message)
        """
        if not files_to_process:
            return

        conn = self.init_db()
        cursor = conn.cursor()
        
        # 載入模型
        try:
            if progress_callback: progress_callback(0, len(files_to_process), "Loading AI Models...")
            
            # [關鍵修復] 如果主程式已經提供了模型，就直接共用，避免 VRAM 撐爆
            if shared_model and shared_preprocess:
                print("[Indexer] Using shared OpenCLIP model from main engine.")
                model = shared_model
                preprocess = shared_preprocess
                # OCR 還是需要獨立載入，因為它佔用很小
                ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
            else:
                model, preprocess, ocr_engine = self.load_ai_models()
                
        except Exception as e:
            print(f"Model Load Failed: {e}")
            conn.close()
            return

        if not model or not ocr_engine:
            conn.close()
            return

        BATCH_SIZE = 4
        total_files = len(files_to_process)
        
        for i in range(0, total_files, BATCH_SIZE):
            batch_paths = files_to_process[i : i + BATCH_SIZE]
            batch_images = []
            db_data = []
            
            # 回報進度
            if progress_callback:
                progress_callback(i, total_files, f"Processing {i}/{total_files}...")

            for path in batch_paths:
                try:
                    img = Image.open(path).convert('RGB')
                    processed_img = preprocess(img).unsqueeze(0)
                    
                    # OCR
                    ocr_result = ocr_engine.ocr(path, cls=True)
                    detected_text_list = []
                    json_data_list = []
                    
                    if ocr_result and ocr_result[0]:
                        for line in ocr_result[0]:
                            box = line[0]
                            text = line[1][0]
                            conf = line[1][1]
                            clean_box = [[int(pt[0]), int(pt[1])] for pt in box]
                            detected_text_list.append(text)
                            json_data_list.append({"box": clean_box, "text": text, "conf": round(float(conf), 4)})
                    
                    batch_images.append(processed_img)
                    db_data.append({
                        "path": path,
                        "filename": os.path.basename(path),
                        "folder": os.path.dirname(path),
                        "mtime": os.path.getmtime(path),
                        "ocr_text": " ".join(detected_text_list),
                        "ocr_data": json.dumps(json_data_list, ensure_ascii=False)
                    })
                except Exception as e:
                    print(f"Skipping {path}: {e}")
                    continue

            if not batch_images: continue

            # CLIP Inference
            with torch.no_grad():
                use_amp = (self.device == 'cuda')
                with torch.amp.autocast(device_type=self.device, enabled=use_amp):
                    image_input = torch.cat(batch_images).to(self.device)
                    image_features = model.encode_image(image_input)
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    image_features = image_features.cpu().numpy()

            # Insert DB
            final_insert_data = []
            for idx, item in enumerate(db_data):
                emb_blob = image_features[idx].astype(np.float32).tobytes()
                final_insert_data.append((
                    item["path"], item["filename"], item["folder"], 
                    item["mtime"], emb_blob, item["ocr_text"], item["ocr_data"]
                ))
            
            try:
                cursor.executemany('''
                    INSERT INTO images (file_path, filename, folder_path, mtime, embedding, ocr_text, ocr_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', final_insert_data)
                conn.commit()
            except sqlite3.IntegrityError:
                pass

        # 最後更新一次統計
        self.update_folder_stats(conn)
        conn.close()

    def load_ai_models(self):
        print(f"Loading Models on {self.device}...")
        model, _, preprocess = open_clip.create_model_and_transforms(
            self.model_name, pretrained=self.pretrained_name, device=self.device
        )
        model.eval()
        ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
        return model, preprocess, ocr_engine

    def update_folder_stats(self, conn):
        cursor = conn.cursor()
        cursor.execute("DELETE FROM folder_stats")
        cursor.execute("""
            INSERT INTO folder_stats (folder_path, image_count, last_updated)
            SELECT folder_path, COUNT(*), datetime('now', 'localtime')
            FROM images GROUP BY folder_path
        """)
        conn.commit()
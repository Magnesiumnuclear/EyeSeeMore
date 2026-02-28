import os
# 在最頂端限制 Paddle 的記憶體貪婪策略 (Auto Growth)
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

# ==========================================
# [新增] 效能監控「總開關」與動態工具
# ==========================================
# 總開關：設為 True 啟動所有效能 X 光機，設為 False 徹底安靜且零效能負擔
ENABLE_PROFILING = False  

def perf_print(*args, **kwargs):
    """自訂列印函數：只有在開啟效能監控時才會印出東西"""
    if ENABLE_PROFILING:
        print(*args, **kwargs)

def optional_mem_profile(func):
    """自訂裝飾器：動態決定是否要掛載 memory_profiler"""
    if ENABLE_PROFILING:
        from memory_profiler import profile
        return profile(func)
    return func

import psutil
from torch.profiler import profile as torch_profile, record_function, ProfilerActivity
# ==========================================

class IndexerService:
    def __init__(self, db_path, model_name='xlm-roberta-large-ViT-H-14', pretrained_name='frozen_laion5b_s13b_b90k', use_gpu_ocr=False):
        self.db_path = db_path
        self.model_name = model_name
        self.pretrained_name = pretrained_name
        self.use_gpu_ocr = bool(use_gpu_ocr) 
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # [修改] 使用 perf_print 取代一般的 print
        perf_print(f"\n{'='*50}")
        perf_print(f"[系統硬體] AI 初始化檢查")
        perf_print(f"{'='*50}")
        
        try:
            import paddle
            if not self.use_gpu_ocr:
                paddle.device.set_device('cpu')
            else:
                paddle.device.set_device('gpu')
            
            actual_paddle_device = paddle.device.get_device()
            perf_print(f"[OCR  設備] 使用者設定: {'GPU' if self.use_gpu_ocr else 'CPU'} | 實際綁定: {actual_paddle_device.upper()}")
        except Exception as e:
            perf_print(f"[OCR  設備] Paddle 環境檢查失敗: {e}")

        perf_print(f"[CLIP 設備] 系統支援最高硬體: {self.device.upper()}")
        perf_print(f"{'='*50}\n")

        logging.getLogger("ppocr").setLevel(logging.ERROR)

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir): os.makedirs(db_dir)
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE, filename TEXT, folder_path TEXT, mtime REAL, ocr_text TEXT, ocr_data TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS embeddings (file_id INTEGER, model_name TEXT, embedding BLOB, PRIMARY KEY (file_id, model_name), FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS model_stats (model_name TEXT, folder_path TEXT, image_count INTEGER, last_scanned TEXT, PRIMARY KEY (model_name, folder_path))''')
        conn.commit()
        return conn

    def scan_for_new_files(self, source_folders_config):
        if not source_folders_config:
            return [], [], [], 0, {}

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
        
        cursor.execute("SELECT file_path FROM files WHERE ocr_text IS NULL")
        db_paths_null_ocr = set(os.path.normpath(row[0]) for row in cursor.fetchall())
        
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
            
        files_full = list(disk_paths - db_paths)
        files_emb_only = list((disk_paths & db_paths) - db_paths_with_emb)
        
        potential_ocr_paths = (disk_paths & db_paths) & db_paths_null_ocr
        files_ocr_only = []
        for p in potential_ocr_paths:
            if self._get_folder_ocr_setting(p, folder_ocr_map):
                files_ocr_only.append(p)
        
        self.update_folder_stats(conn)
        conn.close()
        
        return files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map

    def _get_folder_ocr_setting(self, path, folder_ocr_map):
        path_norm = os.path.normpath(path)
        matched_folder = ""
        use_ocr = False
        for folder_path, setting in folder_ocr_map.items():
            if path_norm.startswith(folder_path) and len(folder_path) > len(matched_folder):
                matched_folder = folder_path
                use_ocr = setting
        return use_ocr

    # [修改] 使用我們自訂的 @optional_mem_profile 裝飾器
    @optional_mem_profile
    def run_ai_processing(self, files_full, files_emb_only, files_ocr_only, folder_ocr_map, progress_callback=None, shared_model=None, shared_preprocess=None):
        """三軌道 AI 處理引擎"""
        # [修改] 用 if 判斷來避免 psutil 去計算不需要的記憶體資訊
        if ENABLE_PROFILING:
            process = psutil.Process(os.getpid())
            start_mem = process.memory_info().rss / (1024 * 1024)
            perf_print(f"\n[系統資源] 開始處理前，程式佔用 RAM: {start_mem:.2f} MB")

        if not files_full and not files_emb_only and not files_ocr_only:
            return

        conn = self._get_conn() 
        cursor = conn.cursor()
        total_files = len(files_full) + len(files_emb_only) + len(files_ocr_only)
        current_progress = 0
        
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

        # [修改] 關閉效能開關時，這裡也不會執行
        if ENABLE_PROFILING:
            end_mem = process.memory_info().rss / (1024 * 1024)
            perf_print(f"[系統資源] 處理結束後，程式佔用 RAM: {end_mem:.2f} MB (變化: {end_mem - start_mem:+.2f} MB)\n")

    def _compute_clip(self, model, batch_images):
        with torch.no_grad():
            use_amp = (self.device == 'cuda')
            
            image_input = torch.cat(batch_images).to(self.device)
            # [修改] 使用 perf_print
            perf_print(f"[張量追蹤] 目前計算批次 (Batch Size: {len(batch_images)}) 被送往 -> {str(image_input.device).upper()}")

            # [修改] 如果沒有開啟效能監控，就不跑 ProfilerActivity，避免拖慢計算速度
            if ENABLE_PROFILING:
                with torch_profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA], record_shapes=True) as prof:
                    with torch.amp.autocast(device_type=self.device, enabled=use_amp):
                        with record_function("CLIP_Model_Forward"):
                            image_features = model.encode_image(image_input)
                            image_features /= image_features.norm(dim=-1, keepdim=True)
                
                sort_metric = "cuda_time_total" if self.device == 'cuda' else "cpu_time_total"
                perf_print(prof.key_averages().table(sort_by=sort_metric, row_limit=3))
            else:
                # 一般純粹的極速運算邏輯
                with torch.amp.autocast(device_type=self.device, enabled=use_amp):
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
        
        actual_clip_device = next(model.parameters()).device
        # [修改] 使用 perf_print
        perf_print(f"[CLIP 權重] 實際分配位置: {str(actual_clip_device).upper()}")

        ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False, use_gpu=self.use_gpu_ocr) if need_ocr else None
        if ocr_engine: logging.getLogger("ppocr").setLevel(logging.ERROR)

        return model, preprocess, ocr_engine

    def update_folder_stats(self, conn):
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
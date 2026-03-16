import os
import sqlite3
from PIL import Image, ExifTags, ImageOps
from PIL import Image
import numpy as np
import logging
import json
import datetime
import psutil
import onnxruntime as ort  # <--- 新增
from onnx_ocr import ONNXOCR


# ==========================================
# [新增] 讀取照片原始尺寸與 EXIF 旋轉標記
# ==========================================
def get_image_metadata(path):
    w, h, orientation = 0, 0, 1
    try:
        with Image.open(path) as pil_img:
            w, h = pil_img.size
            exif = pil_img.getexif()
            if exif:
                for k, v in exif.items():
                    if ExifTags.TAGS.get(k) == 'Orientation':
                        orientation = v
                        break
    except:
        pass
    return w, h, orientation

# ==========================================
# [新增] 根據 EXIF 將 OCR 原始座標翻轉為視覺正確座標
# ==========================================
def rotate_ocr_box(box, orientation, raw_w, raw_h):
    if orientation == 1: return box
    new_box = []
    for pt in box:
        x, y = pt[0], pt[1]
        if orientation == 2:   nx, ny = raw_w - x, y
        elif orientation == 3: nx, ny = raw_w - x, raw_h - y
        elif orientation == 4: nx, ny = x, raw_h - y
        elif orientation == 5: nx, ny = y, x
        elif orientation == 6: nx, ny = raw_h - y, x
        elif orientation == 7: nx, ny = raw_h - y, raw_w - x
        elif orientation == 8: nx, ny = y, raw_w - x
        else:                  nx, ny = x, y
        new_box.append([nx, ny])
    return new_box

# ==========================================
# [新增] 純 Numpy 的圖片預處理 (完全取代 PyTorch & open_clip)
# ==========================================
class NumpyPreprocess:
    def __init__(self, size=224):
        self.size = size
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32).reshape(3, 1, 1)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32).reshape(3, 1, 1)

    def __call__(self, image: Image.Image):
        # 1. 智慧縮放 (短邊對齊 224)
        w, h = image.size
        if w < h:
            new_w = self.size; new_h = int(h * (self.size / w))
        else:
            new_h = self.size; new_w = int(w * (self.size / h))
        image = image.resize((new_w, new_h), Image.Resampling.BICUBIC)
        
        # 2. 中央裁切
        left = (new_w - self.size) // 2
        top = (new_h - self.size) // 2
        image = image.crop((left, top, left + self.size, top + self.size))
        
        # 3. 轉 Numpy、歸一化、調換維度為 CHW
        img_arr = np.array(image).astype(np.float32) / 255.0
        img_arr = img_arr.transpose((2, 0, 1))
        img_arr = (img_arr - self.mean) / self.std
        return img_arr

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
# 已經全面改用 ONNX，不再需要 torch 的效能監控
# from torch.profiler import profile as torch_profile, record_function, ProfilerActivity
# ==========================================

class IndexerService:
    def __init__(self, db_path, model_name='xlm-roberta-large-ViT-H-14', pretrained_name='frozen_laion5b_s13b_b90k', use_gpu_ocr=False):
        self.db_path = db_path
        self.model_name = model_name
        self.pretrained_name = pretrained_name
        self.use_gpu_ocr = bool(use_gpu_ocr) 
        self.device = "dml" if 'DmlExecutionProvider' in ort.get_available_providers() else "cpu"
        
        # [修改] 使用 perf_print 取代一般的 print
        perf_print(f"\n{'='*50}")
        perf_print(f"[系統硬體] AI 初始化檢查")
        perf_print(f"{'='*50}")
        
        # ONNX Runtime 設備狀態印出
        perf_print(f"[OCR  設備] 使用者設定: {'GPU' if self.use_gpu_ocr else 'CPU'} (ONNX Runtime)")

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
        
        # 1. 建立主檔案表 (🌟 新增 width, height, file_size 欄位，移除 ocr_text, ocr_data)
        cursor.execute('''CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            file_path TEXT UNIQUE, 
            filename TEXT, 
            folder_path TEXT, 
            mtime REAL,
            width INTEGER,
            height INTEGER,
            file_size INTEGER
        )''')
        
        # ==========================================
        # 🌟 自動資料庫遷移 (Migration)
        # ==========================================
        cursor.execute("PRAGMA table_info(files)")
        columns = [info[1] for info in cursor.fetchall()]

        # A. 補齊缺失的寬高與大小欄位 (針對舊資料庫)
        if 'width' not in columns:
            perf_print("[Indexer] 升級資料庫：新增尺寸與大小欄位...")
            cursor.execute("ALTER TABLE files ADD COLUMN width INTEGER")
            cursor.execute("ALTER TABLE files ADD COLUMN height INTEGER")
            cursor.execute("ALTER TABLE files ADD COLUMN file_size INTEGER")

        # B. 砍掉殘留的 OCR 欄位 (瘦身)
        if 'ocr_text' in columns:
            try:
                perf_print("[Indexer] 升級資料庫：清除殘留的舊版 OCR 欄位...")
                cursor.execute("ALTER TABLE files DROP COLUMN ocr_text")
                cursor.execute("ALTER TABLE files DROP COLUMN ocr_data")
            except Exception as e:
                perf_print(f"[Indexer] 欄位清理略過 (SQLite 版本可能過舊不支援 DROP COLUMN): {e}")
        # ==========================================
        
        # 2. 建立 CLIP 向量表
        cursor.execute('''CREATE TABLE IF NOT EXISTS embeddings (file_id INTEGER, model_name TEXT, embedding BLOB, PRIMARY KEY (file_id, model_name), FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE)''')
        
        # 3. 建立統計表
        cursor.execute('''CREATE TABLE IF NOT EXISTS model_stats (model_name TEXT, folder_path TEXT, image_count INTEGER, last_scanned TEXT, PRIMARY KEY (model_name, folder_path))''')
        
        # 4. 建立多語系 OCR 子表
        cursor.execute('''CREATE TABLE IF NOT EXISTS ocr_results (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER, lang TEXT, ocr_text TEXT, ocr_data TEXT, confidence REAL, FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE)''')
        
        conn.commit()
        return conn

    def scan_for_new_files(self, source_folders_config):
        if not source_folders_config: return [], [], [], 0, {}

        folder_ocr_map = {}
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        disk_paths = set()
        
        for f_conf in source_folders_config:
            folder = os.path.normpath(f_conf["path"])
            enabled_langs = f_conf.get("enabled_langs", [])
            folder_ocr_map[folder] = enabled_langs
            
        # [Debug 日誌 1] 檢查從主程式傳遞過來的資料夾設定是否正確
        print(f"\n[Debug] 目前資料夾的 OCR 設定: {folder_ocr_map}")
            
        for folder in folder_ocr_map.keys():
            if not os.path.exists(folder): continue
            for root, _, files in os.walk(folder):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_extensions:
                        full_path = os.path.normpath(os.path.join(root, file))
                        disk_paths.add(full_path)

        conn = self.init_db()
        cursor = conn.cursor()
        
        # 1. 取得 DB 所有檔案
        cursor.execute("SELECT id, file_path FROM files")
        db_files = {os.path.normpath(row[1]): row[0] for row in cursor.fetchall()}
        db_paths = set(db_files.keys())
        
        # 2. 取得有 CLIP 向量的檔案
        cursor.execute("SELECT file_id FROM embeddings WHERE model_name = ?", (self.model_name,))
        db_has_emb = set(row[0] for row in cursor.fetchall())
        
        # 3. 取得所有檔案「已完成」的 OCR 語系
        cursor.execute("SELECT file_id, lang FROM ocr_results")
        ocr_history = {}
        for file_id, lang in cursor.fetchall():
            if file_id not in ocr_history: ocr_history[file_id] = set()
            ocr_history[file_id].add(lang)
            
        # [Debug 日誌 2] 檢查資料庫讀取狀況
        print(f"[Debug] 資料庫狀態 -> 總圖片數: {len(db_files)}, 有 CLIP 向量: {len(db_has_emb)}, 有 OCR 紀錄的圖片數: {len(ocr_history)}")
        
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
            
        files_full = list(disk_paths - db_paths) # 完全新圖
        files_emb_only = []
        files_ocr_only = []
        
        debug_print_limit = 0 # 限制印出次數避免洗頻
        
        # 交叉比對：找出缺 CLIP 或缺特定語系 OCR 的圖片
        for p in (disk_paths & db_paths):
            file_id = db_files[p]
            
            # 檢查是否缺 CLIP
            if file_id not in db_has_emb:
                files_emb_only.append(p)
                
            # 檢查 OCR (該資料夾勾選的 vs 該圖片實際跑過的)
            required_langs = self._get_folder_ocr_setting(p, folder_ocr_map)
            done_langs = ocr_history.get(file_id, set())
            
            # [Debug 日誌 3] 抽出前 5 張圖片來看看系統到底是怎麼判斷的
            if debug_print_limit < 5:
                print(f"[Debug] 圖片: {os.path.basename(p)}")
                print(f"         - 此資料夾需要的語系 (Required): {required_langs}")
                print(f"         - 此圖片已完成的語系 (Done): {done_langs}")
                debug_print_limit += 1
            
            # 只要有任何一個需要的語系沒跑過，就排入補算名單！
            if any(lang not in done_langs for lang in required_langs):
                files_ocr_only.append(p)
                
        # [Debug 日誌 4] 最終分類結果
        print(f"[Debug] 掃描分類結果 -> 全新圖(Full): {len(files_full)}, 缺向量(Emb): {len(files_emb_only)}, 缺OCR(Ocr): {len(files_ocr_only)}\n")

        # ==========================================
        # 🌟 軌道 D (已搬家): 在這裡確保每次掃描都會補齊缺失的尺寸資訊！
        # ==========================================
        cursor.execute("SELECT id, file_path FROM files WHERE width IS NULL OR file_size IS NULL")
        missing_meta_rows = cursor.fetchall()
        if missing_meta_rows:
            perf_print(f"[Indexer] 發現 {len(missing_meta_rows)} 張圖片缺少尺寸資訊，開始光速補齊...")
            meta_updates = []
            for row_id, path in missing_meta_rows:
                try:
                    file_size = os.path.getsize(path)
                    
                    # 🌟 [Opt] 讀取 EXIF 並交換長寬
                    raw_w, raw_h, orientation = get_image_metadata(path)
                    w, h = raw_w, raw_h
                    if orientation in [5, 6, 7, 8]:
                        w, h = raw_h, raw_w
                        
                    meta_updates.append((w, h, file_size, row_id))
                except Exception: pass
            
            if meta_updates:
                cursor.executemany("UPDATE files SET width=?, height=?, file_size=? WHERE id=?", meta_updates)
                conn.commit()
            perf_print(f"[Indexer] 已成功補齊 {len(meta_updates)} 張圖片的尺寸與大小資訊！")
        # ==========================================
        
        self.update_folder_stats(conn)
        conn.close()
        
        return files_full, files_emb_only, files_ocr_only, deleted_count, folder_ocr_map

    def _get_folder_ocr_setting(self, path, folder_ocr_map):
        path_norm = os.path.normpath(path)
        matched_folder = ""
        enabled_langs = [] # 預設空陣列
        for folder_path, langs in folder_ocr_map.items():
            if path_norm.startswith(folder_path) and len(folder_path) > len(matched_folder):
                matched_folder = folder_path
                enabled_langs = langs
        return enabled_langs

    @optional_mem_profile
    def run_ai_processing(self, files_full, files_emb_only, files_ocr_only, folder_ocr_map, progress_callback=None, shared_model=None, shared_preprocess=None, shared_ocr_engines=None):
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
        
        import gc
        
        # [修改 1] 收集本次掃描真正需要的語系
        needed_langs = set()
        for path in files_full + files_ocr_only:
            langs = self._get_folder_ocr_setting(path, folder_ocr_map)
            needed_langs.update(langs)
            
        try:
            # 載入 CLIP
            if shared_model and shared_preprocess:
                perf_print("[Indexer] Using shared OpenCLIP model from main engine.")
                model = shared_model
                preprocess = shared_preprocess
            else:
                model, preprocess, _ = self.load_ai_models(need_ocr=False)


            #這裡改成從避風港抓取，如果沒有才建立，建立後存回避風港！
            # [修改 2] OCR 引擎的載入也改成共享模式
            ocr_engines = shared_ocr_engines if shared_ocr_engines is not None else {}

            for lang in needed_langs:
                try:
                    ocr_engines[lang] = ONNXOCR(lang=lang, use_gpu=self.use_gpu_ocr)
                    perf_print(f"{self.model_name}_image.onnx")
                except Exception as e:
                    print(f"Skipping OCR lang '{lang}': {e}")

        except Exception as e:
            print(f"Model Load Failed: {e}"); conn.close(); return

        BATCH_SIZE = 4
        
        # --- 軌道 A: 全新圖片 (OCR + CLIP) ---
        for i in range(0, len(files_full), BATCH_SIZE):
            batch_paths = files_full[i : i + BATCH_SIZE]
            batch_images = []
            batch_meta = [] # 新增：用來裝 metadata
            if progress_callback: progress_callback(current_progress, total_files, f"Full AI: {current_progress}/{total_files}...")

            for path in batch_paths:
                try:
                    file_size = os.path.getsize(path)
                    # 🌟 [Opt] 讀取 EXIF 並交換長寬
                    raw_w, raw_h, orientation = get_image_metadata(path)
                    w, h = raw_w, raw_h
                    if orientation in [5, 6, 7, 8]:
                        w, h = raw_h, raw_w

                    with Image.open(path) as pil_img:
                        # 🌟 [AI 準確度升級] 使用 exif_transpose 把圖片轉正再送給 AI
                        img_rgb = ImageOps.exif_transpose(pil_img).convert('RGB')
                        
                    batch_images.append(np.expand_dims(preprocess(img_rgb), axis=0))
                    batch_meta.append((path, os.path.basename(path), os.path.dirname(path), os.path.getmtime(path), w, h, file_size))
                except Exception: continue

            if batch_images:
                try:
                    # 寫入 files：包含 width, height, file_size
                    cursor.executemany(
                        'INSERT OR IGNORE INTO files (file_path, filename, folder_path, mtime, width, height, file_size) VALUES (?, ?, ?, ?, ?, ?, ?)', 
                        batch_meta
                    )
                    conn.commit()
                except sqlite3.Error as e: print(f"DB Error: {e}")

                paths_tuple = tuple(batch_paths)
                placeholders = ','.join(['?'] * len(paths_tuple))
                # ... 後面寫入 CLIP 與 OCR 的程式碼維持不變 ...
                cursor.execute(f"SELECT file_path, id FROM files WHERE file_path IN ({placeholders})", paths_tuple)
                id_map = {row[0]: row[1] for row in cursor.fetchall()}
                
                # 2. 寫入 CLIP 向量
                embeddings_list = self._compute_clip(model, batch_images)
                emb_insert_data = [(id_map.get(batch_paths[idx]), self.model_name, embeddings_list[idx]) for idx in range(len(batch_paths)) if id_map.get(batch_paths[idx]) is not None]
                try:
                    cursor.executemany('INSERT OR IGNORE INTO embeddings (file_id, model_name, embedding) VALUES (?, ?, ?)', emb_insert_data)
                    conn.commit()
                except sqlite3.Error: pass
                
                # 3. 分語系跑 OCR，並寫入 ocr_results 子表
                ocr_insert_data = []
                for path in batch_paths:
                    file_id = id_map.get(path)
                    if not file_id: continue

                    raw_w, raw_h, orientation = get_image_metadata(path)
                    
                    required_langs = self._get_folder_ocr_setting(path, folder_ocr_map)
                    for target_lang in required_langs:
                        if target_lang in ocr_engines:
                            ocr_text_final, ocr_data_final = "[NONE]", "[]"
                            ocr_result = ocr_engines[target_lang].ocr(path, cls=False)
                            if ocr_result and ocr_result[0]:
                                detected_text_list = []
                                json_data_list = []
                                for line in ocr_result[0]:
                                    box, (text, conf) = line[0], line[1]
                                    
                                    # 🌟 將紅框座標進行 EXIF 翻轉校正後再存入資料庫
                                    if orientation != 1 and raw_w > 0:
                                        box = rotate_ocr_box(box, orientation, raw_w, raw_h)
                                        
                                    detected_text_list.append(text)
                                    json_data_list.append({"box": [[int(pt[0]), int(pt[1])] for pt in box], "text": text, "conf": round(float(conf), 4)})
                                ocr_text_final = " ".join(detected_text_list)
                                ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)
                            
                            ocr_insert_data.append((file_id, target_lang, ocr_text_final, ocr_data_final, 1.0))
                
                if ocr_insert_data:
                    cursor.executemany('INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) VALUES (?, ?, ?, ?, ?)', ocr_insert_data)
                    conn.commit()
            current_progress += len(batch_paths)

        # --- 軌道 B: 切換模型補算 (光速 CLIP) ---
        for i in range(0, len(files_emb_only), BATCH_SIZE):
            batch_paths = files_emb_only[i : i + BATCH_SIZE]
            batch_images = []; valid_paths = []
            if progress_callback: progress_callback(current_progress, total_files, f"Fast CLIP: {current_progress}/{total_files}...")
            for path in batch_paths:
                try:
                    with Image.open(path) as pil_img:
                        # 🌟 [AI 準確度升級] 轉正送給 CLIP
                        img_rgb = ImageOps.exif_transpose(pil_img).convert('RGB')
                    batch_images.append(np.expand_dims(preprocess(img_rgb), axis=0)); valid_paths.append(path)
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

        # --- 軌道 C: 精準補算文字 (缺哪國補哪國) ---
        for i in range(0, len(files_ocr_only), BATCH_SIZE):
            batch_paths = files_ocr_only[i : i + BATCH_SIZE]
            if progress_callback: progress_callback(current_progress, total_files, f"Backfill OCR: {current_progress}/{total_files}...")
            
            ocr_insert_data = []
            for path in batch_paths:
                try:
                    cursor.execute("SELECT id FROM files WHERE file_path=?", (path,))
                    row = cursor.fetchone()
                    if not row: continue
                    file_id = row[0]
                    
                    # 找出這張圖片到底「缺」了哪些標記
                    cursor.execute("SELECT lang FROM ocr_results WHERE file_id=?", (file_id,))
                    done_langs = set(r[0] for r in cursor.fetchall())
                    required_langs = self._get_folder_ocr_setting(path, folder_ocr_map)
                    missing_langs = [l for l in required_langs if l not in done_langs]
                    
                    # 針對缺少的語系補跑
                    for target_lang in missing_langs:
                        if target_lang in ocr_engines:
                            # 🌟 取得照片 EXIF
                            raw_w, raw_h, orientation = get_image_metadata(path) 
                            
                            ocr_text_final, ocr_data_final = "[NONE]", "[]"
                            ocr_result = ocr_engines[target_lang].ocr(path, cls=False)
                            if ocr_result and ocr_result[0]:
                                detected_text_list = []
                                json_data_list = []
                                for line in ocr_result[0]:
                                    box, (text, conf) = line[0], line[1]
                                    
                                    # 🌟 將紅框座標進行 EXIF 翻轉校正
                                    if orientation != 1 and raw_w > 0:
                                        box = rotate_ocr_box(box, orientation, raw_w, raw_h)
                                        
                                    detected_text_list.append(text)
                                    json_data_list.append({"box": [[int(pt[0]), int(pt[1])] for pt in box], "text": text, "conf": round(float(conf), 4)})
                                ocr_text_final = " ".join(detected_text_list)
                                ocr_data_final = json.dumps(json_data_list, ensure_ascii=False)
                            
                            ocr_insert_data.append((file_id, target_lang, ocr_text_final, ocr_data_final, 1.0))
                except Exception as e: print(f"Skipping OCR {path}: {e}")
            
            if ocr_insert_data:
                try:
                    cursor.executemany('INSERT INTO ocr_results (file_id, lang, ocr_text, ocr_data, confidence) VALUES (?, ?, ?, ?, ?)', ocr_insert_data)
                    conn.commit()
                except sqlite3.Error as e: print(f"Update OCR Error: {e}")
                
            current_progress += len(batch_paths)

        self.update_folder_stats(conn)
        conn.close()

        # ==========================================
        # [修改 4] 任務結束，強制銷毀所有 OCR 引擎釋放 VRAM(💥 已廢棄)
        # ==========================================
        # 🌟🌟🌟 絕對不能清空！DirectML 銷毀 Session 會導致 GPU 狀態毒化
        # ocr_engines.clear()
        # gc.collect()
        perf_print("[Indexer] OCR 任務結束，模型實例已銷毀，VRAM 釋放完畢。")

        if ENABLE_PROFILING:
            end_mem = process.memory_info().rss / (1024 * 1024)
            perf_print(f"[系統資源] 處理結束後，程式佔用 RAM: {end_mem:.2f} MB (變化: {end_mem - start_mem:+.2f} MB)\n")

    def _compute_clip(self, image_session, batch_images):
        # [關鍵修改] 不再使用 torch.cat，改用純 Numpy 的 concatenate
        image_input_np = np.concatenate(batch_images, axis=0)
        
        perf_print(f"[張量追蹤] 目前計算批次 (Batch Size: {len(batch_images)}) 被送往 -> ONNX Runtime")
        input_name = image_session.get_inputs()[0].name
        image_features = image_session.run(None, {input_name: image_input_np})[0]
        image_features = image_features / np.linalg.norm(image_features, axis=-1, keepdims=True)
            
        return [emb.astype(np.float32).tobytes() for emb in image_features]

    def load_ai_models(self, need_ocr=True):
        print(f"Loading Models via ONNX Runtime...")
        
        # [關鍵修改] 放棄 open_clip，直接實例化我們的 Numpy 引擎
        preprocess = NumpyPreprocess(size=224)
        
        onnx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "onnx_clip", f"{self.model_name}_image.onnx")
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider'] if (self.device == 'dml') else ['CPUExecutionProvider']
        
        image_session = ort.InferenceSession(onnx_path, providers=providers)
        ocr_engine = ONNXOCR(lang='ch', use_gpu=self.use_gpu_ocr) if need_ocr else None

        return image_session, preprocess, ocr_engine

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
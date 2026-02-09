import os
import sqlite3
import torch
from PIL import Image
import open_clip
from tqdm import tqdm
import numpy as np
import logging
import json  # 新增: 用於儲存座標資料

# 引入 PaddleOCR
from paddleocr import PaddleOCR

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data"
DB_PATH = "images.db"

# 模型設定
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'
# ----------------

# 抑制 Log
logging.getLogger("ppocr").setLevel(logging.ERROR)

def init_db(db_path):
    """初始化資料庫，包含自動遷移邏輯"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 建立主表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE,
        filename TEXT,
        folder_path TEXT,
        mtime REAL,
        embedding BLOB,
        ocr_text TEXT,
        ocr_data TEXT  -- 新增: 儲存 JSON 格式的座標與詳細資訊
    )
    ''')
    
    # --- 自動遷移: 檢查並新增欄位 ---
    existing_columns = set()
    try:
        cursor.execute("PRAGMA table_info(images)")
        for col in cursor.fetchall():
            existing_columns.add(col[1])
    except: pass

    # 補 ocr_text (舊版升級)
    if 'ocr_text' not in existing_columns:
        print("⚠️ 正在升級資料庫: 新增 'ocr_text' 欄位...")
        cursor.execute("ALTER TABLE images ADD COLUMN ocr_text TEXT")
    
    # 補 ocr_data (本次升級)
    if 'ocr_data' not in existing_columns:
        print("⚠️ 正在升級資料庫: 新增 'ocr_data' 欄位 (用於儲存座標)...")
        cursor.execute("ALTER TABLE images ADD COLUMN ocr_data TEXT")

    # 建立索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON images (filename)')
    
    conn.commit()
    return conn

def scan_disk_files(folder):
    """掃描硬碟中的所有圖片檔案，回傳完整路徑的 Set"""
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    disk_paths = set()
    print(f"📂 正在掃描硬碟: {folder} ...")
    for root, _, files in os.walk(folder):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                full_path = os.path.abspath(os.path.join(root, file))
                disk_paths.add(full_path)
    return disk_paths

def clean_deleted_files(conn, disk_paths):
    """檢查資料庫中過期的檔案 (已刪除或改名)，並移除之"""
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM images")
    db_paths = set(row[0] for row in cursor.fetchall())
    
    # 計算差異: 資料庫有 但 硬碟沒有 = 需刪除
    to_delete = db_paths - disk_paths
    
    if to_delete:
        print(f"🗑️ 發現 {len(to_delete)} 個檔案已刪除或改名，正在清理資料庫...")
        # 批次刪除
        # SQLite 的 IN clause 有長度限制，雖然通常很大，但分批刪除比較保險
        to_delete_list = list(to_delete)
        BATCH = 900
        for i in range(0, len(to_delete_list), BATCH):
            batch = to_delete_list[i:i+BATCH]
            placeholders = ','.join(['?'] * len(batch))
            cursor.execute(f"DELETE FROM images WHERE file_path IN ({placeholders})", batch)
        conn.commit()
        print("✅ 清理完成。")
    
    # 計算差異: 硬碟有 但 資料庫沒有 = 需新增
    to_add = disk_paths - db_paths
    return list(to_add)

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動全能索引引擎 (Device: {device.upper()})")

    conn = init_db(DB_PATH)
    
    # 1. 載入模型
    print(f"📥 正在載入 OpenCLIP & PaddleOCR...")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=PRETRAINED, device=device
        )
        model.eval()
        # use_angle_cls=False 加快速度，若你的圖片很多歪斜的再設為 True
        ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        conn.close()
        return

    # 2. 檔案同步 (Sync)
    disk_paths_set = scan_disk_files(IMAGE_FOLDER)
    files_to_process = clean_deleted_files(conn, disk_paths_set)

    if not files_to_process:
        print("✨ 資料庫已是最新狀態，無需更新。")
        conn.close()
        return

    print(f"🆕 發現 {len(files_to_process)} 張新圖片，開始建立索引...")

    # 3. 批次處理
    BATCH_SIZE = 4 # OCR 比較吃資源，如果顯存小可以調小
    cursor = conn.cursor()
    
    for i in tqdm(range(0, len(files_to_process), BATCH_SIZE), desc="Indexing"):
        batch_paths = files_to_process[i : i + BATCH_SIZE]
        
        batch_images = []
        db_data = []
        
        for path in batch_paths:
            try:
                # --- A. 圖片與 Metadata ---
                img = Image.open(path).convert('RGB')
                processed_img = preprocess(img).unsqueeze(0)
                
                filename = os.path.basename(path)
                folder_path = os.path.dirname(path)
                mtime = os.path.getmtime(path)
                
                # --- B. OCR 處理 (含座標) ---
                # ocr_result 結構: [ [ [[x1,y1]..], (text, conf) ], ... ]
                ocr_result = ocr_engine.ocr(path, cls=True)
                
                detected_text_list = []
                json_data_list = []
                
                if ocr_result and ocr_result[0]:
                    for line in ocr_result[0]:
                        coords = line[0]        # 座標 [[x,y], [x,y], [x,y], [x,y]]
                        text = line[1][0]       # 文字內容
                        conf = float(line[1][1]) # 置信度 (轉為 python float 以便存 JSON)
                        
                        detected_text_list.append(text)
                        
                        # 儲存結構化資料
                        json_data_list.append({
                            "box": coords,
                            "text": text,
                            "conf": round(conf, 4)
                        })
                
                full_ocr_text = " ".join(detected_text_list)
                ocr_json_str = json.dumps(json_data_list, ensure_ascii=False)
                
                # --- C. 暫存準備計算向量 ---
                batch_images.append(processed_img)
                
                # 準備寫入資料庫的資料 (Embedding 稍後補上)
                db_data.append({
                    "path": path,
                    "filename": filename,
                    "folder": folder_path,
                    "mtime": mtime,
                    "ocr_text": full_ocr_text,
                    "ocr_data": ocr_json_str
                })
                
            except Exception as e:
                print(f"⚠️ 跳過損壞圖片 {path}: {e}")
                continue
        
        if not batch_images:
            continue

        # --- D. 計算向量 (CLIP) ---
        with torch.no_grad(), torch.cuda.amp.autocast():
            image_input = torch.cat(batch_images).to(device)
            image_features = model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            image_features = image_features.cpu().numpy()

        # --- E. 組合與寫入 ---
        final_insert_data = []
        for idx, item in enumerate(db_data):
            emb_blob = image_features[idx].astype(np.float32).tobytes()
            final_insert_data.append((
                item["path"],
                item["filename"],
                item["folder"],
                item["mtime"],
                emb_blob,
                item["ocr_text"],
                item["ocr_data"]
            ))
            
        try:
            cursor.executemany('''
                INSERT INTO images (file_path, filename, folder_path, mtime, embedding, ocr_text, ocr_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', final_insert_data)
            conn.commit()
        except sqlite3.IntegrityError:
            pass # 忽略重複路徑錯誤

    conn.close()
    print(f"\n✅ 索引同步完成！")

if __name__ == "__main__":
    main()
import os
import sqlite3
import torch
from PIL import Image
import open_clip
from tqdm import tqdm
import numpy as np
import logging
import json
import datetime

# 引入 PaddleOCR
from paddleocr import PaddleOCR

# --- 設定區 ---
SOURCE_FOLDERS = [
    r"D:\software\Gemini\rag-image\data",
    # r"E:\Photos\2024",
]

DB_PATH = "images.db"

# 模型設定
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'
# ----------------

# 抑制 Log
logging.getLogger("ppocr").setLevel(logging.ERROR)

def init_db(db_path):
    """初始化資料庫"""
    conn = sqlite3.connect(db_path)
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

def scan_disk_files(folders):
    """掃描多個來源資料夾"""
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    disk_paths = set()
    
    print(f"🔍 開始掃描 {len(folders)} 個來源路徑...")
    for folder in folders:
        if not os.path.exists(folder):
            print(f"⚠️ 路徑不存在，跳過: {folder}")
            continue   
        print(f"   📂 正在掃描: {folder} ...")
        for root, _, files in os.walk(folder):
            for file in files:
                if os.path.splitext(file)[1].lower() in valid_extensions:
                    full_path = os.path.abspath(os.path.join(root, file))
                    disk_paths.add(full_path)
    return disk_paths

def clean_deleted_files(conn, disk_paths):
    """同步刪除與找出新增檔案"""
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM images")
    db_paths = set(row[0] for row in cursor.fetchall())
    
    # 1. 處理刪除
    to_delete = db_paths - disk_paths
    if to_delete:
        print(f"🗑️ 發現 {len(to_delete)} 個過期檔案，正在清理資料庫...")
        to_delete_list = list(to_delete)
        BATCH = 900
        for i in range(0, len(to_delete_list), BATCH):
            batch = to_delete_list[i:i+BATCH]
            placeholders = ','.join(['?'] * len(batch))
            cursor.execute(f"DELETE FROM images WHERE file_path IN ({placeholders})", batch)
        conn.commit()
    
    # 2. 找出新增
    to_add = disk_paths - db_paths
    return list(to_add)

def load_ai_models(device):
    """載入模型"""
    print(f"📥 正在載入 OpenCLIP & PaddleOCR (Device: {device})...")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=PRETRAINED, device=device
        )
        model.eval()
        ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
        return model, preprocess, ocr_engine
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        return None, None, None

def update_folder_stats(conn):
    """更新統計表"""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM folder_stats")
    cursor.execute("""
        INSERT INTO folder_stats (folder_path, image_count, last_updated)
        SELECT folder_path, COUNT(*), datetime('now', 'localtime')
        FROM images GROUP BY folder_path
    """)
    conn.commit()
    
    print("\n" + "="*50)
    print("📊 資料庫統計報告")
    print("="*50)
    cursor.execute("SELECT * FROM folder_stats ORDER BY folder_path")
    rows = cursor.fetchall()
    total = 0
    if not rows:
        print("   (無資料)")
    else:
        for row in rows:
            print(f"{row[1]:<6} | {row[2]:<20} | {row[0]}")
            total += row[1]
        print("-" * 60)
        print(f"總計: {total} 張圖片")
    print("="*50 + "\n")

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動多來源索引引擎 (Device: {device.upper()})")

    conn = init_db(DB_PATH)
    
    disk_paths_set = scan_disk_files(SOURCE_FOLDERS)
    files_to_process = clean_deleted_files(conn, disk_paths_set)

    if not files_to_process:
        print("✨ 資料庫已是最新狀態，跳過模型載入。")
    else:
        print(f"🆕 發現 {len(files_to_process)} 張新圖片，準備開始索引...")
        
        model, preprocess, ocr_engine = load_ai_models(device)
        
        if model and ocr_engine:
            BATCH_SIZE = 4
            cursor = conn.cursor()
            
            for i in tqdm(range(0, len(files_to_process), BATCH_SIZE), desc="Indexing"):
                batch_paths = files_to_process[i : i + BATCH_SIZE]
                batch_images = []
                db_data = []
                
                for path in batch_paths:
                    try:
                        # 1. 圖片預處理
                        img = Image.open(path).convert('RGB')
                        processed_img = preprocess(img).unsqueeze(0)
                        
                        # 2. OCR 處理
                        ocr_result = ocr_engine.ocr(path, cls=True)
                        detected_text_list = []
                        json_data_list = []
                        
                        if ocr_result and ocr_result[0]:
                            for line in ocr_result[0]:
                                # line 格式: [ [[x1,y1],[x2,y2]...], [text, conf] ]
                                box = line[0]
                                text = line[1][0]
                                conf = line[1][1]
                                
                                # [重要修復] 強制轉型為標準 Python int，避免 JSON 報錯
                                clean_box = [[int(pt[0]), int(pt[1])] for pt in box]
                                
                                detected_text_list.append(text)
                                json_data_list.append({
                                    "box": clean_box,
                                    "text": text,
                                    "conf": round(float(conf), 4)
                                })
                        
                        # Debug: 如果有找到字，印出數量 (測試用)
                        if detected_text_list:
                            tqdm.write(f"   [OCR] {os.path.basename(path)} -> 找到 {len(detected_text_list)} 行文字")

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
                        # [重要修復] 印出具體錯誤，而不是跳過
                        print(f"\n❌ 處理失敗 {os.path.basename(path)}: {e}")
                        continue
                
                if not batch_images: continue

                # CLIP
                with torch.no_grad(), torch.amp.autocast('cuda'):#with torch.no_grad(), torch.cuda.amp.autocast():
                    image_input = torch.cat(batch_images).to(device)
                    image_features = model.encode_image(image_input)
                    image_features /= image_features.norm(dim=-1, keepdim=True)
                    image_features = image_features.cpu().numpy()

                # Insert
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
                except sqlite3.IntegrityError: pass
            
            print("✅ 索引同步完成！")

    update_folder_stats(conn)
    conn.close()

if __name__ == "__main__":
    main()
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
    
    # 自動遷移檢查
    existing_columns = set()
    try:
        cursor.execute("PRAGMA table_info(images)")
        for col in cursor.fetchall():
            existing_columns.add(col[1])
    except: pass

    if 'ocr_text' not in existing_columns:
        cursor.execute("ALTER TABLE images ADD COLUMN ocr_text TEXT")
    if 'ocr_data' not in existing_columns:
        cursor.execute("ALTER TABLE images ADD COLUMN ocr_data TEXT")

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON images (filename)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_folder_path ON images (folder_path)')
    
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
    
    # 1. 處理刪除 (資料庫有，硬碟沒有)
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
    
    # 2. 找出新增 (硬碟有，資料庫沒有)
    to_add = disk_paths - db_paths
    return list(to_add)

def load_ai_models(device):
    """
    獨立的模型載入函式
    只有在真的需要處理圖片時才會被呼叫
    """
    print(f"📥 正在載入 OpenCLIP & PaddleOCR (Device: {device})...")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, pretrained=PRETRAINED, device=device
        )
        model.eval()
        # use_angle_cls=False 速度較快
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
    
    # 顯示
    print("\n" + "="*50)
    print("📊 資料庫統計報告")
    print("="*50)
    cursor.execute("SELECT * FROM folder_stats ORDER BY folder_path")
    rows = cursor.fetchall()
    total = 0
    if not rows:
        print("   (無資料)")
    else:
        print(f"{'數量':<6} | {'更新時間':<20} | {'資料夾路徑'}")
        print("-" * 60)
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
    
    # --- 步驟 1: 先掃描硬碟與比對資料庫 (輕量級操作) ---
    disk_paths_set = scan_disk_files(SOURCE_FOLDERS)
    
    # 這一步會直接執行刪除操作，並回傳需要新增的檔案列表
    files_to_process = clean_deleted_files(conn, disk_paths_set)

    # --- 步驟 2: 判斷是否需要載入模型 ---
    if not files_to_process:
        print("✨ 資料庫已是最新狀態，跳過模型載入。")
    else:
        print(f"🆕 發現 {len(files_to_process)} 張新圖片，準備開始索引...")
        
        # --- 步驟 3: 只有這裡才載入模型 (重量級操作) ---
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
                        img = Image.open(path).convert('RGB')
                        processed_img = preprocess(img).unsqueeze(0)
                        
                        # OCR
                        ocr_result = ocr_engine.ocr(path, cls=True)
                        detected_text_list = []
                        json_data_list = []
                        if ocr_result and ocr_result[0]:
                            for line in ocr_result[0]:
                                detected_text_list.append(line[1][0])
                                json_data_list.append({
                                    "box": line[0],
                                    "text": line[1][0],
                                    "conf": round(float(line[1][1]), 4)
                                })
                        
                        batch_images.append(processed_img)
                        db_data.append({
                            "path": path,
                            "filename": os.path.basename(path),
                            "folder": os.path.dirname(path),
                            "mtime": os.path.getmtime(path),
                            "ocr_text": " ".join(detected_text_list),
                            "ocr_data": json.dumps(json_data_list, ensure_ascii=False)
                        })
                    except Exception:
                        continue
                
                if not batch_images: continue

                # CLIP
                with torch.no_grad(), torch.cuda.amp.autocast():
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

    # --- 步驟 4: 無論是否有更新，都重新統計並顯示結果 ---
    update_folder_stats(conn)
    conn.close()

if __name__ == "__main__":
    main()
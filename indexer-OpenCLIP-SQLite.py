import os
import sqlite3
import torch
from PIL import Image
import open_clip
from tqdm import tqdm
import numpy as np

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data"
DB_PATH = "images.db"  # 資料庫檔案名稱

# 模型設定: Multilingual H-14
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'
# ----------------

def init_db(db_path):
    """初始化資料庫與資料表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 建立資料表 (如果不存在)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE,
        filename TEXT,
        folder_path TEXT,
        mtime REAL,
        embedding BLOB
    )
    ''')
    
    # 建立索引以加速查詢 (可選)
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON images (filename)')
    
    conn.commit()
    return conn

def get_existing_paths(conn):
    """取得資料庫中已存在的檔案路徑"""
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM images")
    # 將查詢結果轉為 set，方便快速比對 (O(1) 複雜度)
    return set(row[0] for row in cursor.fetchall())

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()})")

    # 1. 資料庫初始化
    print(f"🗄️  連接資料庫: {DB_PATH}...")
    conn = init_db(DB_PATH)
    
    # 2. 載入模型
    print(f"📥 正在載入 OpenCLIP 模型: {MODEL_NAME}...")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, 
            pretrained=PRETRAINED, 
            device=device
        )
        tokenizer = open_clip.get_tokenizer(MODEL_NAME)
        model.eval()
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        conn.close()
        return

    # 3. 增量更新檢查
    print("🔍 檢查資料庫現有記錄...")
    indexed_set = get_existing_paths(conn)
    print(f"📊 目前資料庫已有 {len(indexed_set)} 張圖片。")

    # 4. 掃描檔案
    print(f"📂 正在掃描資料夾: {IMAGE_FOLDER}")
    files_to_process = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    
    for root, _, files in os.walk(IMAGE_FOLDER):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                full_path = os.path.abspath(os.path.join(root, file))
                
                # 若路徑不在資料庫中，則加入待處理清單
                if full_path not in indexed_set:
                    files_to_process.append(full_path)

    if not files_to_process:
        print("✨ 資料夾中沒有新圖片，索引已是最新狀態。")
        conn.close()
        return

    print(f"🆕 發現 {len(files_to_process)} 張新圖片，開始編碼...")

    # 5. 批次處理與寫入
    BATCH_SIZE = 32
    cursor = conn.cursor()
    
    # 使用 tqdm 顯示進度
    for i in tqdm(range(0, len(files_to_process), BATCH_SIZE), desc="Processing & Saving"):
        batch_paths = files_to_process[i : i + BATCH_SIZE]
        
        batch_images = []
        metadata_list = [] # 暫存要寫入資料庫的 meta data
        
        for path in batch_paths:
            try:
                # 讀取圖片與 Metadata
                img = Image.open(path).convert('RGB')
                processed_img = preprocess(img).unsqueeze(0)
                
                filename = os.path.basename(path)
                folder_path = os.path.dirname(path)
                mtime = os.path.getmtime(path)
                
                batch_images.append(processed_img)
                metadata_list.append({
                    'path': path,
                    'filename': filename,
                    'folder': folder_path,
                    'mtime': mtime
                })
            except Exception as e:
                print(f"\n⚠️ 無法讀取圖片 {path}: {e}")
                continue
        
        if not batch_images:
            continue
            
        # 推論 (Inference)
        with torch.no_grad(), torch.cuda.amp.autocast():
            image_input = torch.cat(batch_images).to(device)
            image_features = model.encode_image(image_input)
            
            # 正規化 (L2 Norm)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            
            # 轉回 CPU 並轉為 numpy
            image_features = image_features.cpu().numpy()

        # 準備寫入資料庫的資料 (List of Tuples)
        db_data = []
        for idx, meta in enumerate(metadata_list):
            # 將 numpy array 轉為 bytes (Blob)
            emb_blob = image_features[idx].astype(np.float32).tobytes()
            
            db_data.append((
                meta['path'],
                meta['filename'],
                meta['folder'],
                meta['mtime'],
                emb_blob
            ))
        
        # 批次寫入 SQLite
        try:
            cursor.executemany('''
                INSERT INTO images (file_path, filename, folder_path, mtime, embedding)
                VALUES (?, ?, ?, ?, ?)
            ''', db_data)
            conn.commit()  # 每個 Batch 提交一次，確保中斷後資料不遺失
        except sqlite3.IntegrityError as e:
            print(f"\n⚠️ 資料庫寫入錯誤 (可能是重複路徑): {e}")

    conn.close()
    print(f"\n✅ 索引更新完成！新增了 {len(files_to_process)} 張圖片。")

if __name__ == "__main__":
    main()
import os
import sqlite3
import torch
from PIL import Image
import open_clip
from tqdm import tqdm
import numpy as np
import logging

# 引入 PaddleOCR
# 第一次執行會自動下載輕量級模型 (約 20MB)
from paddleocr import PaddleOCR

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data"
DB_PATH = "images.db"  # 資料庫檔案名稱

# 模型設定: Multilingual H-14
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'
# ----------------

# 抑制 PaddleOCR 的繁瑣 Log
logging.getLogger("ppocr").setLevel(logging.ERROR)

def init_db(db_path):
    """初始化資料庫與資料表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 建立資料表 (如果不存在)
    # 新增 ocr_text 欄位用於儲存辨識結果
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT UNIQUE,
        filename TEXT,
        folder_path TEXT,
        mtime REAL,
        embedding BLOB,
        ocr_text TEXT
    )
    ''')
    
    # 檢查是否需要為舊資料庫新增 ocr_text 欄位 (Migration)
    try:
        cursor.execute("SELECT ocr_text FROM images LIMIT 1")
    except sqlite3.OperationalError:
        print("⚠️ 偵測到舊版資料庫，正在新增 'ocr_text' 欄位...")
        try:
            cursor.execute("ALTER TABLE images ADD COLUMN ocr_text TEXT")
            conn.commit()
            print("✅ 欄位新增成功！")
        except Exception as e:
            print(f"❌ 欄位新增失敗: {e}")

    # 建立索引以加速查詢
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON images (filename)')
    
    conn.commit()
    return conn

def get_existing_paths(conn):
    """取得資料庫中已存在的檔案路徑"""
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM images")
    return set(row[0] for row in cursor.fetchall())

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()}) + OCR")

    # 1. 資料庫初始化
    print(f"🗄️  連接資料庫: {DB_PATH}...")
    conn = init_db(DB_PATH)
    
    # 2. 載入 OpenCLIP 模型
    print(f"📥 正在載入 OpenCLIP 模型: {MODEL_NAME}...")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, 
            pretrained=PRETRAINED, 
            device=device
        )
        model.eval()
    except Exception as e:
        print(f"❌ CLIP 模型載入失敗: {e}")
        conn.close()
        return

    # 3. 載入 PaddleOCR 模型
    print(f"👀 正在載入 PaddleOCR 模型 (中英文通用)...")
    try:
        # use_angle_cls=True: 自動修正文字方向 (例如倒著的文字)
        # lang='ch': 支援中英文
        # use_gpu: 如果顯存夠大 (RTX 4080 絕對夠) 建議開啟，速度快很多
        # 移除 use_gpu (它會自動偵測)，並將 use_angle_cls 改為 use_textline_orientation
        ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch')
    except Exception as e:
        print(f"❌ OCR 模型載入失敗: {e}")
        conn.close()
        return

    # 4. 增量更新檢查
    print("🔍 檢查資料庫現有記錄...")
    indexed_set = get_existing_paths(conn)
    print(f"📊 目前資料庫已有 {len(indexed_set)} 張圖片。")

    # 5. 掃描檔案
    print(f"📂 正在掃描資料夾: {IMAGE_FOLDER}")
    files_to_process = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    
    for root, _, files in os.walk(IMAGE_FOLDER):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                full_path = os.path.abspath(os.path.join(root, file))
                if full_path not in indexed_set:
                    files_to_process.append(full_path)

    if not files_to_process:
        print("✨ 資料夾中沒有新圖片，索引已是最新狀態。")
        conn.close()
        return

    print(f"🆕 發現 {len(files_to_process)} 張新圖片，開始處理 (CLIP Embedding + OCR)...")

    # 6. 批次處理與寫入
    # 注意：加入 OCR 後速度會變慢，建議 Batch Size 不要太大，以免 OCR 卡太久
    BATCH_SIZE = 8 
    cursor = conn.cursor()
    
    for i in tqdm(range(0, len(files_to_process), BATCH_SIZE), desc="Processing"):
        batch_paths = files_to_process[i : i + BATCH_SIZE]
        
        batch_images = []
        metadata_list = []
        
        for path in batch_paths:
            try:
                # --- A. 讀取與 CLIP 前處理 ---
                img = Image.open(path).convert('RGB')
                processed_img = preprocess(img).unsqueeze(0)
                
                filename = os.path.basename(path)
                folder_path = os.path.dirname(path)
                mtime = os.path.getmtime(path)
                
                # --- B. 執行 OCR 文字辨識 ---
                # PaddleOCR 支援直接傳入路徑
                ocr_result = ocr_engine.ocr(path, cls=True)
                
                detected_text = ""
                if ocr_result and ocr_result[0]:
                    # ocr_result[0] 是一個 list，包含 [座標, (文字, 信心度)]
                    # 我們只需要把所有抓到的文字串接起來即可
                    texts = [line[1][0] for line in ocr_result[0]]
                    detected_text = " ".join(texts)
                
                # --- C. 收集資料 ---
                batch_images.append(processed_img)
                metadata_list.append({
                    'path': path,
                    'filename': filename,
                    'folder': folder_path,
                    'mtime': mtime,
                    'ocr_text': detected_text  # 存入 OCR 結果
                })
                
            except Exception as e:
                print(f"\n⚠️ 處理失敗 {path}: {e}")
                continue
        
        if not batch_images:
            continue
            
        # --- D. CLIP 推論 (計算向量) ---
        with torch.no_grad(), torch.cuda.amp.autocast():
            image_input = torch.cat(batch_images).to(device)
            image_features = model.encode_image(image_input)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            image_features = image_features.cpu().numpy()

        # --- E. 寫入資料庫 ---
        db_data = []
        for idx, meta in enumerate(metadata_list):
            emb_blob = image_features[idx].astype(np.float32).tobytes()
            
            db_data.append((
                meta['path'],
                meta['filename'],
                meta['folder'],
                meta['mtime'],
                emb_blob,
                meta['ocr_text']  # 寫入文字
            ))
        
        try:
            cursor.executemany('''
                INSERT INTO images (file_path, filename, folder_path, mtime, embedding, ocr_text)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', db_data)
            conn.commit()
        except sqlite3.IntegrityError as e:
            print(f"\n⚠️ 資料庫寫入錯誤: {e}")

    conn.close()
    print(f"\n✅ 索引更新完成！OCR 文字已記錄。")

if __name__ == "__main__":
    main()
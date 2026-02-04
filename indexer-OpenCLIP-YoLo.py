import os
import sqlite3
import torch
from PIL import Image
import open_clip
from tqdm import tqdm
import numpy as np
from ultralytics import YOLO  # 新增: YOLO
from sklearn.cluster import DBSCAN  # 新增: 分群演算法

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data"
DB_PATH = "images.db"
YOLO_MODEL_NAME = 'yolov8m-world.pt'  # 或 'yolov8n.pt'
# 模型設定: Multilingual H-14
MODEL_NAME = 'xlm-roberta-large-ViT-H-14'
PRETRAINED = 'frozen_laion5b_s13b_b90k'

# 設定過濾閾值
OBJECT_AREA_THRESHOLD = 0.1  # 物件面積需佔原圖 10% 以上
# ----------------

def init_db(db_path):
    """初始化資料庫與資料表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. 建立主圖表 (images)
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
    
    # 2. 建立子物件表 (sub_objects) - 新增需求
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sub_objects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_path TEXT,
        label TEXT,
        confidence REAL,
        bbox TEXT,
        embedding BLOB,
        cluster_id INTEGER DEFAULT -1,
        FOREIGN KEY(parent_path) REFERENCES images(file_path)
    )
    ''')

    # 建立索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON images (filename)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_parent ON sub_objects (parent_path)')
    
    conn.commit()
    return conn

def get_existing_paths(conn):
    """取得資料庫中已存在的檔案路徑"""
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM images")
    return set(row[0] for row in cursor.fetchall())

def run_clustering(db_path):
    """
    執行 DBSCAN 分群演算法
    針對 sub_objects 表中的 embedding 進行分群，並更新 cluster_id
    """
    print("\n🧩 開始執行 DBSCAN 物件分群...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 讀取所有物件的 embedding
    cursor.execute("SELECT id, embedding FROM sub_objects")
    rows = cursor.fetchall()
    
    if not rows:
        print("⚠️ 沒有偵測到物件，跳過分群。")
        conn.close()
        return

    ids = []
    embeddings = []
    
    for r in rows:
        obj_id = r[0]
        emb_bytes = r[1]
        # 還原為 numpy array
        emb_np = np.frombuffer(emb_bytes, dtype=np.float32)
        ids.append(obj_id)
        embeddings.append(emb_np)
    
    X = np.array(embeddings)
    print(f"📊 分群資料維度: {X.shape}")

    # 執行 DBSCAN (Cosine Distance)
    # eps: 距離閾值 (cosine distance 0.15~0.2 表示相似度很高)
    # min_samples: 形成核心點所需的最小樣本數
    # eps 改成 0.35 (允許更多視角差異)
    # min_samples 改成 2 (只要有 2 個像的就成群，適合小資料)
    clustering = DBSCAN(eps=0.35, min_samples=2, metric='cosine', n_jobs=-1)
    labels = clustering.fit_predict(X)
    
    # 計算分群數量 (忽略 -1 雜訊點)
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"✨ 分群完成: 發現 {n_clusters} 個群組 (雜訊點: {list(labels).count(-1)})")

    # 更新資料庫
    update_data = []
    for obj_id, cluster_label in zip(ids, labels):
        # numpy int64 轉為 python int
        update_data.append((int(cluster_label), obj_id))
    
    cursor.executemany("UPDATE sub_objects SET cluster_id = ? WHERE id = ?", update_data)
    conn.commit()
    conn.close()
    print("✅ 資料庫 cluster_id 更新完畢。")

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動進階索引引擎 (Device: {device.upper()})")

    # 1. 初始化資料庫
    print(f"🗄️  連接資料庫: {DB_PATH}...")
    conn = init_db(DB_PATH)
    
    # 2. 載入 CLIP 模型
    print(f"📥 正在載入 OpenCLIP 模型: {MODEL_NAME}...")
    try:
        clip_model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, 
            pretrained=PRETRAINED, 
            device=device
        )
        clip_model.eval()
    except Exception as e:
        print(f"❌ CLIP 模型載入失敗: {e}")
        conn.close()
        return

    # 3. 載入 YOLO 模型
    print(f"📥 正在載入 YOLO 模型: {YOLO_MODEL_NAME}...")
    try:
        yolo_model = YOLO(YOLO_MODEL_NAME)
        # 預熱模型 (可選)
    except Exception as e:
        print(f"❌ YOLO 模型載入失敗: {e}")
        conn.close()
        return

    # 4. 掃描與增量檢查
    print("🔍 檢查資料庫現有記錄...")
    indexed_set = get_existing_paths(conn)
    print(f"📊 目前資料庫已有 {len(indexed_set)} 張圖片。")

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
        print("✨ 資料夾中沒有新圖片，準備執行分群檢查...")
        conn.close()
        run_clustering(DB_PATH) # 即使沒新圖也可重跑分群
        return

    print(f"🆕 發現 {len(files_to_process)} 張新圖片，開始處理 (YOLO + CLIP)...")

    # 5. 批次處理
    # 注意：這裡的 Batch Size 是指「讀取檔案」的數量。
    # 因為每張圖可能產生多個物件，實際送入 CLIP 的 Batch 會變大。
    FILE_BATCH_SIZE = 8 
    cursor = conn.cursor()
    
    for i in tqdm(range(0, len(files_to_process), FILE_BATCH_SIZE), desc="Processing"):
        batch_paths = files_to_process[i : i + FILE_BATCH_SIZE]
        
        # 收集此批次所有要進 CLIP 的圖片 (原圖 + 切割圖)
        clip_input_tensors = []
        
        # 記錄對應的資料庫寫入資訊
        # 結構: {'type': 'image'|'sub', 'data': (...params)}
        db_tasks = [] 
        
        for path in batch_paths:
            try:
                # 讀取圖片
                original_pil = Image.open(path).convert('RGB')
                width, height = original_pil.size
                image_area = width * height
                
                # --- A. 處理原圖 (Main Image) ---
                processed_main = preprocess(original_pil).unsqueeze(0)
                clip_input_tensors.append(processed_main)
                
                # 準備寫入 images 表的資料
                filename = os.path.basename(path)
                folder_path = os.path.dirname(path)
                mtime = os.path.getmtime(path)
                
                db_tasks.append({
                    'type': 'image',
                    'data': {
                        'file_path': path,
                        'filename': filename,
                        'folder_path': folder_path,
                        'mtime': mtime
                    }
                })

                # --- B. 執行 YOLO 物件偵測 ---
                # verbose=False 關閉詳細輸出
                results = yolo_model.predict(original_pil, device=device, verbose=False, conf=0.25)
                
                for r in results:
                    boxes = r.boxes
                    for box in boxes:
                        # 取得座標 (x1, y1, x2, y2)
                        coords = box.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = map(int, coords)
                        
                        # 計算物件面積
                        obj_w = x2 - x1
                        obj_h = y2 - y1
                        obj_area = obj_w * obj_h
                        
                        # 關鍵過濾: 面積佔比 > 10%
                        if (obj_area / image_area) > OBJECT_AREA_THRESHOLD:
                            # 取得其他資訊
                            cls_id = int(box.cls[0])
                            label_name = yolo_model.names[cls_id]
                            conf = float(box.conf[0])
                            
                            # 切割圖片 (Crop)
                            crop_img = original_pil.crop((x1, y1, x2, y2))
                            
                            # Preprocess Crop
                            processed_crop = preprocess(crop_img).unsqueeze(0)
                            clip_input_tensors.append(processed_crop)
                            
                            # 準備寫入 sub_objects 表的資料
                            bbox_str = f"{x1},{y1},{x2},{y2}"
                            db_tasks.append({
                                'type': 'sub_object',
                                'data': {
                                    'parent_path': path,
                                    'label': label_name,
                                    'confidence': conf,
                                    'bbox': bbox_str
                                }
                            })

            except Exception as e:
                print(f"\n⚠️ 處理圖片失敗 {path}: {e}")
                continue
        
        if not clip_input_tensors:
            continue

        # --- C. CLIP 統一編碼 (Inference) ---
        with torch.no_grad(), torch.cuda.amp.autocast():
            # 將所有 tensor (原圖 + 物件) 串接
            image_batch = torch.cat(clip_input_tensors).to(device)
            
            # 計算特徵
            features = clip_model.encode_image(image_batch)
            features /= features.norm(dim=-1, keepdim=True) # L2 Norm
            features = features.cpu().numpy()

        # --- D. 寫入資料庫 ---
        # features 的順序與 db_tasks 的順序是一致的
        
        images_insert_list = []
        subs_insert_list = []
        
        for idx, task in enumerate(db_tasks):
            emb_blob = features[idx].astype(np.float32).tobytes()
            meta = task['data']
            
            if task['type'] == 'image':
                images_insert_list.append((
                    meta['file_path'],
                    meta['filename'],
                    meta['folder_path'],
                    meta['mtime'],
                    emb_blob
                ))
            elif task['type'] == 'sub_object':
                subs_insert_list.append((
                    meta['parent_path'],
                    meta['label'],
                    meta['confidence'],
                    meta['bbox'],
                    emb_blob
                ))
        
        try:
            # 寫入 images
            if images_insert_list:
                cursor.executemany('''
                    INSERT INTO images (file_path, filename, folder_path, mtime, embedding)
                    VALUES (?, ?, ?, ?, ?)
                ''', images_insert_list)
            
            # 寫入 sub_objects
            if subs_insert_list:
                cursor.executemany('''
                    INSERT INTO sub_objects (parent_path, label, confidence, bbox, embedding)
                    VALUES (?, ?, ?, ?, ?)
                ''', subs_insert_list)
                
            conn.commit()
        except sqlite3.IntegrityError as e:
            print(f"\n⚠️ 資料庫寫入重複: {e}")

    conn.close()
    print(f"\n✅ 索引更新完成！")
    
    # 6. 執行分群
    run_clustering(DB_PATH)

if __name__ == "__main__":
    main()
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

class IndexerService:
    def __init__(self, db_path, model_name='xlm-roberta-large-ViT-H-14', pretrained_name='frozen_laion5b_s13b_b90k'):
        """
        初始化索引服務
        :param db_path: 資料庫檔案的絕對路徑
        :param model_name: OpenCLIP 模型名稱
        :param pretrained_name: 預訓練權重名稱
        """
        self.db_path = db_path
        self.model_name = model_name
        self.pretrained_name = pretrained_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 抑制 PaddleOCR Log
        logging.getLogger("ppocr").setLevel(logging.ERROR)

    def init_db(self):
        """初始化資料庫連線與表格"""
        print(f"[Indexer] 連線至資料庫: {self.db_path}")
        # 確保資料庫目錄存在 (避免因為路徑不存在而報錯)
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

    def scan_disk_files(self, folders):
        """掃描多個來源資料夾"""
        valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        disk_paths = set()
        
        if not folders:
            print("⚠️ 警告: 未設定來源資料夾 (Source Folders)，請檢查設定檔。")
            return disk_paths

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

    def clean_deleted_files(self, conn, disk_paths):
        """同步刪除與找出新增檔案"""
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM images")
        db_paths = set(row[0] for row in cursor.fetchall())
        
        # 1. 處理刪除 (資料庫有，但硬碟沒有)
        to_delete = db_paths - disk_paths
        if to_delete:
            print(f"🗑️ 發現 {len(to_delete)} 個已刪除或移動的檔案，正在清理資料庫...")
            to_delete_list = list(to_delete)
            BATCH = 900
            for i in range(0, len(to_delete_list), BATCH):
                batch = to_delete_list[i:i+BATCH]
                placeholders = ','.join(['?'] * len(batch))
                cursor.execute(f"DELETE FROM images WHERE file_path IN ({placeholders})", batch)
            conn.commit()
        
        # 2. 找出新增 (硬碟有，但資料庫沒有)
        to_add = disk_paths - db_paths
        return list(to_add)

    def load_ai_models(self):
        """載入模型"""
        print(f"📥 正在載入 OpenCLIP & PaddleOCR (Device: {self.device.upper()})...")
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                self.model_name, pretrained=self.pretrained_name, device=self.device
            )
            model.eval()
            ocr_engine = PaddleOCR(use_angle_cls=False, lang='ch', show_log=False)
            return model, preprocess, ocr_engine
        except Exception as e:
            print(f"❌ 模型載入失敗: {e}")
            return None, None, None

    def update_folder_stats(self, conn):
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

    def run_indexing(self, source_folders):
        """
        執行主要索引流程
        :param source_folders: 要掃描的資料夾路徑列表
        """
        print(f"🚀 啟動多來源索引引擎 (Device: {self.device.upper()})")

        conn = self.init_db()
        
        # 如果沒有設定資料夾，就不執行掃描，避免誤刪資料庫
        if not source_folders:
            print("⚠️ 未偵測到來源資料夾，僅更新統計資訊。")
            self.update_folder_stats(conn)
            conn.close()
            return

        disk_paths_set = self.scan_disk_files(source_folders)
        files_to_process = self.clean_deleted_files(conn, disk_paths_set)

        if not files_to_process:
            print("✨ 資料庫已是最新狀態，跳過模型載入。")
        else:
            print(f"🆕 發現 {len(files_to_process)} 張新圖片，準備開始索引...")
            
            model, preprocess, ocr_engine = self.load_ai_models()
            
            if model and ocr_engine:
                BATCH_SIZE = 4
                cursor = conn.cursor()
                
                # 使用 tqdm 顯示進度
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
                            # cls=True 代表開啟方向分類器 (如果圖片文字倒置可以修正)
                            ocr_result = ocr_engine.ocr(path, cls=True)
                            detected_text_list = []
                            json_data_list = []
                            
                            if ocr_result and ocr_result[0]:
                                for line in ocr_result[0]:
                                    # line 格式: [ [[x1,y1],[x2,y2]...], [text, conf] ]
                                    box = line[0]
                                    text = line[1][0]
                                    conf = line[1][1]
                                    
                                    # 強制轉型為標準 Python int，避免 JSON 序列化報錯
                                    clean_box = [[int(pt[0]), int(pt[1])] for pt in box]
                                    
                                    detected_text_list.append(text)
                                    json_data_list.append({
                                        "box": clean_box,
                                        "text": text,
                                        "conf": round(float(conf), 4)
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
                        except Exception as e:
                            print(f"\n❌ 處理失敗 {os.path.basename(path)}: {e}")
                            continue
                    
                    if not batch_images: continue

                    # CLIP 推論
                    # 使用新版 PyTorch 語法，並指定 cuda
                    with torch.no_grad(), torch.amp.autocast('cuda'):
                        image_input = torch.cat(batch_images).to(self.device)
                        image_features = model.encode_image(image_input)
                        image_features /= image_features.norm(dim=-1, keepdim=True)
                        image_features = image_features.cpu().numpy()

                    # 準備寫入資料庫
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
                
                print("✅ 索引同步完成！")

        self.update_folder_stats(conn)
        conn.close()

if __name__ == "__main__":
    # 這裡示範如何與 ConfigManager 整合
    # 假設 config_manager.py 放在同一層目錄
    try:
        from config_manager import ConfigManager
        
        # 1. 初始化 Config
        cfg = ConfigManager()
        
        # 2. 建立 Indexer 服務 (注入設定)
        service = IndexerService(
            db_path=cfg.db_path,
            model_name=cfg.get("model_name"),
            pretrained_name=cfg.get("pretrained")
        )
        
        # 3. 取得要掃描的資料夾
        target_folders = cfg.get("source_folders")
        
        # 如果設定檔是空的，提示使用者
        if not target_folders:
            print(f"⚠️ 設定檔 ({cfg.config_path}) 中沒有 'source_folders'。")
            print("請先在設定檔中加入圖片路徑，例如: \"source_folders\": [\"C:\\\\Photos\"]")
        
        # 4. 執行
        service.run_indexing(target_folders)

    except ImportError:
        print("❌ 找不到 config_manager.py，無法讀取設定。")
        print("請確保已建立 config_manager.py 檔案。")
    except Exception as e:
        print(f"❌ 發生未預期的錯誤: {e}")
        import traceback
        traceback.print_exc()
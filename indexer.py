import os
import pickle
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from tqdm import tqdm

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data" 
INDEX_FILE = "image_embeddings_laion.pkl"
# 使用強大的 LAION-2B 模型
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
BATCH_SIZE = 64
# ----------------

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()})")
    print(f"📥 正在載入模型: {MODEL_NAME}...")

    # 改用原生 Transformers 載入
    try:
        model = CLIPModel.from_pretrained(MODEL_NAME).to(device)
        processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        return

    # 1. 增量更新檢查
    existing_data = {'paths': [], 'embeddings': None}
    if os.path.exists(INDEX_FILE):
        print(f"📂 讀取現有索引: {INDEX_FILE}")
        with open(INDEX_FILE, 'rb') as f:
            existing_data = pickle.load(f)
    
    indexed_set = set(existing_data['paths'])

    # 2. 掃描檔案
    all_files = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    print(f"📂 正在掃描資料夾...")
    
    for root, _, files in os.walk(IMAGE_FOLDER):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                full_path = os.path.join(root, file)
                if full_path not in indexed_set:
                    all_files.append(full_path)

    if not all_files:
        print("✨ 資料夾中沒有新圖片，索引已是最新狀態。")
        return

    print(f"🆕 發現 {len(all_files)} 張新圖片，開始編碼...")

    # 3. 批次處理
    new_paths = []
    new_embeddings = []

    for i in tqdm(range(0, len(all_files), BATCH_SIZE), desc="Encoding"):
        batch_paths = all_files[i : i + BATCH_SIZE]
        batch_images = []
        current_valid_paths = []

        for path in batch_paths:
            try:
                img = Image.open(path).convert('RGB')
                batch_images.append(img)
                current_valid_paths.append(path)
            except:
                continue
        
        if batch_images:
            with torch.no_grad():
                # 使用 processor 處理圖片，然後丟入 model.get_image_features
                inputs = processor(images=batch_images, return_tensors="pt", padding=True).to(device)
                image_features = model.get_image_features(**inputs)
                
                # 正規化向量 (這是 CLIP 計算相似度的關鍵)
                image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
                
                new_embeddings.append(image_features.cpu())
                new_paths.extend(current_valid_paths)

    # 4. 存檔
    if new_embeddings:
        final_paths = existing_data['paths'] + new_paths
        new_embs_tensor = torch.cat(new_embeddings, dim=0)
        
        if existing_data['embeddings'] is not None:
            final_embs = torch.cat([existing_data['embeddings'], new_embs_tensor], dim=0)
        else:
            final_embs = new_embs_tensor

        with open(INDEX_FILE, 'wb') as f:
            pickle.dump({'paths': final_paths, 'embeddings': final_embs}, f)
        
        print(f"\n✅ 索引建立完成！總計: {len(final_paths)} 張")

if __name__ == "__main__":
    main()
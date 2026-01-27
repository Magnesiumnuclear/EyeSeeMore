import os
import pickle
import torch
from PIL import Image, UnidentifiedImageError
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data" # 使用你的 Junction 路徑
INDEX_FILE = "image_embeddings.pkl"
MODEL_NAME = 'clip-ViT-B-32'
BATCH_SIZE = 64 # RTX 4080 建議直接開到 64 以上
# ----------------

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()})")
    
    model = SentenceTransformer(MODEL_NAME, device=device)

    # 1. 載入現有索引 (如果存在)
    existing_data = {'paths': [], 'embeddings': None}
    if os.path.exists(INDEX_FILE):
        print(f"載入現有索引: {INDEX_FILE}")
        with open(INDEX_FILE, 'rb') as f:
            existing_data = pickle.load(f)
    
    indexed_set = set(existing_data['paths'])

    # 2. 掃描資料夾
    all_files = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    for root, _, files in os.walk(IMAGE_FOLDER):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                full_path = os.path.join(root, file)
                if full_path not in indexed_set: # 只加入尚未索引的檔案
                    all_files.append(full_path)

    if not all_files:
        print("✨ 沒有偵測到新圖片，索引已是最新狀態。")
        return

    print(f"🆕 發現 {len(all_files)} 張新圖片，開始掃描...")

    # 3. 批次處理
    new_paths = []
    new_embeddings = []

    for i in tqdm(range(0, len(all_files), BATCH_SIZE), desc="Embedding"):
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
            with torch.no_grad(): # 關閉梯度計算，節省記憶體
                embeddings = model.encode(batch_images, convert_to_tensor=True, show_progress_bar=False)
                new_embeddings.append(embeddings.cpu())
                new_paths.extend(current_valid_paths)

    # 4. 合併新舊數據並儲存
    final_paths = existing_data['paths'] + new_paths
    
    if new_embeddings:
        new_embs_tensor = torch.cat(new_embeddings, dim=0)
        if existing_data['embeddings'] is not None:
            final_embs = torch.cat([existing_data['embeddings'], new_embs_tensor], dim=0)
        else:
            final_embs = new_embs_tensor

        with open(INDEX_FILE, 'wb') as f:
            pickle.dump({'paths': final_paths, 'embeddings': final_embs}, f)
        
        print(f"✅ 索引更新完成！目前總計: {len(final_paths)} 張圖片")

if __name__ == "__main__":
    main()
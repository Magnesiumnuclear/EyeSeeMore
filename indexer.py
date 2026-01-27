import os
import pickle
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
from tqdm import tqdm

# --- 設定區 ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data" 
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
BATCH_SIZE = 64
# ----------------

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()})")
    print(f"📥 正在載入模型: {MODEL_NAME}...")

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
                inputs = processor(images=batch_images, return_tensors="pt", padding=True).to(device)
                
                # --- 🔥 修正重點：手動執行 Vision Model + Projection ---
                # 1. 取得視覺模型的原始輸出
                vision_outputs = model.vision_model(**inputs)
                
                # 2. 提取 pooled_output (通常是 cls token)
                # 注意：這裡就是報錯的地方，我們手動取值，避開 Wrapper
                pooled_output = vision_outputs.pooler_output  # shape: [batch, 768]
                
                # 3. 投影到 CLIP 向量空間 (Project to 512 dim)
                image_features = model.visual_projection(pooled_output) # shape: [batch, 512]

                # 4. 正規化 (Normalization)
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
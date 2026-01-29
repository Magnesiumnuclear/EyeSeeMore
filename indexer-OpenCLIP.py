import os
import pickle
import torch
from PIL import Image
import open_clip  # 🔥 改用 open_clip 庫
from tqdm import tqdm

# --- 設定區 (這裡改用 OpenCLIP 的格式) ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data"

# 🔥 設定 1: 中文/多語言最強版 (H-14)
INDEX_FILE = "idx_H14_multilingual.pkl"
MODEL_NAME = 'ViT-H-14' 
PRETRAINED = 'laion2b_s32b_b79k'  # 若要多語言需用特定權重，下面會自動處理
# ----------------

def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()})")

    # 🔥 載入模型邏輯 (針對 Multilingual H-14 的特殊處理)
    print(f"📥 正在載入 OpenCLIP 模型: {MODEL_NAME}...")
    try:
        # 如果是要跑多語言 H-14，請使用這組設定：
        # model_name='xlm-roberta-large-ViT-H-14', pretrained='frozen_laion5b_s13b_b90k'
        
        # 這裡我幫你寫死成你想要的「多語言 H-14」，讓你直接跑
        model, _, preprocess = open_clip.create_model_and_transforms(
            'xlm-roberta-large-ViT-H-14', 
            pretrained='frozen_laion5b_s13b_b90k', 
            device=device
        )
        tokenizer = open_clip.get_tokenizer('xlm-roberta-large-ViT-H-14')
        
        # 如果你要跑英文版 H-14，請解開下面這行註解，並註解上面那段
        # model, _, preprocess = open_clip.create_model_and_transforms('ViT-H-14', pretrained='laion2b_s32b_b79k', device=device)
        
        model.eval()
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        print("💡 請確認已安裝套件: pip install open_clip_torch")
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
    BATCH_SIZE = 32 # H-14 比較大，建議稍微調小 Batch
    new_paths = []
    new_embeddings = []

    for i in tqdm(range(0, len(all_files), BATCH_SIZE), desc="Encoding"):
        batch_paths = all_files[i : i + BATCH_SIZE]
        batch_images = []
        current_valid_paths = []

        for path in batch_paths:
            try:
                # OpenCLIP 的預處理方式
                img = Image.open(path).convert('RGB')
                processed_img = preprocess(img).unsqueeze(0)
                batch_images.append(processed_img)
                current_valid_paths.append(path)
            except:
                continue
        
        if batch_images:
            with torch.no_grad(), torch.cuda.amp.autocast(): # 啟用 FP16 加速
                image_input = torch.cat(batch_images).to(device)
                image_features = model.encode_image(image_input)
                
                # 正規化
                image_features /= image_features.norm(dim=-1, keepdim=True)
                
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
        
        print(f"\n✅ 索引建立完成！總計: {len(final_paths)} 張 (使用模型: Multilingual H-14)")

if __name__ == "__main__":
    main()
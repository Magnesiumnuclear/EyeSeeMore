import os
import pickle
import torch
from PIL import Image
import open_clip
from tqdm import tqdm

# --- 設定區 (二次元/美感特化版) ---
IMAGE_FOLDER = r"D:\software\Gemini\rag-image\data" 
INDEX_FILE = "idx_anime.pkl"  # 專用的動漫索引檔名

# 使用 ViT-L-14 架構，搭配 LAION-2B 的 Aesthetic (美感) 權重
# 這顆模型看過 20 億張篩選過「美感」的圖片，對畫風、動漫標籤理解極佳
MODEL_NAME = 'ViT-L-14'
PRETRAINED = 'laion2b_s32b_b82k' 

# RTX 4080 跑 L-14 很輕鬆，Batch Size 可以開大一點
BATCH_SIZE = 128 
# ----------------

def main():
    # 1. 設定裝置
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 啟動索引引擎 (Device: {device.upper()})")
    print(f"🎯 模式: 二次元/美感特化 (Anime/Aesthetic)")

    # 2. 載入模型
    print(f"📥 正在載入 OpenCLIP 模型: {MODEL_NAME} ({PRETRAINED})...")
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            MODEL_NAME, 
            pretrained=PRETRAINED, 
            device=device
        )
        # 雖然建立索引不需要 tokenizer，但為了確保完整性習慣性載入
        tokenizer = open_clip.get_tokenizer(MODEL_NAME)
        
        model.eval()
        print("✅ 模型載入成功！")
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        print("💡 請確認已安裝套件: pip install open_clip_torch")
        return

    # 3. 增量更新檢查 (讀取現有索引)
    existing_data = {'paths': [], 'embeddings': None}
    if os.path.exists(INDEX_FILE):
        print(f"📂 讀取現有索引: {INDEX_FILE}")
        with open(INDEX_FILE, 'rb') as f:
            existing_data = pickle.load(f)
    
    indexed_set = set(existing_data['paths'])

    # 4. 掃描檔案
    all_files = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    print(f"📂 正在掃描資料夾: {IMAGE_FOLDER}...")
    
    for root, _, files in os.walk(IMAGE_FOLDER):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                full_path = os.path.join(root, file)
                # 只有當路徑不在索引中，且檔案真的存在時才加入
                if full_path not in indexed_set and os.path.exists(full_path):
                    all_files.append(full_path)

    if not all_files:
        print("✨ 資料夾中沒有新圖片，索引已是最新狀態。")
        return

    print(f"🆕 發現 {len(all_files)} 張新圖片，開始編碼...")

    # 5. 批次處理與編碼
    new_paths = []
    new_embeddings = []

    # 使用 tqdm 顯示進度條
    for i in tqdm(range(0, len(all_files), BATCH_SIZE), desc="Encoding"):
        batch_paths = all_files[i : i + BATCH_SIZE]
        batch_images = []
        current_valid_paths = []

        for path in batch_paths:
            try:
                # OpenCLIP 預處理：讀圖 -> 轉 RGB -> Preprocess
                img = Image.open(path).convert('RGB')
                processed_img = preprocess(img).unsqueeze(0)
                batch_images.append(processed_img)
                current_valid_paths.append(path)
            except Exception as e:
                # 遇到壞圖直接跳過，不中斷程式
                print(f"\n⚠️ 無法讀取圖片: {path} ({e})")
                continue
        
        if batch_images:
            # 使用 FP16 (autocast) 加速運算並節省 VRAM
            with torch.no_grad(), torch.cuda.amp.autocast():
                image_input = torch.cat(batch_images).to(device)
                image_features = model.encode_image(image_input)
                
                # 特徵正規化 (Normalization) - 這對 Cosine Similarity 很重要
                image_features /= image_features.norm(dim=-1, keepdim=True)
                
                new_embeddings.append(image_features.cpu())
                new_paths.extend(current_valid_paths)

    # 6. 合併與存檔
    if new_embeddings:
        print("💾 正在儲存索引檔...")
        final_paths = existing_data['paths'] + new_paths
        new_embs_tensor = torch.cat(new_embeddings, dim=0)
        
        if existing_data['embeddings'] is not None:
            final_embs = torch.cat([existing_data['embeddings'], new_embs_tensor], dim=0)
        else:
            final_embs = new_embs_tensor

        with open(INDEX_FILE, 'wb') as f:
            pickle.dump({'paths': final_paths, 'embeddings': final_embs}, f)
        
        print(f"\n✅ 動漫索引建立完成！")
        print(f"📊 總計圖片: {len(final_paths)} 張")
        print(f"📁 索引檔案: {INDEX_FILE}")

if __name__ == "__main__":
    main()
import os
import pickle
import torch
from PIL import Image, UnidentifiedImageError
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# --- 設定區 ---
IMAGE_FOLDER = r"C:\Your\Image\Directory"  # <--- 請修改為你的圖片資料夾路徑
INDEX_FILE = "image_embeddings.pkl"        # 索引存檔名稱
MODEL_NAME = 'clip-ViT-B-32-multilingual-v1'
BATCH_SIZE = 32  # RTX 4080 VRAM 很大，可以設為 32, 64 甚至 128
# ----------------

def main():
    # 1. 檢查 GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 正在使用裝置: {device.upper()}")
    if device == "cuda":
        print(f"   GPU 型號: {torch.cuda.get_device_name(0)}")

    # 2. 載入模型
    print(f"📥 正在載入 CLIP 模型: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, device=device)

    # 3. 掃描圖片路徑
    print(f"📂 正在掃描資料夾: {IMAGE_FOLDER}")
    image_paths = []
    valid_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}

    for root, dirs, files in os.walk(IMAGE_FOLDER):
        for file in files:
            if os.path.splitext(file)[1].lower() in valid_extensions:
                image_paths.append(os.path.join(root, file))

    print(f"📊 找到 {len(image_paths)} 張圖片，準備建立索引...")

    # 4. 批次處理圖片並計算向量
    all_embeddings = []
    valid_paths = [] # 儲存成功讀取的路徑

    # 使用 tqdm 顯示進度條
    for i in tqdm(range(0, len(image_paths), BATCH_SIZE), desc="Processing"):
        batch_paths = image_paths[i : i + BATCH_SIZE]
        batch_images = []
        current_batch_valid_paths = []

        for path in batch_paths:
            try:
                # 這裡只做開啟與轉換，確保圖片沒壞
                img = Image.open(path).convert('RGB')
                batch_images.append(img)
                current_batch_valid_paths.append(path)
            except (UnidentifiedImageError, OSError):
                # 忽略損壞的圖片
                continue
        
        if batch_images:
            # 使用模型進行編碼 (這是最吃 GPU 的步驟)
            embeddings = model.encode(batch_images, convert_to_tensor=True, show_progress_bar=False)
            # 轉回 CPU 並轉為 numpy 格式以便儲存，節省之後搜尋的 VRAM
            all_embeddings.append(embeddings.cpu())
            valid_paths.extend(current_batch_valid_paths)

    # 5. 合併與存檔
    if all_embeddings:
        final_embeddings = torch.cat(all_embeddings, dim=0)
        
        data = {
            'paths': valid_paths,
            'embeddings': final_embeddings
        }

        with open(INDEX_FILE, 'wb') as f:
            pickle.dump(data, f)

        print(f"\n✅ 索引建立完成！")
        print(f"   - 總共索引: {len(valid_paths)} 張圖片")
        print(f"   - 檔案儲存為: {INDEX_FILE}")
    else:
        print("❌ 未處理任何圖片，請檢查路徑或檔案格式。")

if __name__ == "__main__":
    main()
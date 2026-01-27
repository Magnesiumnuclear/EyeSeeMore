import os
import pickle
import torch
from transformers import CLIPProcessor, CLIPModel

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
TOP_K = 3
# ----------------

def main():
    if not os.path.exists(INDEX_FILE):
        print(f"❌ 找不到索引檔 '{INDEX_FILE}'。請先執行 indexer.py。")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 初始化搜尋引擎 (Device: {device.upper()})...")

    try:
        model = CLIPModel.from_pretrained(MODEL_NAME).to(device)
        processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        return

    print("📥 正在載入索引數據...")
    with open(INDEX_FILE, 'rb') as f:
        data = pickle.load(f)
    
    stored_embeddings = data['embeddings'].to(device)
    stored_paths = data['paths']
    print(f"✅ 系統就緒！資料庫中有 {len(stored_paths)} 張圖片。")
    print("--------------------------------------------------")
    print("👉 提示：輸入英文 Tag 效果最佳 (例: 'anime girl, blue hair')")
    print("👉 中文指令可能較弱，建議用 'sorasaki hina' 等專有名詞")
    print("--------------------------------------------------")

    while True:
        query = input("\n🔍 請輸入搜尋關鍵字: ").strip()
        
        if query.lower() in ['q', 'exit']:
            break
        if not query:
            continue

        # 1. 文字轉向量 (手動執行 Text Model + Projection)
        with torch.no_grad():
            inputs = processor(text=[query], return_tensors="pt", padding=True).to(device)
            
            # --- 🔥 修正重點：手動執行 Text Model ---
            text_outputs = model.text_model(**inputs)
            pooled_output = text_outputs.pooler_output
            text_features = model.text_projection(pooled_output)
            
            # 正規化
            text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

        # 2. 計算相似度
        similarity = (text_features @ stored_embeddings.T).squeeze(0)

        # 3. 找出 Top K
        values, indices = similarity.topk(TOP_K)

        print(f"\n🎯 搜尋結果 Top {TOP_K}:")
        best_path = None
        
        for i in range(TOP_K):
            score = values[i].item()
            idx = indices[i].item()
            path = stored_paths[idx]
            filename = os.path.basename(path)
            
            if i == 0: best_path = path
            
            print(f"   [{i+1}] {score:.4f} | 📂 {filename}")

        if best_path:
            try:
                os.startfile(best_path)
            except:
                pass

if __name__ == "__main__":
    main()
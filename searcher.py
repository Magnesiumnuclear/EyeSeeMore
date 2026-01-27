import os
import pickle
import torch
from transformers import CLIPProcessor, CLIPModel

# --- 設定區 ---
INDEX_FILE = "image_embeddings_laion.pkl"
MODEL_NAME = 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K'
TOP_K = 3  # 這次我們顯示前三名，讓你比較分數
# ----------------

def main():
    if not os.path.exists(INDEX_FILE):
        print(f"❌ 找不到索引檔 '{INDEX_FILE}'。請先執行 indexer.py。")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 初始化搜尋引擎 (Device: {device.upper()})...")

    # 載入模型
    try:
        model = CLIPModel.from_pretrained(MODEL_NAME).to(device)
        processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    except Exception as e:
        print(f"❌ 模型載入失敗: {e}")
        return

    # 載入數據
    print("📥 正在載入索引數據...")
    with open(INDEX_FILE, 'rb') as f:
        data = pickle.load(f)
    
    stored_embeddings = data['embeddings'].to(device)
    stored_paths = data['paths']
    print(f"✅ 系統就緒！資料庫中有 {len(stored_paths)} 張圖片。")
    print("--------------------------------------------------")
    print("👉 提示：此模型對英文 Tag 最敏感 (例如: 'anime girl, blue hair')")
    print("👉 輸入 'q' 離開")
    print("--------------------------------------------------")

    while True:
        query = input("\n🔍 請輸入搜尋關鍵字 (建議英文): ").strip()
        
        if query.lower() in ['q', 'exit']:
            break
        if not query:
            continue

        # 1. 文字轉向量
        with torch.no_grad():
            inputs = processor(text=[query], return_tensors="pt", padding=True).to(device)
            text_features = model.get_text_features(**inputs)
            # 正規化
            text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

        # 2. 計算相似度 (矩陣乘法)
        # 這裡 text_features 形狀是 [1, 512], stored_embeddings 是 [N, 512]
        # 結果會是 [1, N]
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
            
            if i == 0: best_path = path # 記錄第一名
            
            print(f"   [{i+1}] {score:.4f} | 📂 {filename}")

        # 4. 自動開啟第一名
        if best_path:
            try:
                os.startfile(best_path)
            except:
                pass

if __name__ == "__main__":
    main()
import os
import pickle
import torch
from sentence_transformers import SentenceTransformer, util

# --- 設定區 ---
INDEX_FILE = "image_embeddings.pkl"
MODEL_NAME = 'clip-ViT-B-32-multilingual-v1'
TOP_K = 1  # 預設開啟最像的那一張
# ----------------

def main():
    # 1. 檢查環境與索引檔
    if not os.path.exists(INDEX_FILE):
        print(f"❌ 找不到索引檔 '{INDEX_FILE}'。請先執行 indexer.py。")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🚀 初始化搜尋引擎 (Device: {device.upper()})...")

    # 2. 載入模型 (搜尋時模型只需要編碼文字，非常輕量)
    model = SentenceTransformer(MODEL_NAME, device=device)

    # 3. 載入索引數據
    print("📥 正在載入索引數據...")
    with open(INDEX_FILE, 'rb') as f:
        data = pickle.load(f)
    
    stored_embeddings = data['embeddings'].to(device) # 將向量搬到 GPU 加速比對
    stored_paths = data['paths']
    print(f"✅ 系統就緒！資料庫中有 {len(stored_paths)} 張圖片。")
    print("--------------------------------------------------")
    print("👉 請輸入描述 (例如: '紅色的法拉利', '貓在睡覺')")
    print("👉 輸入 'q' 或 'exit' 離開程式")
    print("--------------------------------------------------")

    # 4. 互動迴圈
    while True:
        query = input("\n🔍 請輸入搜尋關鍵字: ").strip()
        
        if query.lower() in ['q', 'exit']:
            print("👋 程式結束。")
            break
            
        if not query:
            continue

        # 文字轉向量
        query_embedding = model.encode(query, convert_to_tensor=True)

        # 計算餘弦相似度 (Cosine Similarity)
        # util.cos_sim 會自動處理 GPU 上的 Tensor 運算
        cos_scores = util.cos_sim(query_embedding, stored_embeddings)[0]

        # 找出分數最高的 TOP_K
        top_results = torch.topk(cos_scores, k=TOP_K)
        
        # 解析結果
        score = top_results.values[0].item()
        idx = top_results.indices[0].item()
        best_image_path = stored_paths[idx]

        print(f"🎯 找到最佳匹配 (相似度: {score:.4f}):")
        print(f"   📂 {os.path.basename(best_image_path)}")
        
        # 5. 自動開啟圖片
        try:
            print("🚀 正在開啟圖片...")
            os.startfile(best_image_path)
        except Exception as e:
            print(f"⚠️ 無法開啟圖片: {e}")

if __name__ == "__main__":
    main()
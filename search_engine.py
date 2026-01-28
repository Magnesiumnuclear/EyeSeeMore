import os
import pickle
import torch
from transformers import CLIPProcessor, CLIPModel

class ImageSearchEngine:
    def __init__(self, 
                 index_file="image_embeddings_laion.pkl", 
                 model_name='laion/CLIP-ViT-B-32-laion2B-s34B-b79K'):
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.index_file = index_file
        self.model_name = model_name
        self.is_ready = False
        
        print(f"🚀 初始化搜尋引擎 (Device: {self.device.upper()})...")
        self._load_model()
        self._load_index()

    def _load_model(self):
        try:
            # 載入模型與處理器
            self.model = CLIPModel.from_pretrained(self.model_name).to(self.device)
            self.processor = CLIPProcessor.from_pretrained(self.model_name)
            # 設定為評估模式
            self.model.eval()
        except Exception as e:
            print(f"❌ 模型載入失敗: {e}")
            raise e

    def _load_index(self):
        if not os.path.exists(self.index_file):
            print(f"❌ 找不到索引檔 '{self.index_file}'")
            self.stored_embeddings = None
            self.stored_paths = []
            return

        try:
            with open(self.index_file, 'rb') as f:
                data = pickle.load(f)
            
            # 將向量搬移到 GPU 以加速運算
            self.stored_embeddings = data['embeddings'].to(self.device)
            self.stored_paths = data['paths']
            self.is_ready = True
            print(f"✅ 索引載入成功！資料庫中有 {len(self.stored_paths)} 張圖片。")
        except Exception as e:
            print(f"❌ 索引讀取失敗: {e}")
            self.is_ready = False

    def search(self, query_text, top_k=5):
        """
        輸入文字，回傳最相似的圖片列表。
        回傳格式: [ {'rank': 1, 'score': 0.35, 'path': '...', 'filename': '...'}, ... ]
        """
        if not self.is_ready or not query_text:
            return []

        # 1. 文字轉向量 (手動提取特徵，避開版本相容性問題)
        with torch.no_grad():
            inputs = self.processor(text=[query_text], return_tensors="pt", padding=True).to(self.device)
            
            # 手動執行 Text Model + Projection
            text_outputs = self.model.text_model(**inputs)
            pooled_output = text_outputs.pooler_output
            text_features = self.model.text_projection(pooled_output)
            
            # 正規化
            text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)

        # 2. 計算相似度 (矩陣乘法)
        # text_features: [1, 512] @ stored_embeddings.T: [512, N] -> [1, N]
        similarity = (text_features @ self.stored_embeddings.T).squeeze(0)

        # 3. 找出 Top K (確保不超過總圖片數)
        k = min(top_k, len(self.stored_paths))
        values, indices = similarity.topk(k)

        # 4. 格式化輸出結果
        results = []
        for i in range(k):
            idx = indices[i].item()
            path = self.stored_paths[idx]
            score = values[i].item()
            
            results.append({
                "rank": i + 1,
                "score": round(score, 4), # 四雪五入到小數點後四位
                "path": path,
                "filename": os.path.basename(path)
            })
            
        return results
import os
from huggingface_hub import snapshot_download

# 設定儲存根目錄 (指向你的 4TB SSD)
BASE_DIR = r"D:\Models"

models = {
    # 1. 影像生成 (畫質最強) - 需 HF Token
    # "Flux.1-dev": "black-forest-labs/FLUX.1-dev", 
    # 替代方案：Flux.1-schnell (Apache協議，免Token，速度更快)
    "Flux.1-schnell": "black-forest-labs/FLUX.1-schnell",
    
    # 2. 影片生成
    "CogVideoX-5b": "THUDM/CogVideoX-5b",
    
    # 3. 語音轉寫 (影片搜尋用)
    "Whisper-Large-v3-Turbo": "openai/whisper-large-v3-turbo",
    
    # 4. 視覺問答 (VLM)
    "Llama-3.2-11B-Vision": "meta-llama/Llama-3.2-11B-Vision-Instruct",
    
    # 5. 中文 OCR 增強 (Qwen2-VL 也是必備，如果你之前沒載的話)
    "Qwen2.5-7B-Instruct": "Qwen/Qwen2.5-7B-Instruct", # 純文字最強 7B
    
    # 6. 強力 Embedding
    "BGE-M3": "BAAI/bge-m3"
}

print(f"🚀 開始利用 10 倍網速下載模型至 {BASE_DIR} ...")

for name, repo_id in models.items():
    print(f"\n⬇️ 下載中: {name} ({repo_id})")
    try:
        path = snapshot_download(
            repo_id=repo_id, 
            local_dir=os.path.join(BASE_DIR, name),
            max_workers=16, # 網速快就開多一點線程
            resume_download=True
        )
        print(f"✅ 完成: {path}")
    except Exception as e:
        print(f"❌ 失敗 {name}: {e}")

print("\n🎉 下載結束！你的 4TB 硬碟現在更值錢了。")
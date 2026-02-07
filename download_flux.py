import os
from huggingface_hub import snapshot_download

# 👇 在這裡貼上你的 Token (以 hf_ 開頭)
HF_TOKEN = "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" 

# 設定儲存位置
BASE_DIR = r"D:\Models"

models = {
    # 畫質最強 (需去官網點同意)
    "Flux.1-dev": "black-forest-labs/FLUX.1-dev",
    
    # 速度最快 (需去官網點同意)
    "Flux.1-schnell": "black-forest-labs/FLUX.1-schnell",
}

print(f"🚀 開始下載 Flux 模型 (使用 Token 驗證)...")

for name, repo_id in models.items():
    print(f"\n⬇️ 下載中: {name} ({repo_id})")
    try:
        path = snapshot_download(
            repo_id=repo_id, 
            local_dir=os.path.join(BASE_DIR, name),
            max_workers=16,
            resume_download=True,
            token=HF_TOKEN  # 🔑 關鍵：加上這行傳送 Token
        )
        print(f"✅ 完成: {path}")
    except Exception as e:
        print(f"❌ 失敗 {name}: {e}")
        if "401" in str(e):
            print("👉 原因：你可能還沒去 HuggingFace 網頁點擊「同意條款」，或者 Token 貼錯了。")

print("\n🎉 下載結束！")
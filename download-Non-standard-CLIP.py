import os
from huggingface_hub import snapshot_download

# 👇 必填！請填入你的 HuggingFace Token (hf_ 開頭)
HF_TOKEN = "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" 

# 設定儲存位置
BASE_DIR = r"D:\Models\Vision_Specialists"

models = {
    # === 1. [修正] EVA02-CLIP (改用 timm 託管的標準版) ===
    # 這是目前最強的 CLIP 變體之一，高解析度 (336px)
    "EVA02-CLIP-L-14-336": "timm/eva02_large_patch14_clip_336.merged2b_s6b_b61k",

    # === 2. [修正] BAAI BGE Visualized (官方正確倉庫) ===
    # 這是 BAAI 的視覺嵌入模型，支援多模態檢索
    "bge-visualized": "BAAI/bge-visualized",

    # === 3. [新增] Nomic Embed Vision (動態解析度) ===
    # 這款模型很特別，可以吃不同長寬比的圖，不會強制壓縮
    "nomic-embed-vision-v1.5": "nomic-ai/nomic-embed-vision-v1.5",

    # === 4. [強烈推薦] Chinese-CLIP (中文特化) ===
    # 如果你的搜尋關鍵字很多是中文，這個模型比 OpenAI 原版準非常多
    "chinese-clip-vit-huge": "OFA-Sys/chinese-clip-vit-huge-patch14",
}

print(f"🚀 開始下載修正後的模型清單 (使用 Token: {HF_TOKEN[:5]}***)...")

for name, repo_id in models.items():
    print(f"\n⬇️ 下載中: {name} ({repo_id})")
    try:
        path = snapshot_download(
            repo_id=repo_id, 
            local_dir=os.path.join(BASE_DIR, name),
            max_workers=16,
            resume_download=True,
            token=HF_TOKEN,  # 強制帶上身分證
            # 過濾掉不需要的訓練檔，只抓權重
            ignore_patterns=["*.msgpack", "*.h5", "*.OTF", "*.ttf", "*.onnx", "optimizer.pt"] 
        )
        print(f"✅ 完成: {path}")
    except Exception as e:
        print(f"❌ 失敗 {name}: {e}")
        if "404" in str(e):
            print("👉 如果還是 404，可能是網路快取問題，請稍後再試。但在 timm 下載應該是穩的。")

print("\n🎉 視覺軍火庫補完計畫完成！回家路上小心！")
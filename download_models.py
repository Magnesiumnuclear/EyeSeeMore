import open_clip
import os
from tqdm import tqdm

# 定義你想囤積的模型清單
models_to_download = [
    # 1. 你目前用的 (確認有快取)
    ('xlm-roberta-large-ViT-H-14', 'frozen_laion5b_s13b_b90k'),
    
    # 2. OpenAI 經典款 (相容性最好)
    ('ViT-L-14', 'openai'),
    
    # 3. 極速輕量版 (給爛電腦用)
    ('ViT-B-32', 'laion2b_s34b_b79k'),
    
    # 4. Google SigLIP (新技術)
    ('ViT-SO400M-14-SigLIP', 'webli'),
    
    # 5. 英文特化版 (有時候搜英文代碼比 Multilingual 準)
    ('ViT-H-14', 'laion2b_s32b_b79k'),
]

print(f"🚀 開始下載 {len(models_to_download)} 個大型模型... 請確保網路暢通")

for model_name, pretrained in models_to_download:
    print(f"\n⬇️ Downloading: {model_name} ({pretrained}) ...")
    try:
        # create_model 會自動觸發下載並存到 cache
        model = open_clip.create_model(model_name, pretrained=pretrained)
        print(f"✅ {model_name} 下載完成！")
        del model # 釋放記憶體，避免爆掉
    except Exception as e:
        print(f"❌ 下載失敗 {model_name}: {e}")

print("\n🎉 所有 CLIP 模型已快取完成！")
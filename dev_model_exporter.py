import os
import warnings
import torch
import open_clip

# 忽略 ONNX 轉換時不必要的警告
warnings.filterwarnings("ignore")

# 定義支援轉換的模型清單
MODELS_CONFIG = {
    "1": {"id": "ViT-B-32", "pre": "laion2b_s34b_b79k", "desc": "標準模式"},
    "2": {"id": "ViT-H-14", "pre": "laion2b_s32b_b79k", "desc": "精準模式"},
    "3": {"id": "xlm-roberta-large-ViT-H-14", "pre": "frozen_laion5b_s13b_b90k", "desc": "多語系模式 (支援中文)"}
}

def export_model(model_name, pretrained, save_dir):
    os.makedirs(save_dir, exist_ok=True)
    device = "cpu"
    
    image_onnx_path = os.path.join(save_dir, f"{model_name}_image.onnx")
    text_onnx_path = os.path.join(save_dir, f"{model_name}_text.onnx")
    
    print(f"\n[1/4] 🚀 開始處理模型: {model_name} (Pretrained: {pretrained})")
    print("[2/4] 📥 正在從雲端下載/載入 PyTorch 權重 (這會花費一些時間)...")
    
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=device
        )
        model.eval()

        # --- 處理 Image Encoder ---
        print("[3/4] ⚙️ 正在編譯 Image Encoder 為 ONNX...")
        t_size = getattr(preprocess.transforms[0], 'size', 224)
        img_size = t_size[0] if isinstance(t_size, (list, tuple)) else t_size
        dummy_image = torch.randn(1, 3, img_size, img_size)

        class ImageEncoderWrapper(torch.nn.Module):
            def __init__(self, model):
                super().__init__()
                self.model = model
            def forward(self, image):
                return self.model.encode_image(image)

        image_wrapper = ImageEncoderWrapper(model)
        
        torch.onnx.export(
            image_wrapper, dummy_image, image_onnx_path,
            export_params=True, opset_version=14, do_constant_folding=True,
            input_names=['image'], output_names=['image_features'],
            dynamic_axes={'image': {0: 'batch_size'}, 'image_features': {0: 'batch_size'}}
        )

        # --- 處理 Text Encoder ---
        print("[4/4] 📝 正在編譯 Text Encoder 為 ONNX...")
        is_hf = "roberta" in model_name.lower() or "xlm" in model_name.lower()
        
        if is_hf:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-large')
            # 🌟 關鍵修復：強制將 Dummy Text 填充至 77 個長度，讓 ONNX 記住這個形狀
            dummy_text = tokenizer(
                ["dummy text"], 
                padding="max_length", 
                max_length=77, 
                truncation=True, 
                return_tensors="pt"
            ).input_ids
        else:
            tokenizer = open_clip.get_tokenizer(model_name)
            # open_clip 內建的 tokenize 預設就會輸出 (batch_size, 77) 的形狀
            dummy_text = tokenizer(["dummy text"])

        class TextEncoderWrapper(torch.nn.Module):
            def __init__(self, model):
                super().__init__()
                self.model = model
            def forward(self, text):
                return self.model.encode_text(text)

        text_wrapper = TextEncoderWrapper(model)
        
        torch.onnx.export(
            text_wrapper, dummy_text, text_onnx_path,
            export_params=True, opset_version=14, do_constant_folding=True,
            input_names=['text'], output_names=['text_features'],
            # 注意：text 輸入的 dynamic_axes 只有 batch_size (維度0)，長度(維度1)被鎖定為 77
            dynamic_axes={'text': {0: 'batch_size'}, 'text_features': {0: 'batch_size'}}
        )
        
        print(f"\n✅ 轉換成功！\n影像模型: {image_onnx_path}\n文字模型: {text_onnx_path}\n")
        
    except Exception as e:
        print(f"\n❌ 轉換失敗: {str(e)}\n")

if __name__ == "__main__":
    # 預設儲存在腳本所在目錄的 exported_models 資料夾下
    SAVE_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exported_models")
    
    print("==================================================")
    print("      EyeSeeMore - 開發者專用 ONNX 模型打包工具   ")
    print("==================================================")
    print("請選擇您要下載並轉換的模型：")
    
    for key, config in MODELS_CONFIG.items():
        print(f"[{key}] {config['id']} ({config['desc']})")
    print("[A] 轉換全部模型")
    print("[Q] 退出程式")
    
    choice = input("\n請輸入選項: ").strip().upper()
    
    if choice == 'Q':
        print("已退出。")
    elif choice == 'A':
        for config in MODELS_CONFIG.values():
            export_model(config['id'], config['pre'], SAVE_DIRECTORY)
        print("🎉 所有模型轉換完畢！")
    elif choice in MODELS_CONFIG:
        config = MODELS_CONFIG[choice]
        export_model(config['id'], config['pre'], SAVE_DIRECTORY)
    else:
        print("無效的選項，程式結束。")
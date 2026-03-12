import os
import warnings

# 忽略 ONNX 轉換時不必要的警告
warnings.filterwarnings("ignore")

def export_to_onnx(model_name, pretrained, save_dir, progress_callback=None):
    # [關鍵修復] 延遲載入 torch，避免沒有 PyTorch 的輕量版環境在啟動時崩潰
    try:
        import torch
        import open_clip
    except ImportError:
        if progress_callback: 
            progress_callback(0, "錯誤：此輕量版環境未包含 PyTorch，無法進行模型轉換。")
        return False

    os.makedirs(save_dir, exist_ok=True)
    device = "cpu"
    # ... (下方保持原樣) ...
    device = "cpu"
    
    # 為了避免不同模型切換時覆蓋檔案，檔名加上 model_name 前綴
    image_onnx_path = os.path.join(save_dir, f"{model_name}_image.onnx")
    text_onnx_path = os.path.join(save_dir, f"{model_name}_text.onnx")
    
    # 如果兩個檔案都已經存在，就直接跳過轉換
    if os.path.exists(image_onnx_path) and os.path.exists(text_onnx_path):
        if progress_callback: progress_callback(100, "ONNX 模型已存在，準備切換...")
        return True

    if progress_callback: progress_callback(10, f"下載/載入 {model_name} PyTorch 權重 (需時較長)...")
    
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained, device=device
        )
        model.eval()

        # 1. 動態取得圖片的輸入尺寸 (相容 int 與 tuple 格式)
        t_size = getattr(preprocess.transforms[0], 'size', 224)
        img_size = t_size[0] if isinstance(t_size, (list, tuple)) else t_size
        dummy_image = torch.randn(1, 3, img_size, img_size)
        
        if progress_callback: progress_callback(40, "正在編譯 Image Encoder 為 ONNX (這會花費幾分鐘)...")
        torch.onnx.export(
            model.visual, dummy_image, image_onnx_path,
            export_params=True, opset_version=14, do_constant_folding=True,
            input_names=['image'], output_names=['image_features'],
            dynamic_axes={'image': {0: 'batch_size'}, 'image_features': {0: 'batch_size'}}
        )

        # 2. 文字模型的 Dummy Data (針對 XLM-Roberta 進行特殊處理)
        is_hf = "roberta" in model_name.lower() or "xlm" in model_name.lower()
        if is_hf:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-large')
            # HuggingFace 模型在 open_clip 中的 forward 只吃 input_ids
            dummy_text = tokenizer(["dummy text"], padding=True, truncation=True, return_tensors="pt").input_ids
        else:
            tokenizer = open_clip.get_tokenizer(model_name)
            dummy_text = tokenizer(["dummy text"])

        class TextEncoderWrapper(torch.nn.Module):
            def __init__(self, model):
                super().__init__()
                self.model = model
            def forward(self, text):
                return self.model.encode_text(text)

        text_wrapper = TextEncoderWrapper(model)
        
        if progress_callback: progress_callback(40, "正在編譯 Image Encoder 為 ONNX (這會花費幾分鐘)...")
        
        # [關鍵升級] 透過 Wrapper 強制呼叫 encode_image，確保包含最終的投影層 (Projection Layer)
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
    
    except Exception as e:
        if progress_callback: progress_callback(0, f"轉換失敗: {str(e)}")
        print(f"Export error: {e}")
        return False
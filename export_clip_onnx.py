import torch
import open_clip
import os

def export_to_onnx(model_name, pretrained, save_dir):
    os.makedirs(save_dir, exist_ok=True)
    device = "cpu"  # 匯出 ONNX 時建議使用 CPU
    print(f"Loading {model_name}...")
    
    # 載入原始 PyTorch 模型
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained, device=device
    )
    model.eval()

    # 1. 準備影像輸入 Dummy Data
    # ViT-H-14 預設輸入是 224x224
    dummy_image = torch.randn(1, 3, 224, 224)
    image_onnx_path = os.path.join(save_dir, "clip_image_encoder.onnx")
    
    print("Exporting Image Encoder to ONNX...")
    torch.onnx.export(
        model.visual,                 # 影像編碼器模組
        dummy_image,                  # Dummy 輸入
        image_onnx_path,              # 存檔路徑
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=['image'],        # 設定輸入變數名稱
        output_names=['image_features'], # 設定輸出變數名稱
        dynamic_axes={'image': {0: 'batch_size'}, 'image_features': {0: 'batch_size'}} # 允許動態 Batch Size
    )
    print(f"Image Encoder saved to {image_onnx_path}")

    # 2. 準備文字輸入 Dummy Data (這裡以簡單模型為例，如果是 xlm-roberta 會有差異)
    tokenizer = open_clip.get_tokenizer(model_name)
    dummy_text = tokenizer(["dummy text"])
    text_onnx_path = os.path.join(save_dir, "clip_text_encoder.onnx")

    print("Exporting Text Encoder to ONNX...")
    # 注意：不同模型的 text encoder 實作可能不同，這裡使用 encode_text 的底層結構
    class TextEncoderWrapper(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model
        def forward(self, text):
            return self.model.encode_text(text)

    text_wrapper = TextEncoderWrapper(model)
    torch.onnx.export(
        text_wrapper,
        dummy_text,
        text_onnx_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=['text'],
        output_names=['text_features'],
        dynamic_axes={'text': {0: 'batch_size', 1: 'sequence_length'}, 'text_features': {0: 'batch_size'}}
    )
    print(f"Text Encoder saved to {text_onnx_path}")

if __name__ == "__main__":
    # 以 ViT-B-32 為例進行測試轉換
    export_to_onnx("ViT-B-32", "laion2b_s34b_b79k", "./models/onnx_clip")
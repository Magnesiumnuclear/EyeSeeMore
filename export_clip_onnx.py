import os

def export_to_onnx(model_name, pretrained, save_dir, progress_callback=None):
    """
    [離線版] 廢棄了即時的 PyTorch 下載與轉換功能。
    現在這個函數只負責檢查本地資料夾是否已經放好了對應的 .onnx 模型。
    """
    if progress_callback: 
        progress_callback(10, f"檢查 {model_name} 本地 ONNX 模型...")

    image_onnx_path = os.path.join(save_dir, f"{model_name}_image.onnx")
    text_onnx_path = os.path.join(save_dir, f"{model_name}_text.onnx")
    
    # 檢查兩個檔案是否都已經存在於本地
    if os.path.exists(image_onnx_path) and os.path.exists(text_onnx_path):
        if progress_callback: progress_callback(100, "ONNX 模型已就緒，準備切換...")
        return True
    else:
        if progress_callback: progress_callback(0, "錯誤：找不到本地 ONNX 檔案。")
        print(f"[Error] Missing models. Expected paths:\n{image_onnx_path}\n{text_onnx_path}")
        return False
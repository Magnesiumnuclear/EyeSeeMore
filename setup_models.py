import os
import urllib.request
import tarfile
import subprocess
import shutil

# 設定目錄結構
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models", "ocr")
COMMON_DIR = os.path.join(MODELS_DIR, "common")
CH_DIR = os.path.join(MODELS_DIR, "ch")
TEMP_DIR = os.path.join(BASE_DIR, "temp_paddle_models")

DET_URL = "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_det_infer.tar"
REC_URL = "https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_rec_infer.tar"
DICT_URL = "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/ppocr/utils/ppocr_keys_v1.txt"

def ensure_dirs():
    for d in [COMMON_DIR, CH_DIR, TEMP_DIR]:
        os.makedirs(d, exist_ok=True)

def download_and_extract(url, extract_to):
    filename = url.split("/")[-1]
    filepath = os.path.join(TEMP_DIR, filename)
    if not os.path.exists(filepath):
        print(f"⏳ 正在下載 {filename}...")
        urllib.request.urlretrieve(url, filepath)
    print(f"📦 正在解壓縮 {filename}...")
    with tarfile.open(filepath, "r") as tar:
        tar.extractall(path=extract_to)

def download_dict():
    dict_path = os.path.join(CH_DIR, "dict.txt")
    if not os.path.exists(dict_path):
        print("⏳ 正在下載中文字典檔...")
        urllib.request.urlretrieve(DICT_URL, dict_path)

# [修正] 移除 input_shape_dict，讓工具自動判斷動態維度
def convert_to_onnx(model_dir, save_path):
    print(f"🔄 正在轉換模型至 ONNX: {os.path.basename(save_path)}...")
    cmd = [
        "paddle2onnx",
        "--model_dir", model_dir,
        "--model_filename", "inference.pdmodel",
        "--params_filename", "inference.pdiparams",
        "--save_file", save_path,
        "--opset_version", "11",
        "--enable_onnx_checker", "True"
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"✅ 轉換成功: {save_path}")
    except subprocess.CalledProcessError as e:
        print(f"❌ 轉換失敗！\n錯誤訊息: {e.stderr.decode()}")

if __name__ == "__main__":
    print("🚀 開始準備 ONNX 模型...\n")
    ensure_dirs()
    
    download_and_extract(DET_URL, TEMP_DIR)
    download_and_extract(REC_URL, TEMP_DIR)
    download_dict()

    # 轉換 Det 模型
    det_model_dir = os.path.join(TEMP_DIR, "ch_PP-OCRv4_det_infer")
    det_onnx_path = os.path.join(COMMON_DIR, "det.onnx")
    convert_to_onnx(det_model_dir, det_onnx_path)

    # 轉換 Rec 模型
    rec_model_dir = os.path.join(TEMP_DIR, "ch_PP-OCRv4_rec_infer")
    rec_onnx_path = os.path.join(CH_DIR, "rec.onnx")
    convert_to_onnx(rec_model_dir, rec_onnx_path)

    # 清理暫存
    print("🧹 清理暫存資料夾...")
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    print("\n🎉 模型準備完畢！")
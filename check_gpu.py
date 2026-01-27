import torch
import sys

def check_gpu():
    print("="*40)
    print("🔍 PyTorch GPU (CUDA) 環境檢測工具")
    print("="*40)

    # 1. 檢查 CUDA 是否可用
    is_cuda_available = torch.cuda.is_available()
    print(f"CUDA 是否可用: {'✅ 是 (True)' if is_cuda_available else '❌ 否 (False)'}")

    # 2. 顯示版本資訊
    print(f"Python 版本: {sys.version.split()[0]}")
    print(f"PyTorch 版本: {torch.__version__}")
    
    if is_cuda_available:
        print(f"CUDA 版本: {torch.version.cuda}")
        print(f"cuDNN 版本: {torch.backends.cudnn.version()}")
        
        # 3. 獲取 GPU 硬體資訊
        device_count = torch.cuda.device_count()
        print(f"\n偵測到 {device_count} 個 GPU 裝置:")
        
        for i in range(device_count):
            device_name = torch.cuda.get_device_name(i)
            # 取得 VRAM 大小 (Bytes -> GB)
            total_memory = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
            print(f"  [{i}] 顯示卡型號: {device_name}")
            print(f"  [{i}] VRAM 容量: {total_memory:.2f} GB")

        # 4. 實際運算測試 (Smoke Test)
        print("\n⚡ 正在進行 GPU 運算測試...")
        try:
            # 建立隨機張量並移至 GPU
            x = torch.rand(1000, 1000).cuda()
            y = torch.rand(1000, 1000).cuda()
            
            # 執行矩陣乘法
            z = torch.matmul(x, y)
            
            # 確認結果是否在 GPU 上
            if z.is_cuda:
                print("✅ 測試成功！張量運算已在 GPU 上完成。")
                print("🚀 你的環境已準備好進行 AI 開發。")
            else:
                print("⚠️ 測試警告：運算似乎未在 GPU 上執行。")
                
        except Exception as e:
            print(f"❌ 測試失敗，發生錯誤: {e}")
            
    else:
        print("\n❌ 警告: PyTorch 無法抓取到 GPU。")
        print("💡 可能原因:")
        print("1. 你安裝的是 CPU 版本的 PyTorch。")
        print("2. 顯卡驅動程式未更新。")
        print("3. 請嘗試執行: pip install torch --index-url https://download.pytorch.org/whl/cu118")

    print("="*40)

if __name__ == "__main__":
    check_gpu()
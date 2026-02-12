import torch
import numpy as np
import cv2

class ClipGradCAM:
    """
    針對 OpenCLIP ViT 架構設計的 Grad-CAM 實作。
    [模式] Spotlight (聚光燈)：背景變暗，僅打亮 AI 關注區域。
    """
    def __init__(self, model):
        self.model = model
        self.device = next(model.parameters()).device
        self.gradients = None
        self.activations = None
        
        # 抓取 ln_post (最接近輸出的空間層)
        self.target_layer = self._find_target_layer()
        
        if self.target_layer:
            self.target_layer.register_forward_hook(self.save_activation)
            self.target_layer.register_full_backward_hook(self.save_gradient)
        else:
            print("Error: Could not find target layer in model!")

    def _find_target_layer(self):
        try:
            return self.model.visual.ln_post
        except AttributeError:
            try:
                return self.model.visual.transformer.resblocks[-1]
            except:
                return None

    def save_activation(self, module, input, output):
        self.activations = output.detach()

    def save_gradient(self, module, grad_input, grad_output):
        self.gradients = grad_output[0].detach()

    def generate_heatmap(self, image_tensor, text_ids, original_image_cv2):
        # 1. 準備資料
        image_tensor = image_tensor.to(self.device)
        token_ids = text_ids.to(self.device)
        image_tensor.requires_grad_(True)
        
        try:
            self.model.zero_grad()

            with torch.enable_grad(), torch.amp.autocast('cuda'):
                image_features = self.model.encode_image(image_tensor)
                text_features = self.model.encode_text(token_ids)

                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)

                similarity = (image_features @ text_features.T).sum()
            
            similarity.backward()
                
            if self.gradients is None or self.activations is None:
                return original_image_cv2, None

            # 2. 計算 CAM
            grads = self.gradients[0, 1:, :] 
            acts = self.activations[0, 1:, :]

            weights = grads.mean(dim=0)
            cam = (acts * weights).sum(dim=1)
            
            # 3. Reshape
            seq_len = cam.shape[0]
            grid_size = int(np.sqrt(seq_len)) 
            cam = cam.reshape(grid_size, grid_size)
            
            # 4. 數值處理 & 正規化
            cam = cam.float().cpu().numpy()
            cam = np.maximum(cam, 0) # ReLU
            
            # 放大至原圖尺寸 (使用雙立方插值讓邊緣圓潤)
            h, w = original_image_cv2.shape[:2]
            heatmap = cv2.resize(cam, (w, h), interpolation=cv2.INTER_CUBIC)
            
            # Min-Max 正規化 (拉伸到 0~1)
            # 確保即使分數低，也能顯示相對最亮的區域
            heatmap = (heatmap - heatmap.min()) / (heatmap.max() - heatmap.min() + 1e-8)

            # [視覺優化] 高斯模糊 (讓光暈更自然)
            heatmap = cv2.GaussianBlur(heatmap, (21, 21), 0)
            if heatmap.max() != 0:
                heatmap = heatmap / heatmap.max()

            # ==========================================
            # [核心修改] 聚光燈效果 (Spotlight Effect)
            # ==========================================
            
            # 1. 轉為 3 通道遮罩 (H, W, 3)
            heatmap_3ch = np.stack([heatmap] * 3, axis=2)
            
            # 2. 設定環境光亮度 (0.3 = 30% 亮度，即背景變暗 70%)
            # 你可以調整這個值：0.1 會更暗(更戲劇化)，0.5 會比較亮
            ambient_light = 0.3 
            
            # 3. 計算光照遮罩
            # 邏輯：最亮的地方保持 1.0 (原圖)，最暗的地方降到 0.3
            spotlight_mask = ambient_light + (1 - ambient_light) * heatmap_3ch
            
            # 4. 應用遮罩到原圖
            img_float = original_image_cv2.astype(np.float32)
            result = (img_float * spotlight_mask).astype(np.uint8)
            
            # (選用) 如果你還是想看原始熱力圖，可以在這裡生成，不然回傳 None 也可以
            # 這裡回傳聚光燈圖作為主要結果
            return result, None

        except Exception as e:
            print(f"[GradCAM] Error: {e}")
            import traceback
            traceback.print_exc()
            return original_image_cv2, None
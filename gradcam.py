import torch
import numpy as np
import cv2

class ClipGradCAM:
    def __init__(self, model, target_layer=None):
        self.model = model
        self.gradients = None
        self.activations = None
        
        # 如果沒指定層，預設抓取 ViT 的最後一個 Residual Block
        # 對於 xlm-roberta-large-ViT-H-14，通常是 model.visual.transformer.resblocks[-1]
        if target_layer is None:
            self.target_layer = model.visual.transformer.resblocks[-1]
        else:
            self.target_layer = target_layer

        # 註冊 Hook (攔截數據用)
        self.target_layer.register_forward_hook(self.save_activation)
        self.target_layer.register_full_backward_hook(self.save_gradient)

    def save_activation(self, module, input, output):
        # ViT 的 output 通常是 (Batch, Sequence_Length, Hidden_Dim)
        # 我們需要的是 Sequence (Patch) 的部分
        self.activations = output.detach()

    def save_gradient(self, module, grad_input, grad_output):
        self.gradients = grad_output[0].detach()

    def generate_heatmap(self, image_tensor, text_tensor, original_image_cv2):
        """
        image_tensor: 預處理好的圖片 Tensor (1, 3, 224, 224)
        text_tensor: Tokenize 好的文字 Tensor
        original_image_cv2: 原始圖片 (用 cv2.imread 讀取的 numpy array)，用來最後疊加顯示
        """
        # 1. 清空舊的梯度
        self.model.zero_grad()
        
        # 2. 前向傳播 (Forward)
        # 必須開啟 gradient 追蹤
        with torch.set_grad_enabled(True):
            image_features = self.model.encode_image(image_tensor)
            text_features = self.model.encode_text(text_tensor)

            # 正規化 (Normalize)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            # 3. 計算相似度 (Dot Product)
            # 這就是我們要「解釋」的目標分數
            similarity = (image_features @ text_features.T).squeeze()
            
            # 4. 反向傳播 (Backward)
            # 算出「如何調整圖片特徵才能讓相似度更高？」 -> 這就是梯度
            similarity.backward()

        # 5. 生成 CAM (Class Activation Map)
        # gradients shape: (1, 257, 1280) -> (Batch, Tokens, Dim)
        # tokens 第一個通常是 CLS token (分類用)，後面 256 個是 16x16 的圖片 Patch
        
        # 取出 Patch 部分 (去掉第 0 個 CLS token)
        grads = self.gradients[0, 1:, :] 
        acts = self.activations[0, 1:, :]

        # Global Average Pooling on Gradients (權重)
        weights = grads.mean(dim=0)
        
        # 加權總和
        cam = (acts * weights).sum(dim=1)
        
        # 6. 重塑形狀 (Reshape)
        # ViT-H-14 的輸入是 224x224，Patch size 14，所以 grid 是 16x16 (14*16=224)
        # 具體 grid size 要看模型的 patch size 設定，通常可以用開根號算出來
        seq_len = cam.shape[0]
        grid_size = int(np.sqrt(seq_len)) # 例如 sqrt(256) = 16
        
        cam = cam.reshape(grid_size, grid_size)
        
        # 7. 後處理 (ReLU + Normalize)
        cam = cam.cpu().numpy()
        cam = np.maximum(cam, 0) # ReLU: 只保留正相關 (負相關代表抑制，通常不看)
        
        # 避免除以 0
        if cam.max() != 0:
            cam = cam / cam.max()
        
        # 8. 放大回原圖尺寸並上色
        h, w = original_image_cv2.shape[:2]
        heatmap = cv2.resize(cam, (w, h))
        
        # 轉成熱力圖顏色 (藍色冷 -> 紅色熱)
        heatmap = np.uint8(255 * heatmap)
        heatmap_color = cv2.applyColorMap(heatmap, cv2.COLORMAP_JET)
        
        # 疊加 (原圖 0.6 + 熱力圖 0.4)
        superimposed_img = cv2.addWeighted(original_image_cv2, 0.6, heatmap_color, 0.4, 0)
        
        return superimposed_img, heatmap_color
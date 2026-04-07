import os
import cv2
import numpy as np
import onnxruntime as ort
import pyclipper
from shapely.geometry import Polygon

class ONNXOCR:
    def __init__(self, lang='ch', use_gpu=False):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.det_model_path = os.path.join(self.base_dir, "models", "ocr", "common", "det.onnx")
        self.rec_model_path = os.path.join(self.base_dir, "models", "ocr", lang, "rec.onnx")
        self.dict_path = os.path.join(self.base_dir, "models", "ocr", lang, "dict.txt")
        
        # 1. 設定 ONNX Runtime 的執行者 (Provider)
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider'] if use_gpu else ['CPUExecutionProvider']
        
        # 2. 載入模型
        print(f"[ONNXOCR] 正在載入模型 (GPU: {use_gpu})...")
        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3 # 減少不必要的警告
        
        self.det_session = ort.InferenceSession(self.det_model_path, sess_options=sess_opts, providers=providers)
        self.rec_session = ort.InferenceSession(self.rec_model_path, sess_options=sess_opts, providers=providers)
        
        # 3. 載入字典檔 (CTC 解碼用)
        self.character = self._load_dict(self.dict_path)

    def _load_dict(self, dict_path):
        # PaddleOCR 預設 0 是 blank, 最後一個是空格
        character = ['blank']
        with open(dict_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                line = line.strip("\n")
                character.append(line)
        character.append(' ')
        return character

    def ocr(self, img_input, cls=False):
        """
        模擬 PaddleOCR 的 ocr 介面。
        🌟 [優化] 支援直接輸入 numpy array (BGR 格式)，省去重複的硬碟 IO
        """
        # 判斷輸入是路徑還是已經解碼的圖片矩陣
        if isinstance(img_input, str):
            img = cv2.imdecode(np.fromfile(img_input, dtype=np.uint8), cv2.IMREAD_COLOR)
        elif isinstance(img_input, np.ndarray):
            img = img_input # 直接使用記憶體中的資料
        else:
            return None

        if img is None:
            return [[]]

        # --- 階段 1：文字偵測 (Detection) ---
        dt_boxes = self._det_forward(img)
        if len(dt_boxes) == 0:
            return [[]]

        # 根據由上到下，由左到右排序框
        dt_boxes = self._sort_boxes(dt_boxes)

        # --- 階段 2：文字辨識 (Recognition) ---
        results = []
        for box in dt_boxes:
            # 1. 將傾斜的文字框裁切並轉正
            crop_img = self._get_rotate_crop_image(img, box)
            # 2. 辨識文字
            text, score = self._rec_forward(crop_img)
            
            if score > 0.5 and text.strip(): # 信心度大於 0.5 才納入
                # 輸出格式對齊 PaddleOCR: [[box, (text, score)], ...]
                results.append([box.tolist(), (text, score)])
        
        return [results] if results else [[]]

    # ==========================================
    #  偵測模型 (Detection) 核心邏輯
    # ==========================================
    def _det_forward(self, img):
        # 影像前處理 (Resize, Normalize)
        limit_side_len = 960
        h, w, c = img.shape
        ratio = 1.0
        if max(h, w) > limit_side_len:
            if h > w:
                ratio = float(limit_side_len) / h
            else:
                ratio = float(limit_side_len) / w
        resize_h = int(h * ratio)
        resize_w = int(w * ratio)
        # 確保長寬是 32 的倍數
        resize_h = max(int(round(resize_h / 32) * 32), 32)
        resize_w = max(int(round(resize_w / 32) * 32), 32)
        
        resized_img = cv2.resize(img, (resize_w, resize_h))
        
        # Normalize: mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        resized_img = resized_img.astype('float32') / 255.0
        resized_img -= np.array([0.485, 0.456, 0.406])
        resized_img /= np.array([0.229, 0.224, 0.225])
        
        # HWC to CHW
        resized_img = resized_img.transpose((2, 0, 1))
        resized_img = np.expand_dims(resized_img, axis=0)

        # 執行推論
        input_name = self.det_session.get_inputs()[0].name
        outputs = self.det_session.run(None, {input_name: resized_img})
        preds = outputs[0][0, 0, :, :] # 取出 Heatmap

        # 後處理 (DBNet Postprocess)
        boxes = self._boxes_from_bitmap(preds, preds > 0.3, dest_width=w, dest_height=h)
        return boxes

    def _boxes_from_bitmap(self, pred, _bitmap, dest_width, dest_height):
        # 將 Heatmap 轉為多邊形外框
        bitmap = _bitmap.astype(np.uint8) * 255
        contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        
        boxes = []
        height, width = bitmap.shape
        for contour in contours:
            epsilon = 0.001 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            points = approx.reshape((-1, 2))
            if points.shape[0] < 4: continue
            
            # 使用 pyclipper 擴張多邊形 (Unclip)
            poly = Polygon(points)
            distance = poly.area * 1.5 / poly.length
            offset = pyclipper.PyclipperOffset()
            offset.AddPath(points, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
            expanded = offset.Execute(distance)
            if not expanded: continue
            
            expanded = np.array(expanded[0])
            rect = cv2.minAreaRect(expanded)
            box = cv2.boxPoints(rect)
            
            # 座標還原回原圖比例
            box[:, 0] = np.clip(box[:, 0] / width * dest_width, 0, dest_width)
            box[:, 1] = np.clip(box[:, 1] / height * dest_height, 0, dest_height)
            boxes.append(box)
            
        return np.array(boxes)

    # ==========================================
    #  辨識模型 (Recognition) 核心邏輯
    # ==========================================
    def _rec_forward(self, img):
        # PP-OCRv4 模型要求輸入高度為 48
        imgC, imgH, imgW = 3, 48, 320
        h, w = img.shape[:2]
        ratio = w / float(h)
        # 動態計算寬度，最大限制到一個合理的長度避免 OOM
        resized_w = int(imgH * ratio)
        
        resized_img = cv2.resize(img, (resized_w, imgH))
        
        # Normalize: mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]
        resized_img = resized_img.astype('float32') / 255.0
        resized_img -= 0.5
        resized_img /= 0.5
        
        # HWC to CHW
        resized_img = resized_img.transpose((2, 0, 1))
        resized_img = np.expand_dims(resized_img, axis=0)

        # 執行推論
        input_name = self.rec_session.get_inputs()[0].name
        outputs = self.rec_session.run(None, {input_name: resized_img})
        preds = outputs[0]

        # CTC 解碼 (Greedy Decode)
        preds_idx = preds.argmax(axis=2)[0]
        preds_prob = preds.max(axis=2)[0]
        
        char_list = []
        conf_list = []
        pre_c = preds_idx[0]
        if pre_c != 0: # 0 是 blank
            char_list.append(self.character[pre_c])
            conf_list.append(preds_prob[0])
            
        for i in range(1, len(preds_idx)):
            c = preds_idx[i]
            # 忽略空白以及相鄰重複的字元
            if c != 0 and c != pre_c:
                char_list.append(self.character[c])
                conf_list.append(preds_prob[i])
            pre_c = c
            
        text = "".join(char_list)
        score = sum(conf_list) / len(conf_list) if conf_list else 0.0
        return text, score

    # ==========================================
    #  工具函式：影像轉正與排序
    # ==========================================
    def _get_rotate_crop_image(self, img, points):
        # 根據四個角點，將傾斜的影像切下來轉正 (Perspective Transform)
        img_crop_width = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
        img_crop_height = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
        pts_std = np.float32([[0, 0], [img_crop_width, 0], [img_crop_width, img_crop_height], [0, img_crop_height]])
        M = cv2.getPerspectiveTransform(np.float32(points), pts_std)
        dst_img = cv2.warpPerspective(img, M, (img_crop_width, img_crop_height), borderMode=cv2.BORDER_REPLICATE)
        # 如果高度大於寬度，代表字是直的，旋轉 90 度
        if dst_img.shape[0] * 1.0 / dst_img.shape[1] >= 1.5:
            dst_img = np.rot90(dst_img)
        return dst_img

    def _sort_boxes(self, dt_boxes):
        num_boxes = dt_boxes.shape[0]
        sorted_boxes = sorted(dt_boxes, key=lambda x: (x[0][1], x[0][0]))
        _boxes = list(sorted_boxes)
        for i in range(num_boxes - 1):
            if abs(_boxes[i+1][0][1] - _boxes[i][0][1]) < 10 and (_boxes[i+1][0][0] < _boxes[i][0][0]):
                tmp = _boxes[i]
                _boxes[i] = _boxes[i+1]
                _boxes[i+1] = tmp
        return _boxes
import math
import numpy as np

from PyQt6.QtCore import Qt, pyqtSignal, QObject, QRunnable, QSize, QRect, QPoint
from PyQt6.QtWidgets import QWidget, QLabel
from PyQt6.QtGui import (QFont, QFontMetrics, QPainter, QColor, QBrush, QPen,
                          QPolygon)


# ==========================================
class CropOCRSignals(QObject):
    result = pyqtSignal(list)   # list of merged-data dicts (box, results, lang)
    error  = pyqtSignal(str)


class CropOCRWorker(QRunnable):
    """
    在背景執行緒裡對使用者框選的矩形範圍跑 OCR。
    因為已知範圍，跳過全圖 det 步驟；直接對裁切後的子圖做 det+rec（小圖很快）。
    box 座標最終換算回原始圖片的完整座標系。
    """
    def __init__(self, file_path, crop_rect, shared_engines, needed_langs,
                 use_gpu, orig_w, orig_h):
        super().__init__()
        self.file_path      = file_path
        self.crop_rect      = crop_rect          # QRect，單位是原始圖片像素
        self.shared_engines = shared_engines     # dict {lang: ONNXOCR}，可被寫回新載入的引擎
        self.needed_langs   = needed_langs       # ["ch", "japan", ...]
        self.use_gpu        = use_gpu
        self.orig_w         = orig_w
        self.orig_h         = orig_h
        self.signals        = CropOCRSignals()
        self.is_cancelled   = False

    def run(self):
        try:
            import cv2 as _cv2
            from PIL import Image as _PIL, ImageOps as _ImageOps
            from onnx_ocr import ONNXOCR as _ONNXOCR

            # 讀圖（含 EXIF 轉正）
            with _PIL.open(self.file_path) as pil_img:
                pil_img = _ImageOps.exif_transpose(pil_img)
                img_rgb = pil_img.convert("RGB")
            img_bgr = _cv2.cvtColor(np.array(img_rgb), _cv2.COLOR_RGB2BGR)

            if self.is_cancelled: return

            # 若 shared_engines 中缺少所需語系，即時載入並寫回（下次可直接複用）
            for lang in self.needed_langs:
                if lang not in self.shared_engines:
                    try:
                        print(f"[CropOCR] 載入 OCR 引擎: {lang}")
                        self.shared_engines[lang] = _ONNXOCR(lang=lang, use_gpu=self.use_gpu)
                    except Exception as e:
                        print(f"[CropOCR] 載入 '{lang}' 失敗: {e}")

            if self.is_cancelled: return

            # 取裁切範圍（夾邊防越界）
            x  = max(0, self.crop_rect.x())
            y  = max(0, self.crop_rect.y())
            x2 = min(img_bgr.shape[1], self.crop_rect.right() + 1)
            y2 = min(img_bgr.shape[0], self.crop_rect.bottom() + 1)
            crop = img_bgr[y:y2, x:x2]
            if crop.size == 0:
                self.signals.result.emit([])
                return

            if self.is_cancelled: return

            merged = []
            print(f"[CropOCR Debug] 框選區域: x={x}, y={y}, w={x2-x}, h={y2-y}  |  langs={self.needed_langs}")
            for lang in self.needed_langs:
                engine = self.shared_engines.get(lang)
                if engine is None:
                    print(f"[CropOCR Debug] [{lang}] 引擎不存在，跳過")
                    continue
                ocr_out = engine.ocr(crop, cls=False)
                if not ocr_out or not ocr_out[0]:
                    print(f"[CropOCR Debug] [{lang}] 偵測無結果，放棄")
                    continue
                raw_lines = ocr_out[0]
                print(f"[CropOCR Debug] [{lang}] 共 {len(raw_lines)} 行原始結果:")
                for idx, line in enumerate(raw_lines):
                    box_local, (text, conf) = line[0], line[1]
                    print(f"[CropOCR Debug]   [{idx}] conf={conf:.4f}  text={repr(text)}")
                    # 把框座標平移回全圖座標
                    box_full = [[int(pt[0]) + x, int(pt[1]) + y] for pt in box_local]
                    merged.append({
                        "box":     box_full,
                        "results": [{"lang": lang, "text": text, "conf": round(float(conf), 4)}],
                        "lang":    lang,
                        "text":    text,
                        "conf":    round(float(conf), 4),
                    })

            print(f"[CropOCR Debug] 最終合併結果: {len(merged)} 個框")
            if not self.is_cancelled:
                self.signals.result.emit(merged)

        except Exception as e:
            if not self.is_cancelled:
                self.signals.error.emit(str(e))


def _merge_raw_ocr_shapely(raw_ocr_data: list) -> list:
    """將 DB 撈出的 flat OCR 列表，以 Shapely 重疊率 >85% 合併成多語言框。
    回傳 [{"box": [...], "results": [{lang, text, conf}, ...]}, ...]
    """
    def _sort_points(box):
        pts = np.array(box)
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect.tolist()

    try:
        from shapely.geometry import Polygon as ShapelyPolygon
    except ImportError:
        ShapelyPolygon = None

    merged_data = []
    if not ShapelyPolygon:
        for item in raw_ocr_data:
            merged_data.append({
                "box": item.get("box", []),
                "results": [{"lang": item.get("lang", "unk"),
                              "text": item.get("text", ""),
                              "conf": item.get("conf", 0.0)}]
            })
        return merged_data

    for item in raw_ocr_data:
        box = item.get("box")
        if not box or len(box) != 4:
            continue
        try:
            sorted_box = _sort_points(box)
            current_poly = ShapelyPolygon(sorted_box)
            if not current_poly.is_valid or current_poly.area <= 0:
                continue
        except Exception:
            continue

        is_merged = False
        for existing in merged_data:
            existing_poly = existing.get("poly")
            if not existing_poly:
                continue
            try:
                if current_poly.intersects(existing_poly):
                    inter_area = current_poly.intersection(existing_poly).area
                    min_area = min(current_poly.area, existing_poly.area)
                    if (inter_area / min_area) > 0.85:
                        existing["results"].append({
                            "lang": item.get("lang", "unk"),
                            "text": item.get("text", ""),
                            "conf": item.get("conf", 0.0)
                        })
                        is_merged = True
                        break
            except Exception:
                pass

        if not is_merged:
            merged_data.append({
                "box": sorted_box,
                "poly": current_poly,
                "results": [{"lang": item.get("lang", "unk"),
                              "text": item.get("text", ""),
                              "conf": item.get("conf", 0.0)}]
            })

    for m in merged_data:
        m.pop("poly", None)

    return merged_data


# ==========================================
class FloatingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        # 讓滑鼠點擊可以直接穿透這個標籤，避免擋住底下的紅框
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

        self.results = []
        self.box_poly = None
        self.cursor_pos = QPoint()
        self.mode = "anchored"

    def update_data(self, results, box_poly, cursor_pos, mode):
        self.results = results
        self.box_poly = box_poly
        self.cursor_pos = cursor_pos
        self.mode = mode

        if not results or not self.parent():
            self.hide()
            return

        # --- 計算面板所需尺寸 ---
        font_text = QFont("Microsoft JhengHei", 13, QFont.Weight.Bold)
        fm_text = QFontMetrics(font_text)
        pad_x = 12
        pad_y = 10
        line_spacing = 6
        max_w = 0
        total_h = 0

        for r in results:
            lang_str = f"[{r.get('lang', 'unk').upper()}]"
            text_str = r.get("text", "")
            conf_str = f" {r.get('conf', 0.0):.2f}"
            w = fm_text.boundingRect(f"{lang_str} {text_str} {conf_str} ").width()
            if w > max_w: max_w = w
            total_h += fm_text.height()

        total_h += (len(results) - 1) * line_spacing
        panel_w = max_w + (pad_x * 2)
        panel_h = total_h + (pad_y * 2)

        parent_w = self.parent().width()
        parent_h = self.parent().height()

        # 超長文字防護：不超過父視窗寬度
        max_panel_w = parent_w - 20
        if panel_w > max_panel_w: panel_w = max_panel_w

        # --- 計算動態座標 (兩種模式) ---
        if mode == "anchored" and box_poly and not box_poly.isEmpty():
            rect = box_poly.boundingRect()
            # 優先位置：框的上方對齊左側
            pos_x = rect.left()
            pos_y = rect.top() - panel_h - 8

            # 若上方空間不夠，改放下方
            if pos_y < 10:
                pos_y = rect.bottom() + 8
            # 若下方也超出畫面 (框極大)，浮在框內頂部
            if pos_y + panel_h > parent_h:
                pos_y = rect.top() + 8

            # X 軸邊界防護：超出右邊則對齊右側，超出左邊則鎖死 10px
            if pos_x + panel_w > parent_w:
                pos_x = rect.right() - panel_w
            if pos_x < 10: pos_x = 10
        else:
            # 跟隨游標模式 (Follow)
            pos_x = cursor_pos.x() + 15
            pos_y = cursor_pos.y() + 15
            if pos_x + panel_w > parent_w: pos_x = cursor_pos.x() - panel_w - 10
            if pos_y + panel_h > parent_h: pos_y = cursor_pos.y() - panel_h - 10
            if pos_x < 10: pos_x = 10
            if pos_y < 10: pos_y = 10

        self.resize(panel_w, panel_h)
        self.move(pos_x, pos_y)
        self.show()
        self.update()

    def paintEvent(self, event):
        if not self.results: return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font_text = QFont("Microsoft JhengHei", 13, QFont.Weight.Bold)
        fm_text = QFontMetrics(font_text)
        pad_x = 12
        pad_y = 10
        line_spacing = 6
        panel_rect = self.rect()

        # ==========================================
        # [新增] 1. 預先計算所有語言標籤的「最大寬度」
        # ==========================================
        max_lang_w = 0
        for r in self.results:
            lang_str = f"[{r.get('lang', 'unk').upper()}] "
            w = fm_text.boundingRect(lang_str).width()
            if w > max_lang_w:
                max_lang_w = w

        # 畫背景面板 (深灰色)
        bg_color_str = self.window().theme_manager.current_colors.get("bg_floating", "#f0232323")
        painter.setBrush(QColor(bg_color_str))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 8, 8)

        current_y = panel_rect.top() + pad_y + fm_text.ascent()

        for r in self.results:
            lang_str = f"[{r.get('lang', 'unk').upper()}] "
            text_str = r.get("text", "")
            conf_str = f" {r.get('conf', 0.0):.2f}"

            #  取得主題顏色
            colors = self.window().theme_manager.current_colors

            # 1. 畫語言標籤 (主題主色)
            painter.setPen(QColor(colors.get("primary", "#60cdff")))
            painter.drawText(panel_rect.left() + pad_x, current_y, lang_str)

            # 2. 計算信心度寬度 (靠右對齊用)
            conf_w = fm_text.boundingRect(conf_str).width()

            # 3. 畫辨識文字 (主題主要文字色)
            text_start_x = panel_rect.left() + pad_x + max_lang_w
            text_max_w = panel_rect.width() - (pad_x * 2) - max_lang_w - conf_w
            if text_max_w < 20: text_max_w = 20
            elided_text = fm_text.elidedText(text_str, Qt.TextElideMode.ElideRight, text_max_w)

            painter.setPen(QColor(colors.get("text_main", "#ffffff")))
            painter.drawText(text_start_x, current_y, elided_text)

            # 4. 畫信心度 (主題次要文字色)
            painter.setPen(QColor(colors.get("text_muted", "#aaaaaa")))
            painter.drawText(panel_rect.right() - pad_x - conf_w, current_y, conf_str)

            current_y += fm_text.height() + line_spacing

# ==========================================
# 請將這段程式碼完全覆蓋原本的 OCRLabel 類別
# ==========================================
class OCRLabel(QLabel):
    hover_info_changed   = pyqtSignal(list, QPolygon, QPoint)
    crop_rect_confirmed  = pyqtSignal(QRect)   # 框選完成，QRect 為原始圖片像素座標
    box_left_clicked     = pyqtSignal(int)              # 左鍵點擊 OCR 框（index）
    box_right_clicked    = pyqtSignal(int, QPoint)      # 右鍵點擊 OCR 框（index, 全域座標）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ocr_data = []
        self.show_ocr_boxes = False
        self.original_size = QSize(0, 0)
        self.search_query = ""
        self.is_precise_mode = False

        # 框選 OCR 相關狀態
        self._crop_mode    = False
        self._crop_start   = QPoint()
        self._crop_end     = QPoint()
        self._crop_drawing = False          # 正在拖曳中
        self._crop_frozen  = False          # 放開後凍結顯示，等待 OCR 結果
        self._crop_items   = []             # 框選 OCR 結果（綠框）

        # 開啟滑鼠追蹤
        self.setMouseTracking(True)
        self.hovered_index = -1
        self.cursor_pos = QPoint(0, 0)

    # ---- 框選模式開關 ----------------------------------------
    def enter_crop_mode(self):
        self._crop_mode    = True
        self._crop_frozen  = False
        self._crop_drawing = False
        self._crop_items   = []
        self._crop_start   = QPoint()
        self._crop_end     = QPoint()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def exit_crop_mode(self):
        self._crop_mode    = False
        self._crop_frozen  = False
        self._crop_drawing = False
        self._crop_items   = []
        self._crop_start   = QPoint()
        self._crop_end     = QPoint()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def set_crop_items(self, items: list):
        """接收框選 OCR 結果，凍結框並以綠色繪製"""
        self._crop_items  = items
        self._crop_frozen = True
        self.update()

    def _label_to_image_rect(self, label_rect: QRect) -> QRect:
        """將 QLabel 座標系內的矩形換算成原始圖片像素座標"""
        pm = self.pixmap()
        if pm is None or pm.isNull() or self.original_size.width() == 0:
            return QRect()
        dw = pm.width();  dh = pm.height()
        ox = (self.width()  - dw) / 2
        oy = (self.height() - dh) / 2
        sx = self.original_size.width()  / dw
        sy = self.original_size.height() / dh
        ix = int((label_rect.x()      - ox) * sx)
        iy = int((label_rect.y()      - oy) * sy)
        iw = int(label_rect.width()          * sx)
        ih = int(label_rect.height()         * sy)
        return QRect(ix, iy, iw, ih)

    # ---- 滑鼠事件 -------------------------------------------
    def mousePressEvent(self, event):
        if self._crop_mode and event.button() == Qt.MouseButton.LeftButton:
            self._crop_start   = event.pos()
            self._crop_end     = event.pos()
            self._crop_drawing = True
            self._crop_frozen  = False
            self._crop_items   = []
            self.update()
            return
        # OCR 框點擊互動（顯示紅框時才生效）
        if self.show_ocr_boxes and self.hovered_index != -1 and not self._crop_mode:
            if event.button() == Qt.MouseButton.LeftButton:
                self.box_left_clicked.emit(self.hovered_index)
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self.box_right_clicked.emit(self.hovered_index, event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._crop_mode and self._crop_drawing and event.button() == Qt.MouseButton.LeftButton:
            self._crop_end     = event.pos()
            self._crop_drawing = False
            rect_label = QRect(self._crop_start, self._crop_end).normalized()
            if rect_label.width() > 5 and rect_label.height() > 5:
                rect_img = self._label_to_image_rect(rect_label)
                self.crop_rect_confirmed.emit(rect_img)
            self.update()
            return
        super().mouseReleaseEvent(event)


    def leaveEvent(self, event):
        """滑鼠完全離開 OCRLabel（移至圖片外的灰色區域）時，立即隱藏懸浮標籤"""
        if self.hovered_index != -1:
            self.hovered_index = -1
            self.hover_info_changed.emit([], QPolygon(), QPoint())
            self.update()
        super().leaveEvent(event)

    def set_draw_boxes(self, show):
        self.show_ocr_boxes = show
        if not show:
            self.hovered_index = -1
            self.hover_info_changed.emit([], QPolygon(), QPoint())
        self.update()

    def set_precomputed_ocr_data(self, precomputed_data, orig_w, orig_h, query="", is_precise=False):
        """[極速版] 捨棄所有運算，直接接收背景算好的幾何資料，UI 執行緒只負責繪圖"""
        self.original_size = QSize(orig_w, orig_h)
        self.search_query = query.lower()
        self.is_precise_mode = is_precise
        self.hovered_index = -1
        self.ocr_data = precomputed_data
        self.update()

    def _calculate_ratios(self, full_text, search_query):
        """計算字元權重與起訖比例"""
        start_idx = full_text.find(search_query)
        if start_idx == -1:
            return 0.0, 1.0

        def get_weight(char):
            return 2.0 if ord(char) > 255 else 1.0

        total_weight = sum(get_weight(c) for c in full_text)
        if total_weight == 0:
            return 0.0, 1.0

        start_weight = sum(get_weight(c) for c in full_text[:start_idx])
        match_weight = sum(get_weight(c) for c in search_query)

        start_ratio = start_weight / total_weight
        end_ratio = (start_weight + match_weight) / total_weight

        return start_ratio, end_ratio

    # ==========================================
    # [新增] 滑鼠移動事件：處理座標對齊與碰撞偵測
    # ==========================================
    def mouseMoveEvent(self, event):
        # 框選拖曳更新
        if self._crop_mode and self._crop_drawing:
            self._crop_end = event.pos()
            self.update()
            return

        super().mouseMoveEvent(event)

        # 如果沒開紅框，或者沒資料，就不浪費算力
        if not self.show_ocr_boxes or not self.ocr_data or not self.pixmap():
            return

        if self.original_size.width() == 0 or self.original_size.height() == 0:
            return

        self.cursor_pos = event.pos()

        # 1. 取得目前圖片在畫面上的縮放比例與位移
        displayed_w = self.pixmap().width()
        displayed_h = self.pixmap().height()
        offset_x = (self.width() - displayed_w) / 2
        offset_y = (self.height() - displayed_h) / 2
        scale_x = displayed_w / self.original_size.width()
        scale_y = displayed_h / self.original_size.height()

        # 2. 將滑鼠在螢幕上的座標，逆向還原回圖片的「真實像素座標」
        real_x = (self.cursor_pos.x() - offset_x) / scale_x
        real_y = (self.cursor_pos.y() - offset_y) / scale_y
        real_point = QPoint(int(real_x), int(real_y))

        # 3. 多邊形碰撞測試 (Hit Test)
        new_hovered_index = -1
        for i, item in enumerate(self.ocr_data):
            box = item.get("box")
            if box and len(box) == 4:
                poly = QPolygon([QPoint(int(pt[0]), int(pt[1])) for pt in box])
                if poly.containsPoint(real_point, Qt.FillRule.OddEvenFill):
                    new_hovered_index = i
                    break

        # 4. 如果踩到的目標改變了，或者游標在框內移動(需要更新標籤位置)
        if self.hovered_index != new_hovered_index or new_hovered_index != -1:
            self.hovered_index = new_hovered_index
            self.update()

            if self.hovered_index != -1:
                item = self.ocr_data[self.hovered_index]
                results = item.get("results", [])

                sorted_box = item.get("box")
                full_poly_points = []
                for pt in sorted_box:
                    nx = pt[0] * scale_x + offset_x
                    ny = pt[1] * scale_y + offset_y
                    full_poly_points.append(QPoint(int(nx), int(ny)))
                poly = QPolygon(full_poly_points)

                self.hover_info_changed.emit(results, poly, self.cursor_pos)
            else:
                self.hover_info_changed.emit([], QPolygon(), QPoint())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── 計算圖片縮放參數（共用）──────────────────────────────
        pm = self.pixmap()
        has_pm = pm is not None and not pm.isNull()
        if has_pm and self.original_size.width() > 0:
            dw       = pm.width();   dh = pm.height()
            offset_x = (self.width()  - dw) / 2
            offset_y = (self.height() - dh) / 2
            scale_x  = dw / self.original_size.width()
            scale_y  = dh / self.original_size.height()
        else:
            has_pm = False

        # ── 1. 既有 OCR 紅框（Shift 模式）────────────────────────
        if self.show_ocr_boxes and self.ocr_data and has_pm:
            for i, item in enumerate(self.ocr_data):
                sorted_box = item.get("box")
                if not sorted_box or len(sorted_box) != 4: continue

                results   = item.get("results", [])
                full_text = " ".join([r.get("text", "") for r in results]).lower()
                p0, p1, p2, p3 = sorted_box[0], sorted_box[1], sorted_box[2], sorted_box[3]
                highlight_box = sorted_box

                if self.search_query and self.search_query in full_text:
                    if self.is_precise_mode:
                        match_text = ""
                        for r in results:
                            if self.search_query in r.get("text", "").lower():
                                match_text = r.get("text", "").lower(); break
                        if not match_text: match_text = full_text
                        start_ratio, end_ratio = self._calculate_ratios(match_text, self.search_query)
                        margin = 0.015
                        if start_ratio > 0.0: start_ratio = min(start_ratio + margin, 1.0)
                        if end_ratio < 1.0:   end_ratio   = max(end_ratio   - margin, 0.0)
                        if start_ratio >= end_ratio:
                            center = (start_ratio + end_ratio) / 2.0
                            start_ratio, end_ratio = center - 0.001, center + 0.001
                        width_px  = math.hypot(p0[0]-p1[0], p0[1]-p1[1])
                        height_px = math.hypot(p0[0]-p3[0], p0[1]-p3[1])
                        if height_px > width_px * 1.2:
                            np0=[p0[0]+(p3[0]-p0[0])*start_ratio, p0[1]+(p3[1]-p0[1])*start_ratio]
                            np3=[p0[0]+(p3[0]-p0[0])*end_ratio,   p0[1]+(p3[1]-p0[1])*end_ratio]
                            np1=[p1[0]+(p2[0]-p1[0])*start_ratio, p1[1]+(p2[1]-p1[1])*start_ratio]
                            np2=[p1[0]+(p2[0]-p1[0])*end_ratio,   p1[1]+(p2[1]-p1[1])*end_ratio]
                        else:
                            np0=[p0[0]+(p1[0]-p0[0])*start_ratio, p0[1]+(p1[1]-p0[1])*start_ratio]
                            np1=[p0[0]+(p1[0]-p0[0])*end_ratio,   p0[1]+(p1[1]-p0[1])*end_ratio]
                            np3=[p3[0]+(p2[0]-p3[0])*start_ratio, p3[1]+(p2[1]-p3[1])*start_ratio]
                            np2=[p3[0]+(p2[0]-p3[0])*end_ratio,   p3[1]+(p2[1]-p3[1])*end_ratio]
                        highlight_box = [np0, np1, np2, np3]

                    poly_pts = [QPoint(int(pt[0]*scale_x+offset_x), int(pt[1]*scale_y+offset_y))
                                for pt in highlight_box]
                    colors = self.window().theme_manager.current_colors
                    painter.setBrush(QBrush(QColor(colors.get("ocr_highlight", "#64ffff00"))))
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawPolygon(QPolygon(poly_pts))

                full_pts = [QPoint(int(pt[0]*scale_x+offset_x), int(pt[1]*scale_y+offset_y))
                            for pt in sorted_box]
                colors = self.window().theme_manager.current_colors
                hover_bg = QColor(colors.get("primary", "#60cdff")); hover_bg.setAlpha(60)
                if i == self.hovered_index:
                    painter.setBrush(QBrush(hover_bg))
                    painter.setPen(QPen(QColor(colors.get("primary", "#60cdff")), 3))
                else:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(colors.get("ocr_box_normal", "#c8ff0000")), 2))
                painter.drawPolygon(QPolygon(full_pts))

        # ── 2. 框選 OCR 結果（綠框）──────────────────────────────
        if self._crop_items and has_pm:
            green_pen  = QPen(QColor(0, 220, 80, 220), 2)
            green_fill = QColor(0, 220, 80, 40)
            for item in self._crop_items:
                box = item.get("box")
                if not box or len(box) != 4: continue
                pts = [QPoint(int(pt[0]*scale_x+offset_x), int(pt[1]*scale_y+offset_y))
                       for pt in box]
                painter.setBrush(QBrush(green_fill))
                painter.setPen(green_pen)
                painter.drawPolygon(QPolygon(pts))

        # ── 3. 橡皮框（拖曳中 & 凍結）───────────────────────────
        if self._crop_mode and (self._crop_drawing or self._crop_frozen):
            rect = QRect(self._crop_start, self._crop_end).normalized()
            if not self._crop_drawing and self._crop_items:
                # OCR 完成後框變綠色實線
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(0, 220, 80, 200), 2))
            else:
                # 拖曳中：藍色虛線
                dash_pen = QPen(QColor(100, 180, 255, 200), 2, Qt.PenStyle.DashLine)
                painter.setBrush(QColor(100, 180, 255, 25))
                painter.setPen(dash_pen)
            painter.drawRect(rect)

        painter.end()

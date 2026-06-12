"""
ui/widgets/image_delegate.py
----------------------------
Gallery card rendering layer.

Contains:
  - ImageItem          : data structure for a single image result
  - FunnelCardItem     : virtual card displaying search-funnel statistics
  - WorkerSignals      : Qt signals for ThumbnailLoader
  - PreviewSignals     : Qt signals for PreviewLoader
  - _merge_raw_ocr_shapely : helper to merge overlapping OCR boxes via Shapely
  - PreviewLoader      : QRunnable that loads a high-res preview in the background
  - ThumbnailLoader    : QRunnable that loads / caches thumbnails in the background
  - ImageDelegate      : QStyledItemDelegate that paints each gallery card
"""

import os

from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QRunnable,
    QSize, QRect, QRectF, QFileInfo,
)
from PyQt6.QtWidgets import (
    QStyledItemDelegate, QStyle, QFileIconProvider,
)
from PyQt6.QtGui import (
    QPixmap, QImage, QColor, QFont, QFontMetrics,
    QPainter, QBrush, QPen, QPainterPath, QImageReader,
)


# ==========================================
#  資料結構
# ==========================================

class ImageItem:
    """單張圖片的資料結構，統一管理所有屬性"""
    def __init__(self, path, filename, score, ocr_text="", mtime=0, width=0, height=0):
        self.path = path
        self.filename = filename
        self.score = score
        self.ocr_text = ocr_text
        self.mtime = mtime
        self.width = width
        self.height = height
        self.is_ocr_match = False
        self.is_pinned = False
        self.is_funnel_card = False   # 漏斗統計卡片旗標

        self.score_val = float(score)
        self.score_str = f"{self.score_val:.4f}" if self.score_val > 0.0001 else ""
        self._elided_name_cache = {}

    def get_elided_name(self, fm, width):
        """動態快取省略檔名，相同寬度的卡片只需要計算一次"""
        if width not in self._elided_name_cache:
            self._elided_name_cache[width] = fm.elidedText(self.filename, Qt.TextElideMode.ElideRight, width)
        return self._elided_name_cache[width]


class FunnelCardItem:
    """漏斗統計卡片的虛擬項目 (僅供展示，不對應真實圖檔)"""
    VIRTUAL_PATH = "__FUNNEL_CARD__"

    def __init__(self, raw_count: int, after_date: int, after_aspect: int, final_count: int):
        self.path = self.VIRTUAL_PATH
        self.filename = "Search Funnel"
        self.score = 0.0
        self.score_val = 0.0
        self.score_str = ""
        self.ocr_text = ""
        self.mtime = float("inf")   # 排序鍵：比所有圖片更早，確保排在最前面（後面用特殊處理）
        self.width = 0
        self.height = 0
        self.is_ocr_match = False
        self.is_pinned = False
        self.is_funnel_card = True

        self.raw_count = raw_count
        self.after_date = after_date
        self.after_aspect = after_aspect
        self.final_count = final_count

        # 每一列的 (數字, 標籤名稱)
        self.rows = [
            (raw_count,   "FAISS 初始結果"),
            (after_date,  "日期篩選後"),
            (after_aspect,"比例篩選後"),
            (final_count, "最終顯示"),
        ]

    def get_elided_name(self, fm, width):
        return "Search Funnel"


# ==========================================
#  Qt Signals
# ==========================================

class WorkerSignals(QObject):
    result = pyqtSignal(str, QPixmap, bool)  # 加入一個布林值 is_final，讓系統知道這是不是最終的高清圖


class PreviewSignals(QObject):
    #  關鍵修復：將跨執行緒的傳遞物件從 QPixmap 換成絕對安全的 QImage
    result = pyqtSignal(str, QImage, list, int, int, str, bool)


# ==========================================
#  OCR 合併輔助函式
# ==========================================

def _merge_raw_ocr_shapely(raw_ocr_data: list) -> list:
    """將 DB 撈出的 flat OCR 列表，以 Shapely 重疊率 >85% 合併成多語言框。
    回傳 [{"box": [...], "results": [{lang, text, conf}, ...]}, ...]
    """
    def _sort_points(box):
        import numpy as np
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
#  背景工作執行緒
# ==========================================

class PreviewLoader(QRunnable):
    """專門用於大圖預覽的高清背景讀取器 + 幾何碰撞運算器"""
    def __init__(self, file_path, target_size, engine, query, is_precise, orig_w, orig_h):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.engine = engine  #  拿到引擎準備去撈資料
        self.query = query
        self.is_precise = is_precise
        self.orig_w = orig_w
        self.orig_h = orig_h
        self.signals = PreviewSignals()
        self.is_cancelled = False

    def run(self):
        if self.is_cancelled: return

        # ==========================================
        #  任務 A-0：背景向 SQLite 請求 JSON 解析 (秒速且不卡 UI)
        # ==========================================
        raw_ocr_data = []
        if self.engine:
            raw_ocr_data = self.engine.get_ocr_data_by_path(self.file_path)

        if self.is_cancelled: return

        # ==========================================
        #  任務 A：背景執行 Shapely 群組合併
        # ==========================================
        merged_data = _merge_raw_ocr_shapely(raw_ocr_data)

        if self.is_cancelled: return

        # ==========================================
        #  任務 B：背景讀取高清圖片 (改用 QImage)
        # ==========================================
        final_img = QImage()  # 建立一個空的 QImage 作為預設值
        try:
            reader = QImageReader(self.file_path)
            # [修正] 先取原始(RAW)尺寸再啟用 AutoTransform：
            # 若先 setAutoTransform(True) 再 size()，Qt6 回傳的是顯示方向尺寸（直向）；
            # 但 JPEG 解碼器仍以原始橫向資料工作，setScaledSize 給直向提示會導致畫面扭曲或超出邊界。
            orig_size = reader.size()  # RAW 尺寸（EXIF 旋轉前）
            reader.setAutoTransform(True)

            if orig_size.isValid():
                scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(scaled_size)
                img = reader.read()

                if not self.is_cancelled and not img.isNull():
                    # [修正] EXIF 旋轉後寬高可能超出 target_size（手機直拍照片常見），需再縮放一次
                    if img.width() > self.target_size.width() or img.height() > self.target_size.height():
                        img = img.scaled(
                            self.target_size,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation
                        )
                    # 轉換格式，但保持為 QImage
                    final_img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        except Exception as e:
            print(f"Preview Loader Error: {e}")

        if not self.is_cancelled:
            # 安全地將 QImage 與 OCR 資料一起發射給主執行緒
            self.signals.result.emit(self.file_path, final_img, merged_data, self.orig_w, self.orig_h, self.query, self.is_precise)


class ThumbnailLoader(QRunnable):
    """背景圖片讀取器 (智慧縮放 + GPU 材質加速版)"""
    def __init__(self, file_path, target_size):
        super().__init__()
        self.file_path = file_path
        self.target_size = target_size
        self.signals = WorkerSignals()
        self.is_cancelled = False

    def run(self):
        if self.is_cancelled:
            self.signals.result.emit(self.file_path, QPixmap(), True)
            return

        import hashlib
        # 必須與 indexer.generate_l2_cache() 共用同一目錄（core/paths.py），
        # 否則 indexer 預產的縮圖永遠不會命中，每張卡片都退化成全圖解碼
        from core.paths import THUMBNAIL_CACHE_DIR as cache_dir

        path_hash = hashlib.md5(self.file_path.encode('utf-8')).hexdigest()
        cache_path = os.path.join(cache_dir, f"{path_hash}.webp")

        image = QImage()
        has_l2 = False

        if os.path.exists(cache_path):
            image.load(cache_path)
            if not image.isNull():
                has_l2 = True

        #  判定：目標尺寸如果大於 256 (例如 XL 模式)，代表 L2 尺寸不夠，需要升級！
        needs_upgrade = (self.target_size.width() > 256 or self.target_size.height() > 256)

        # ==========================================
        #  階段一：光速發射 L2 佔位圖 (毫秒級)
        # ==========================================
        if has_l2:
            if self.is_cancelled:
                self.signals.result.emit(self.file_path, QPixmap(), True)
                return

            # 關鍵魔法：在背景將小圖「平滑放大」到目標尺寸，UI 接手時直接貼上就好！
            scaled_l2 = image.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            pixmap = QPixmap.fromImage(scaled_l2.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))

            # 第一發射：先讓畫面有圖，並標記是否為最終圖
            self.signals.result.emit(self.file_path, pixmap, not needs_upgrade)

            if not needs_upgrade:
                return  # M/L 模式在這裡就結束了，極度省電！

        # ==========================================
        #  階段二：背景替換高清大圖 (重炮火力)
        # ==========================================
        if self.is_cancelled:
            self.signals.result.emit(self.file_path, QPixmap(), True)
            return

        try:
            reader = QImageReader(self.file_path)
            orig_size = reader.size()  # RAW 尺寸（EXIF 旋轉前）
            reader.setAutoTransform(True)
            if orig_size.isValid():
                scaled_size = orig_size.scaled(self.target_size, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(scaled_size)
                high_res_image = reader.read()

                # [修正] EXIF 旋轉後寬高可能超出 target_size，縮圖前先確保大小正確
                if not high_res_image.isNull() and (
                    high_res_image.width() > self.target_size.width() or
                    high_res_image.height() > self.target_size.height()
                ):
                    high_res_image = high_res_image.scaled(
                        self.target_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )

                # 動態補建 L2 (如果之前沒有的話)
                if not has_l2 and not high_res_image.isNull() and not self.is_cancelled:
                    os.makedirs(cache_dir, exist_ok=True)
                    high_res_image.save(cache_path, "WEBP", 80)

                if self.is_cancelled:
                    self.signals.result.emit(self.file_path, QPixmap(), True)
                    return

                if not high_res_image.isNull():
                    final_pixmap = QPixmap.fromImage(high_res_image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
                    #  第二發射：高清原圖覆蓋上去！(is_final = True)
                    self.signals.result.emit(self.file_path, final_pixmap, True)
                else:
                    self.signals.result.emit(self.file_path, QPixmap(), True)
            else:
                self.signals.result.emit(self.file_path, QPixmap(), True)
        except Exception:
            self.signals.result.emit(self.file_path, QPixmap(), True)


# ==========================================
#  畫廊卡片 Delegate
# ==========================================

class ImageDelegate(QStyledItemDelegate):
    """負責繪製列表中的每一個項目 (支援動態調整大小)"""
    def __init__(self, card_size, thumb_height, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.padding = 10
        self.radius = 8
        self.font_name = QFont("Segoe UI", 10, QFont.Weight.Medium)
        self.font_score = QFont("Consolas", 9)
        self.font_tag = QFont("Segoe UI", 8, QFont.Weight.Bold)

        self.fm_name = QFontMetrics(self.font_name)

        self.card_size = card_size
        self.thumb_height = thumb_height

        # 取得系統預設圖示
        provider = QFileIconProvider()
        # 使用一個不存在的 .jpg 檔名來獲取系統對 jpg 的預設圖示
        self.placeholder_icon = provider.icon(QFileInfo("template.jpg"))

    # [新增] 更新尺寸的方法
    def set_view_params(self, card_size, thumb_height):
        self.card_size = card_size
        self.thumb_height = thumb_height

    def sizeHint(self, option, index):
        return self.card_size

    def paint(self, painter: QPainter, option, index):
        if not index.isValid(): return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        item = index.data(Qt.ItemDataRole.UserRole)
        if not item:
            painter.restore()
            return

        # ──────────────────────────────────────────────
        #  漏斗卡片專屬渲染
        # ──────────────────────────────────────────────
        if getattr(item, 'is_funnel_card', False):
            self._paint_funnel_card(painter, option, item)
            painter.restore()
            return

        pixmap = index.data(Qt.ItemDataRole.DecorationRole)

        rect = option.rect
        card_rect = rect.adjusted(4, 4, -4, -4)

        # ── 取得主題顏色 ──
        if hasattr(self.main_window, 'theme_manager'):
            colors = self.main_window.theme_manager.current_colors
        else:
            colors = {}

        # ── 狀態旗標 ──
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover    = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # ── 背景色（hover 時換底色，不影響邊框） ──
        bg_color   = QColor(colors.get("bg_card", "#2b2b2b"))
        text_color = QColor(colors.get("text_main", "#ffffff"))
        if text_color.name().lower() == "#ffffff":
            text_color = QColor("#e0e0e0")
        if is_hover and not is_selected:
            bg_color = QColor(colors.get("bg_hover", "#383838"))

        # 1. 只填充背景，不畫邊框（邊框統一在最後繪製）
        path = QPainterPath()
        path.addRoundedRect(QRectF(card_rect), self.radius, self.radius)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

        # --- 版面計算 ---
        bottom_margin = self.padding
        score_height = 20
        score_y = card_rect.bottom() - bottom_margin - score_height
        score_rect = QRect(
            card_rect.left() + self.padding,
            score_y,
            100, score_height
        )

        name_height = 20
        name_y = score_y - 2 - name_height
        text_rect = QRect(
            card_rect.left() + self.padding,
            name_y,
            card_rect.width() - 2 * self.padding,
            name_height
        )

        img_rect_height = self.thumb_height
        img_rect = QRect(
            card_rect.left() + self.padding,
            card_rect.top() + self.padding,
            card_rect.width() - 2 * self.padding,
            img_rect_height
        )

        painter.setClipPath(path)

        if pixmap and not pixmap.isNull():
            x_off = (img_rect.width() - pixmap.width()) / 2
            y_off = (img_rect.height() - pixmap.height()) / 2

            painter.drawPixmap(
                img_rect.left() + int(x_off),
                img_rect.top() + int(y_off),
                pixmap
            )
        else:
            min_dim = min(img_rect.width(), img_rect.height())
            icon_size = max(48, int(min_dim * 0.60))

            icon_rect = QRect(0, 0, icon_size, icon_size)
            icon_rect.moveCenter(img_rect.center())

            painter.setOpacity(0.2)
            self.placeholder_icon.paint(painter, icon_rect)
            painter.setOpacity(1.0)

        painter.setClipping(False)

        # 3. 繪製文字
        painter.setFont(self.font_name)
        painter.setPen(text_color)
        elided_name = item.get_elided_name(self.fm_name, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided_name)

        # 4. 繪製分數
        painter.setFont(self.font_score)

        if item.score_val > 0.0001:
            if item.score_val > 0.3:
                score_color = colors.get("primary", "#60cdff")
            else:
                score_color = colors.get("text_muted", "#999999")

            painter.setPen(QColor(score_color))
            painter.drawText(score_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, item.score_str)

        # 5. 右下角並列標籤 (PINNED + TEXT)
        tag_h = 16
        tag_y = score_rect.top() + 2
        tag_gap = 4
        pin_tag_w = 45
        ocr_tag_w = 36
        right_edge = card_rect.right() - self.padding

        painter.setFont(self.font_tag)
        painter.setPen(Qt.PenStyle.NoPen)

        if item.is_pinned and item.is_ocr_match:
            # 兩者並列：[PINNED] [TEXT]，TEXT 靠右
            ocr_x = right_edge - ocr_tag_w
            pin_x = ocr_x - tag_gap - pin_tag_w

            pin_rect = QRect(pin_x, tag_y, pin_tag_w, tag_h)
            ocr_rect = QRect(ocr_x, tag_y, ocr_tag_w, tag_h)

            pin_bg = colors.get("accent", colors.get("primary", "#60cdff"))
            painter.setBrush(QBrush(QColor(pin_bg)))
            painter.drawRoundedRect(pin_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(pin_rect, Qt.AlignmentFlag.AlignCenter, "PIN")

            ocr_bg = colors.get("text_success", "#4caf50")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(ocr_bg)))
            painter.drawRoundedRect(ocr_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(ocr_rect, Qt.AlignmentFlag.AlignCenter, "TEXT")

        elif item.is_pinned:
            pin_rect = QRect(right_edge - pin_tag_w, tag_y, pin_tag_w, tag_h)
            pin_bg = colors.get("accent", colors.get("primary", "#60cdff"))
            painter.setBrush(QBrush(QColor(pin_bg)))
            painter.drawRoundedRect(pin_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(pin_rect, Qt.AlignmentFlag.AlignCenter, "PIN")

        elif item.is_ocr_match:
            ocr_rect = QRect(right_edge - ocr_tag_w, tag_y, ocr_tag_w, tag_h)
            ocr_bg = colors.get("text_success", "#4caf50")
            painter.setBrush(QBrush(QColor(ocr_bg)))
            painter.drawRoundedRect(ocr_rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(ocr_rect, Qt.AlignmentFlag.AlignCenter, "TEXT")

        # ── 邊框層（由內而外疊加，選取框永遠最頂層） ──
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # 層 A：預設細邊框或 hover 邊框（無任何特殊狀態時）
        if not item.is_pinned and not item.is_ocr_match and not is_selected:
            border_c = colors.get("primary_hover", "#7ce0ff") if is_hover else colors.get("border_main", "#3e3e3e")
            painter.setPen(QPen(QColor(border_c), 1))
            painter.drawPath(path)

        # 層 B：OCR 綠色虛線環
        # 畫在比 card_rect 外擴 2px 的路徑，確保與釘選藍色(Layer C)完全不重疊，兩層同時可見
        if item.is_ocr_match:
            ocr_path = QPainterPath()
            ocr_path.addRoundedRect(
                QRectF(card_rect.adjusted(-2, -2, 2, 2)),
                self.radius + 1, self.radius + 1,
            )
            pen_ocr = QPen(QColor(colors.get("text_success", "#4caf50")), 1.5, Qt.PenStyle.DashLine)
            pen_ocr.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_ocr)
            painter.drawPath(ocr_path)

        # 層 C：釘選藍色實線（2px，畫在 card_rect 位置）
        if item.is_pinned:
            pen_pin = QPen(
                QColor(colors.get("accent", colors.get("primary", "#60cdff"))),
                2, Qt.PenStyle.SolidLine,
            )
            pen_pin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_pin)
            painter.drawPath(path)

        # 層 D：WASD / 滑鼠選取框（3px，永遠最頂層；比釘選線粗一格，差異明顯）
        if is_selected:
            pen_sel = QPen(QColor(colors.get("primary", "#60cdff")), 3, Qt.PenStyle.SolidLine)
            pen_sel.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen_sel)
            painter.drawPath(path)

        painter.restore()

    def _paint_funnel_card(self, painter: QPainter, option, item):
        """漏斗統計卡片的專屬繪製邏輯"""
        rect = option.rect
        card_rect = rect.adjusted(4, 4, -4, -4)

        if hasattr(self.main_window, 'theme_manager'):
            colors = self.main_window.theme_manager.current_colors
        else:
            colors = {}

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover    = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # ── 背景 ──
        bg_color = QColor(colors.get("bg_card", "#2b2b2b"))
        if is_hover and not is_selected:
            bg_color = bg_color.lighter(115)

        path_shape = QPainterPath()
        path_shape.addRoundedRect(QRectF(card_rect), self.radius, self.radius)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path_shape)

        # ── 標題 "漏斗統計" ──
        accent = QColor(colors.get("primary", "#60cdff"))
        text_color = QColor(colors.get("text_main", "#e0e0e0"))
        muted_color = QColor(colors.get("text_muted", "#888888"))

        title_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        row_num_font = QFont("Consolas", 14, QFont.Weight.Bold)
        row_label_font = QFont("Segoe UI", 8)

        inner_x = card_rect.left() + self.padding
        inner_w = card_rect.width() - 2 * self.padding

        # 標題區
        title_rect = QRect(inner_x, card_rect.top() + 8, inner_w, 18)
        painter.setFont(title_font)
        painter.setPen(accent)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, "📊 Search Funnel")

        # 分隔線
        sep_y = title_rect.bottom() + 5
        painter.setPen(QPen(muted_color, 1, Qt.PenStyle.SolidLine))
        painter.drawLine(inner_x, sep_y, inner_x + inner_w, sep_y)

        # ── 每一列資料 ──
        row_area_top = sep_y + 6
        row_count = len(item.rows)
        row_area_h = card_rect.bottom() - self.padding - row_area_top
        row_h = row_area_h // row_count if row_count else 30

        # 最大數字用來比例換算（避免除零）
        max_num = max((r[0] for r in item.rows), default=1) or 1

        for i, (num, label) in enumerate(item.rows):
            ry = row_area_top + i * row_h

            # 進度條背景
            bar_bg_rect = QRectF(inner_x, ry + row_h - 6, inner_w, 4)
            painter.setBrush(QBrush(muted_color.darker(150)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar_bg_rect, 2, 2)

            # 進度條前景
            fill_w = (num / max_num) * inner_w
            if fill_w > 0:
                bar_fill_rect = QRectF(inner_x, ry + row_h - 6, fill_w, 4)
                # 最後一行（final_count）用 accent 色，其餘用漸層
                if i == row_count - 1:
                    bar_color = accent
                else:
                    bar_color = QColor(colors.get("primary", "#60cdff")).lighter(100 + i * 20)
                painter.setBrush(QBrush(bar_color))
                painter.drawRoundedRect(bar_fill_rect, 2, 2)

            # 數字（左對齊大字）
            num_rect = QRect(inner_x, ry, 60, row_h - 8)
            painter.setFont(row_num_font)
            painter.setPen(accent if i == row_count - 1 else text_color)
            painter.drawText(num_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(num))

            # 標籤（右側小字）
            label_rect = QRect(inner_x + 60, ry, inner_w - 60, row_h - 8)
            painter.setFont(row_label_font)
            painter.setPen(muted_color if i < row_count - 1 else accent)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        # ── 邊框 ──
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if is_selected:
            pen = QPen(accent, 3, Qt.PenStyle.SolidLine)
        else:
            border_c = colors.get("primary_hover", "#7ce0ff") if is_hover else colors.get("border_main", "#3e3e3e")
            pen = QPen(QColor(border_c), 1, Qt.PenStyle.DashLine)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path_shape)

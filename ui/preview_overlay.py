import os

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QSize, QTimer, QThreadPool
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QApplication, QLineEdit, QMenu, QSizePolicy, QGraphicsDropShadowEffect,
)
from PyQt6.QtGui import (
    QPixmap, QColor, QFont, QPainter, QBrush, QPen, QPainterPath, QPolygon,
)

# These classes are currently defined in Blur-main.py and will be relocated
# to their own modules during the full refactor (Phase 3).
# At runtime they are available via the top-level namespace of Blur-main.
from ui.widgets.ocr_widgets import OCRLabel, FloatingWidget


class PreviewOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 必須在 self.hide() 之前先設好，否則 hideEvent 被觸發時會引發 AttributeError
        self.current_preview_path = ""
        self.current_preview_worker = None
        self._crop_worker  = None       # CropOCRWorker
        self._crop_items   = []         # 框選 OCR 暫存結果
        self._last_crop_rect_px = None  # 使用者框選的原始圖片像素 QRect
        self._edit_mode_item = None     # 正在編輯的 OCR 框資料（None 表示新增模式）
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        self.setObjectName("PreviewOverlayMask")

        self.layout = QVBoxLayout(self)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_label = OCRLabel()
        self.image_label.hover_info_changed.connect(self.on_hover_info_changed)
        self.image_label.crop_rect_confirmed.connect(self._on_crop_confirmed)
        self.image_label.box_left_clicked.connect(self._on_box_left_clicked)
        self.image_label.box_right_clicked.connect(self._on_box_right_clicked)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: transparent;")
        # Expanding 讓 label 始終填滿可用空間，pixmap 變動不觸發 layout 重算
        # 確保 _reposition_toolbar 讀到的 geometry 永遠穩定
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0,0,0, 150))
        self.image_label.setGraphicsEffect(shadow)

        self.layout.addWidget(self.image_label)

        self.filename_label = QLabel()
        self.filename_label.setObjectName("PreviewOverlayFilename")
        self.filename_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.filename_label)

        self.ocr_hint = QLabel("SHIFT: 長按顯示紅框 / 按一下切換鎖定　　◉ 工具列按鈕：切換顯示")
        self.ocr_hint.setObjectName("PreviewOverlayHint")
        self.layout.addWidget(self.ocr_hint, alignment=Qt.AlignmentFlag.AlignCenter)

        self.floating_tag = FloatingWidget(self)

        # --- 浮動功能列 (圖片右側，頂部對齊) ---
        self.img_toolbar = QWidget(self)
        self.img_toolbar.setObjectName("PreviewImgToolbar")
        self.img_toolbar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _tb_layout = QVBoxLayout(self.img_toolbar)
        _tb_layout.setContentsMargins(5, 5, 5, 5)
        _tb_layout.setSpacing(4)
        _tb_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # OCR 紅框切換按鈕（圖示：眼睛，放在第一顆）
        self.btn_ocr_toggle = QPushButton("◉")
        self.btn_ocr_toggle.setObjectName("PreviewToolbarBtn")
        self.btn_ocr_toggle.setToolTip("顯示／隱藏 OCR 紅框 (Shift)")
        self.btn_ocr_toggle.setFixedSize(36, 36)
        self.btn_ocr_toggle.setCheckable(True)
        self.btn_ocr_toggle.clicked.connect(self._on_toolbar_ocr_toggle)
        _tb_layout.addWidget(self.btn_ocr_toggle)

        self.btn_ocr_crop = QPushButton("[T]")
        self.btn_ocr_crop.setObjectName("PreviewToolbarBtn")
        self.btn_ocr_crop.setToolTip("框選區域執行 OCR")
        self.btn_ocr_crop.setFixedSize(36, 36)
        self.btn_ocr_crop.setCheckable(True)
        self.btn_ocr_crop.clicked.connect(self._toggle_crop_mode)
        _tb_layout.addWidget(self.btn_ocr_crop)

        self.img_toolbar.adjustSize()
        self.img_toolbar.hide()

        # --- 框選結果確認列（浮在圖片下邊緣內側）---
        self._crop_confirm_bar = QWidget(self)
        self._crop_confirm_bar.setObjectName("CropConfirmBar")
        self._crop_confirm_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _cb_layout = QVBoxLayout(self._crop_confirm_bar)
        _cb_layout.setContentsMargins(10, 8, 10, 8)
        _cb_layout.setSpacing(6)

        # 第一排：辨識狀態文字
        self._crop_status_lbl = QLabel("辨識中…")
        self._crop_status_lbl.setObjectName("CropStatusLabel")
        _cb_layout.addWidget(self._crop_status_lbl)

        # 第二排：可編輯文字欄（OCR 完成後顯示，可修改後再存入 DB）
        self._crop_edit = QLineEdit()
        self._crop_edit.setObjectName("CropTextEdit")
        self._crop_edit.setPlaceholderText("點此輸入或修改文字…")
        self._crop_edit.hide()
        self._crop_edit.textChanged.connect(self._on_crop_edit_changed)
        _cb_layout.addWidget(self._crop_edit)

        # 第三排：按鈕靠右排列
        _btn_row = QHBoxLayout()
        _btn_row.setContentsMargins(0, 0, 0, 0)
        _btn_row.setSpacing(8)
        _btn_row.addStretch()

        self._btn_save_crop = QPushButton("加入資料庫")
        self._btn_save_crop.setObjectName("CropSaveBtn")
        self._btn_save_crop.setEnabled(False)
        self._btn_save_crop.clicked.connect(self._save_crop_to_db)
        _btn_row.addWidget(self._btn_save_crop)

        self._btn_cancel_crop = QPushButton("取消")
        self._btn_cancel_crop.setObjectName("CropCancelBtn")
        self._btn_cancel_crop.clicked.connect(self._cancel_crop)
        _btn_row.addWidget(self._btn_cancel_crop)

        _cb_layout.addLayout(_btn_row)

        self._crop_confirm_bar.adjustSize()
        self._crop_confirm_bar.hide()

    # ── 框選模式控制 ────────────────────────────────────────────
    def _toggle_crop_mode(self, checked: bool):
        if checked:
            self._cancel_crop()          # 先清除上次殘留
            self.image_label.enter_crop_mode()
            self.btn_ocr_crop.setStyleSheet("background-color: rgba(0,200,80,60);")
        else:
            self._cancel_crop()

    def _cancel_crop(self):
        if self._crop_worker:
            self._crop_worker.is_cancelled = True
            self._crop_worker = None
        self._crop_items = []
        self._last_crop_rect_px = None
        self._edit_mode_item = None
        self._crop_edit.clear()
        self._crop_edit.hide()
        self.image_label.exit_crop_mode()
        self.btn_ocr_crop.setChecked(False)
        self.btn_ocr_crop.setStyleSheet("")
        self._crop_confirm_bar.hide()

    def _on_crop_confirmed(self, rect: QRect):
        """使用者框選完成，啟動背景 OCR"""
        if rect.width() < 4 or rect.height() < 4:
            return

        # 根據圖片路徑決定要跑哪些語系
        needed_langs   = self._get_langs_for_path(self.current_preview_path)
        shared_engines = getattr(self.parent().engine, "shared_ocr_engines", {})
        use_gpu        = bool(self.parent().config.get("use_gpu_ocr", False))

        # 取得原圖尺寸
        orig_w = self.image_label.original_size.width()
        orig_h = self.image_label.original_size.height()

        self._crop_items = []
        self._last_crop_rect_px = rect  # 儲存原始像素 rect 供手動輸入使用
        self._crop_status_lbl.setText(f"載入引擎並辨識中… ({', '.join(needed_langs)})")
        self._btn_save_crop.setEnabled(False)
        self._reposition_confirm_bar()
        self._crop_confirm_bar.show()
        self._crop_confirm_bar.raise_()

        if self._crop_worker:
            self._crop_worker.is_cancelled = True

        # CropOCRWorker is defined in Blur-main.py (to be moved to core/workers.py)
        from __main__ import CropOCRWorker
        self._crop_worker = CropOCRWorker(
            self.current_preview_path, rect,
            shared_engines, needed_langs, use_gpu,
            orig_w, orig_h
        )
        self._crop_worker.signals.result.connect(self._on_crop_ocr_ready)
        self._crop_worker.signals.error.connect(self._on_crop_ocr_error)
        QThreadPool.globalInstance().start(self._crop_worker)

    def _get_langs_for_path(self, image_path: str) -> list:
        """根據圖片路徑尋找 config source_folders 中最匹配資料夾的語系，找不到 fallback ['ch']"""
        try:
            config_folders = self.parent().config.get("source_folders") or []
            norm_img = os.path.normpath(image_path)
            best_folder, best_langs = "", []
            for f_conf in config_folders:
                folder = os.path.normpath(f_conf.get("path", ""))
                langs  = f_conf.get("enabled_langs") or []
                if norm_img.startswith(folder) and len(folder) > len(best_folder):
                    best_folder = folder
                    best_langs  = langs
            return best_langs if best_langs else ["ch"]
        except Exception:
            return ["ch"]


    def _on_crop_ocr_ready(self, items: list):
        self._crop_items = items
        self.image_label.set_crop_items(items)
        if items:
            texts = [i["text"] for i in items]
            self._crop_status_lbl.setText(f"辨識到 {len(items)} 個文字區塊（可編輯）")
            self._crop_edit.setText(" ".join(texts))
            self._btn_save_crop.setEnabled(True)
        else:
            self._crop_status_lbl.setText("未辨識到文字（可手動輸入後存入）")
            self._crop_edit.setText("")
            self._btn_save_crop.setEnabled(False)  # 等待輸入後才啟用
        self._crop_edit.show()
        self._crop_edit.setFocus()
        self._reposition_confirm_bar()

    def _on_crop_edit_changed(self, text: str):
        """文字欄內容改變時：依照目前模式決定是否啟用儲存按鈕"""
        if self._edit_mode_item is not None:
            # 編輯模式：有文字就可儲存
            self._btn_save_crop.setEnabled(bool(text.strip()))
        elif not self._crop_items:
            # 新增模式（無 OCR 結果）：手動輸入才啟用
            self._btn_save_crop.setEnabled(bool(text.strip()))

    def _on_crop_ocr_error(self, msg: str):
        self._crop_status_lbl.setText(f"OCR 錯誤：{msg}")
        self._btn_save_crop.setEnabled(False)

    def _save_crop_to_db(self):
        # 編輯模式：走替換流程
        if self._edit_mode_item is not None:
            self._save_edited_box()
            return
        if not self.current_preview_path:
            return
        edited_text = self._crop_edit.text().strip()
        if not edited_text and not self._crop_items:
            return

        # 決定要儲存的 items：以編輯欄文字為準
        original_texts = " ".join(i["text"] for i in self._crop_items) if self._crop_items else ""
        if edited_text and edited_text != original_texts:
            # 使用者修改過，或手動輸入（用框選的矩形作為 box）
            r = self._last_crop_rect_px
            if r:
                box = [[r.left(), r.top()], [r.right(), r.top()],
                       [r.right(), r.bottom()], [r.left(), r.bottom()]]
            elif self._crop_items:
                box = self._crop_items[0]["box"]
            else:
                return
            lang = self._crop_items[0]["lang"] if self._crop_items else \
                   self._get_langs_for_path(self.current_preview_path)[0]
            save_items = [{
                "box":     box,
                "lang":    lang,
                "text":    edited_text,
                "conf":    1.0,
                "results": [{"lang": lang, "text": edited_text, "conf": 1.0}],
            }]
        else:
            # 文字未修改，儲存原始 OCR 結果
            save_items = self._crop_items

        if not save_items:
            return

        engine = self.parent().engine
        ok = engine.upsert_crop_ocr(self.current_preview_path, save_items)
        if ok:
            self._reload_ocr_data()  # 更新 Shift 紅框
            self._cancel_crop()      # 關閉框選模式與確認列
        else:
            self._crop_status_lbl.setText("寫入失敗，請確認圖片已建立索引")

    # ── OCR 框點擊互動 ─────────────────────────────────────────
    def _on_box_left_clicked(self, idx: int):
        """左鍵點擊 OCR 框：開啟編輯確認列"""
        if idx < 0 or idx >= len(self.image_label.ocr_data):
            return
        item = self.image_label.ocr_data[idx]
        self._edit_mode_item = item
        # 組合所有語系文字
        combined = " ".join(r.get("text", "") for r in item.get("results", []))
        self._crop_status_lbl.setText("編輯 OCR 文字（完成後點擊儲存）")
        self._crop_edit.setText(combined)
        self._crop_edit.show()
        self._crop_edit.selectAll()
        self._crop_edit.setFocus()
        self._btn_save_crop.setEnabled(bool(combined.strip()))
        self.floating_tag.hide()   # 編輯模式期間隱藏懸浮標籤，避免重疊
        self._reposition_confirm_bar()
        self._crop_confirm_bar.show()
        self._crop_confirm_bar.raise_()

    def _on_box_right_clicked(self, idx: int, global_pos: QPoint):
        """右鍵點擊 OCR 框：顯示操作選單"""
        if idx < 0 or idx >= len(self.image_label.ocr_data):
            return
        item = self.image_label.ocr_data[idx]
        combined = " ".join(r.get("text", "") for r in item.get("results", []))

        menu = QMenu(self)
        act_copy = menu.addAction("複製文字")
        act_edit = menu.addAction("編輯文字")
        menu.addSeparator()
        act_del  = menu.addAction("刪除此區塊")

        chosen = menu.exec(global_pos)
        if chosen == act_copy:
            QApplication.clipboard().setText(combined)
        elif chosen == act_edit:
            self._on_box_left_clicked(idx)
        elif chosen == act_del:
            self._delete_ocr_box_at(idx)

    def _delete_ocr_box_at(self, idx: int):
        """從 DB 刪除指定的 OCR 框，並重新整合畫面"""
        if idx < 0 or idx >= len(self.image_label.ocr_data):
            return
        item = self.image_label.ocr_data[idx]
        box  = item.get("box")
        if not box:
            return
        engine = self.parent().engine
        for r in item.get("results", []):
            engine.delete_ocr_box(self.current_preview_path, r.get("lang", "unk"), box)
        self._reload_ocr_data()
        self._cancel_crop()   # 清除可能殘留的 _edit_mode_item（避免指向已刪除的框）

    def _save_edited_box(self):
        """以替換方式更新編輯後的文字到 DB"""
        if not self._edit_mode_item or not self.current_preview_path:
            self._cancel_crop()
            return
        new_text = self._crop_edit.text().strip()
        if not new_text:
            self._cancel_crop()
            return
        item = self._edit_mode_item
        box  = item.get("box")
        engine = self.parent().engine
        succeeded = 0
        failed = 0
        for r in item.get("results", []):
            if engine.update_ocr_box_text(
                self.current_preview_path, r.get("lang", "unk"), box, new_text
            ):
                succeeded += 1
            else:
                failed += 1

        # 無論成敗都重新整合畫面，避免 UI 卡死或停留在過期狀態
        self._reload_ocr_data()
        self._cancel_crop()

        # 若有部分或全部語言寫入失敗，短暫顯示提示（不阻塞流程）
        if failed > 0 and succeeded == 0:
            self._crop_status_lbl.setText("更新失敗，請確認圖片已建立索引")
            self._crop_confirm_bar.show()
            QTimer.singleShot(3000, self._crop_confirm_bar.hide)
        elif failed > 0:
            self._crop_status_lbl.setText(f"部分語言更新失敗（{succeeded} 成功 / {failed} 失敗）")
            self._crop_confirm_bar.show()
            QTimer.singleShot(3000, self._crop_confirm_bar.hide)

    def _reload_ocr_data(self):
        """從 DB 重新讀取 OCR 資料並更新 image_label（Shift 紅框即時反映新內容）"""
        try:
            engine = self.parent().engine
            raw = engine.get_ocr_data_by_path(self.current_preview_path)
            # _merge_raw_ocr_shapely is defined in Blur-main.py (to be moved to a utility module)
            from __main__ import _merge_raw_ocr_shapely
            merged = _merge_raw_ocr_shapely(raw)
            lbl = self.image_label
            lbl.set_precomputed_ocr_data(
                merged,
                lbl.original_size.width(),
                lbl.original_size.height(),
                lbl.search_query,
                lbl.is_precise_mode,
            )
        except Exception as e:
            print(f"[PreviewOverlay] reload OCR error: {e}")

    def _reposition_confirm_bar(self):
        """將確認列定位在圖片下緣，寬度自動延伸以完整顯示文字"""
        lbl = self.image_label
        pm  = lbl.pixmap()
        if pm is None or pm.isNull():
            return

        # 水平：同 _reposition_toolbar，直接用 overlay 寬度計算
        # img_cx = (self.width() + pm.width()) / 2 - pm.width() / 2 + pm.width() / 2
        #        = (self.width() + pm.width()) / 2  → image right edge
        # 置中於圖片 = overlay 水平中心
        img_cx = self.width() // 2

        # 垂直：圖片下緣
        lbl_top = lbl.mapTo(self, QPoint(0, 0)).y()
        img_y2  = lbl_top + (lbl.height() + pm.height()) // 2

        bar = self._crop_confirm_bar
        bar.setMinimumWidth(0)
        bar.setMaximumWidth(16777215)
        bar.adjustSize()
        bw = bar.sizeHint().width()           # 只用內容所需寬度
        bw = min(bw, self.width() - 20)       # 不超出 overlay 邊界
        bar.setFixedWidth(bw)
        bar.adjustSize()
        bh = bar.height()
        bx = max(0, img_cx - bw // 2)        # 水平置中於圖片
        if bx + bw > self.width():
            bx = max(0, self.width() - bw)
        by = img_y2 - bh - 6
        bar.move(bx, by)
        bar.raise_()



    def _reposition_toolbar(self):
        """將功能列定位於 image_label 內實際圖片右側，頂部對齊"""
        lbl = self.image_label
        pm  = lbl.pixmap()
        if pm is None or pm.isNull():
            return

        # 水平方向：label 有 Expanding 永遠佔滿 overlay 全寬
        # 因此直接用 overlay 寬度計算，不依賴 lbl.width()/lbl.geometry()
        # 避免 layout 延遲更新導致水平偏移量計算錯誤（尤其直圖問題）
        img_right = (self.width() + pm.width()) // 2

        # 垂直方向：用 mapTo 取得 label 實際 y 位置（y 變動小，不受長寬比影響）
        lbl_top = lbl.mapTo(self, QPoint(0, 0)).y()
        img_y   = lbl_top + (lbl.height() - pm.height()) // 2

        tb = self.img_toolbar
        tb.adjustSize()
        tb.move(img_right, img_y)
        tb.raise_()
        tb.show()

    def on_hover_info_changed(self, results, poly, cursor_pos):
        if not results:
            self.floating_tag.hide()
            return

        # 確認列開著時（框選 OCR 或編輯模式），不顯示懸浮標籤
        if self._crop_confirm_bar.isVisible():
            self.floating_tag.hide()
            return

        # 把 OCRLabel 的區域座標，轉換成 PreviewOverlay (全螢幕) 的絕對座標
        mapped_poly = QPolygon([self.image_label.mapTo(self, pt) for pt in poly])
        mapped_cursor = self.image_label.mapTo(self, cursor_pos)

        # 讀取設定檔決定顯示模式
        ui_state = self.parent().config.get("ui_state", {})
        mode = ui_state.get("ocr_tag_mode", "anchored")

        self.floating_tag.update_data(results, mapped_poly, mapped_cursor, mode)

    def set_ocr_visible(self, visible):
        self.image_label.set_draw_boxes(visible)
        if not visible:
            self.floating_tag.hide()
        # 同步工具列按鈕亮起/熄滅狀態
        self.btn_ocr_toggle.setChecked(visible)
        self.btn_ocr_toggle.setStyleSheet(
            "background-color: rgba(100,200,255,60);" if visible else ""
        )

    def _on_toolbar_ocr_toggle(self, checked: bool):
        """工具列 OCR 按鈕：不管當前 Shift 模式，一律切換顯示/隱藏"""
        self.set_ocr_visible(checked)
        # 同步回主視窗的 is_ocr_locked 狀態
        mw = self.parent()
        if hasattr(mw, 'is_ocr_locked'):
            mw.is_ocr_locked = checked

    def show_image(self, result_data, current_query="", is_precise_mode=False, l1_pixmap=None):
        # ImageItem is defined in Blur-main.py (to be moved to a data model module)
        from __main__ import ImageItem
        if isinstance(result_data, ImageItem):
            path = result_data.path
            orig_w, orig_h = result_data.width, result_data.height
        else:
            path = result_data['path']
            screen_size = self.parent().size()
            orig_w = result_data.get('width', int(screen_size.width() * 0.85))
            orig_h = result_data.get('height', int(screen_size.height() * 0.85))

        if not os.path.exists(path): return

        self.current_preview_path = path

        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None

        screen_size = self.parent().size()
        max_w = int(screen_size.width() * 0.85)
        max_h = int(screen_size.height() * 0.85)
        target_size = QSize(max_w, max_h)

        if orig_w == 0 or orig_h == 0:
            orig_w, orig_h = target_size.width(), target_size.height()

        if l1_pixmap and not l1_pixmap.isNull():
            scaled_l1 = l1_pixmap.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_l1)
        else:
                        self.image_label.clear()

        self.floating_tag.hide()   # 切換圖片時立即清除舊圖的 OCR 懸浮標籤
        self.image_label.set_precomputed_ocr_data([], orig_w, orig_h)

        #  將 engine 傳入，讓它在背景自己去撈資料！
        # PreviewLoader is defined in Blur-main.py (to be moved to core/workers.py)
        from __main__ import PreviewLoader
        self.current_preview_worker = PreviewLoader(
            path, target_size, self.parent().engine, current_query, is_precise_mode, orig_w, orig_h
        )
        self.current_preview_worker.signals.result.connect(self.on_highres_ready)
        QThreadPool.globalInstance().start(self.current_preview_worker)

        self.filename_label.setText(os.path.basename(path))
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()
        # 新圖顯示時：保持 is_ocr_locked（toggle）或 _ocr_hold_active（hold）的狀態
        mw = self.parent()
        locked = getattr(mw, 'is_ocr_locked', False) or getattr(mw, '_ocr_hold_active', False)
        self.set_ocr_visible(locked)
        QTimer.singleShot(0, self._reposition_toolbar)

    def on_highres_ready(self, path, img, merged_data, orig_w, orig_h, query, is_precise):
        # 確保是目前正在看這張圖
        if path == self.current_preview_path:

            # 1.  確保在 UI 執行緒內才把 QImage 轉換為 QPixmap，絕對安全！
            if not img.isNull():
                pixmap = QPixmap.fromImage(img)
                self.image_label.setPixmap(pixmap)
                # 延遲到下一個 event loop tick 再定位，避免 layout 延遲結算導致呶得舊初始化時的 y 座標
                QTimer.singleShot(0, self._reposition_toolbar)

            # 2.  就算圖片因為極端原因載入失敗，我們也強制把算好的 OCR 資料塞給畫布
            # 這樣按 Shift 就絕對能看得到紅框！
            self.image_label.set_precomputed_ocr_data(merged_data, orig_w, orig_h, query, is_precise)
            self.image_label.update()

    def show_funnel_card(self, funnel_item):
        """在全螢幕覆蓋層中顯示放大版漏斗統計（按 Space/Esc/點擊空白關閉）"""
        # FunnelCardItem is defined in Blur-main.py (to be moved to a data model module)
        from __main__ import FunnelCardItem
        self.current_preview_path = FunnelCardItem.VIRTUAL_PATH
        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None

        # 用 QPainter 繪製漏斗統計到 QPixmap
        W, H = 520, 380
        pixmap = QPixmap(W, H)
        pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景卡片
        bg = QColor(30, 30, 35, 240)
        card_rect = QRectF(0, 0, W, H)
        card_path = QPainterPath()
        card_path.addRoundedRect(card_rect, 16, 16)
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(card_path)

        accent = QColor("#60cdff")
        text_c = QColor("#e0e0e0")
        muted  = QColor("#888888")

        # 標題
        title_font = QFont("Segoe UI", 14, QFont.Weight.Bold)
        p.setFont(title_font)
        p.setPen(accent)
        p.drawText(QRectF(0, 20, W, 36), Qt.AlignmentFlag.AlignCenter, "📊  Search Funnel")

        # 分隔線
        p.setPen(QPen(muted, 1))
        p.drawLine(40, 62, W - 40, 62)

        rows = funnel_item.rows
        max_num = max(r[0] for r in rows) or 1
        row_h = (H - 80) // len(rows)

        num_font   = QFont("Consolas", 22, QFont.Weight.Bold)
        label_font = QFont("Segoe UI", 11)
        sub_font   = QFont("Segoe UI", 9)

        for i, (num, label) in enumerate(rows):
            ry = 72 + i * row_h
            is_last = (i == len(rows) - 1)
            bar_color = accent if is_last else QColor("#60cdff").lighter(100 + i * 15)
            row_text_c = accent if is_last else text_c

            # 箭頭（第一行不畫）
            if i > 0:
                arr_y = ry - 10
                p.setPen(QPen(muted, 1))
                p.setFont(sub_font)
                p.drawText(QRectF(0, arr_y, W, 14), Qt.AlignmentFlag.AlignCenter, "▼")

            # 進度條底
            bar_rect = QRectF(40, ry + row_h - 14, W - 80, 6)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(60, 60, 70)))
            p.drawRoundedRect(bar_rect, 3, 3)

            # 進度條前景
            fill_w = (num / max_num) * (W - 80)
            if fill_w > 0:
                fill_rect = QRectF(40, ry + row_h - 14, fill_w, 6)
                p.setBrush(QBrush(bar_color))
                p.drawRoundedRect(fill_rect, 3, 3)

            # 數字
            p.setFont(num_font)
            p.setPen(row_text_c)
            p.drawText(QRectF(40, ry, 100, row_h - 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(num))

            # 標籤
            p.setFont(label_font)
            p.setPen(muted if not is_last else accent)
            p.drawText(QRectF(150, ry, W - 190, row_h - 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)

        p.end()

        self.image_label.setPixmap(pixmap)
        self.image_label.set_precomputed_ocr_data([], 0, 0)
        self.filename_label.setText("Search Funnel Stats")
        self.ocr_hint.hide()
        self.img_toolbar.hide()   # 漏斗卡片不顯示功能列
        self.resize(self.parent().size())
        self.show()
        self.raise_()
        self.setFocus()

    def hideEvent(self, event):
        if self.current_preview_worker:
            self.current_preview_worker.is_cancelled = True
            self.current_preview_worker = None
        # 確保 OCR 提示在漏斗卡片預覽關閉後復原顯示
        if hasattr(self, 'ocr_hint'):
            self.ocr_hint.show()
        if hasattr(self, 'img_toolbar'):
            self.img_toolbar.hide()
        if hasattr(self, '_crop_confirm_bar'):
            self._cancel_crop()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.image_label._crop_mode:
                self._cancel_crop()   # Esc 先退出框選模式
                return
            self.hide()
        elif event.key() == Qt.Key.Key_Space:
            self.hide()
        elif event.key() == Qt.Key.Key_Shift:
            # 直接呼叫 ActionHandler，讓 Shift 行為跟主視窗完全一致
            mw = self.parent()
            if hasattr(mw, 'action_handler'):
                cfg = mw.action_handler.get_config()
                mw.action_handler.handle_shift_press(cfg["ocr_mode"])
            event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Shift:
            mw = self.parent()
            if hasattr(mw, 'action_handler'):
                cfg = mw.action_handler.get_config()
                mw.action_handler.handle_shift_release(cfg["ocr_mode"])
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        # 框選模式中，所有 overlay 點擊不關閉預覽（讓 OCRLabel 自己處理）
        if self.image_label._crop_mode:
            return
        # 點擊圖片、功能列、確認列以外的區域才關閉
        pos = event.position().toPoint()
        if (not self.image_label.geometry().contains(pos)
                and not self.img_toolbar.geometry().contains(pos)
                and not self._crop_confirm_bar.geometry().contains(pos)):
            self.hide()

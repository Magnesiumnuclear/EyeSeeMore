import os
from PyQt6.QtCore import (Qt, pyqtSignal, QObject, QRunnable, QThreadPool,
                           QSize, QTimer, QEvent)
from PyQt6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QListWidget, QListWidgetItem, QAbstractItemView,
                              QMenu, QLineEdit)
from PyQt6.QtGui import QIcon, QPixmap, QImageReader, QAction


# ==========================================
#  [究極升級] 多模態特徵物件與互動式標籤 UI
# ==========================================
class FeatureItem:
    """統一管理圖片與文字的特徵結構"""
    def __init__(self, f_type, data):
        self.type = f_type  # 'image' 或是 'text'
        self.data = data    # 圖片路徑 或是 搜尋字串
        self.vector = None  # 緩存的 1024 維向量 (預熱用)


class TextFeatureWidget(QWidget):
    """直接可在清單內編輯的文字標籤"""
    def __init__(self, feat_item, is_positive, parent_bucket, list_item):
        super().__init__()
        self.feat_item = feat_item
        self.parent_bucket = parent_bucket
        self.list_item = list_item

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(8, 2, 8, 2)

        #  重構魔法：核發身分證與極性，視覺全交給 QSS 接管！
        self.setObjectName("TextFeature")
        self.setProperty("polarity", "positive" if is_positive else "negative")

        self.lbl_icon = QLabel("[T]")
        # 這裡的 styleSheet 也被我們在 QSS 用 QWidget#TextFeature QLabel 統一處理掉了！
        self.layout.addWidget(self.lbl_icon)

        self.edit = QLineEdit(self.feat_item.data)
        self.edit.setPlaceholderText("輸入文字特徵 (Enter確認)...")
        self.edit.editingFinished.connect(self.on_edit_finished)
        self.edit.returnPressed.connect(self.release_all_focus)

        self.edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.edit.customContextMenuRequested.connect(self.on_custom_context_menu)

        #  新增：安裝事件過濾器來捕捉 ESC 鍵
        self.edit.installEventFilter(self)

        self.layout.addWidget(self.edit, stretch=1)

    #  新增：專屬的事件過濾器
    def eventFilter(self, obj, event):
        if obj == self.edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                # 完美的 UX：按下 ESC 時，不但取消焦點，還要「還原」為原本的文字
                # (如果是剛點出來的空標籤，還原後會是 ""，失去焦點時就會自動被銷毀！)
                self.edit.setText(self.feat_item.data)
                self.release_all_focus()
                return True # 成功攔截事件
        return super().eventFilter(obj, event)

    def release_all_focus(self):
        """徹底解放焦點：連同外層的清單選取狀態一起清除"""
        self.edit.clearFocus()
        self.parent_bucket.list_widget.clearSelection()
        self.parent_bucket.list_widget.clearFocus()

    def on_custom_context_menu(self, pos):
        if self.edit.hasFocus():
            menu = self.edit.createStandardContextMenu()
            menu.exec(self.edit.mapToGlobal(pos))
        else:
            global_pos = self.edit.mapToGlobal(pos)
            list_pos = self.parent_bucket.list_widget.mapFromGlobal(global_pos)
            self.parent_bucket.show_context_menu(list_pos)

    def on_edit_finished(self):
        new_text = self.edit.text().strip()
        if new_text:
            if self.feat_item.data != new_text:
                self.feat_item.data = new_text
                self.feat_item.vector = None
                self.parent_bucket.preheat_text_vector(self.feat_item)
                self.parent_bucket.files_changed.emit()
        else:
            self.parent_bucket.delete_item_by_widget(self.list_item)


class ThumbnailSignals(QObject):
    finished = pyqtSignal(QListWidgetItem, QIcon)


class ThumbnailWorker(QRunnable):
    def __init__(self, item, path, size=QSize(64, 64)):
        super().__init__(); self.item = item; self.path = path; self.size = size; self.signals = ThumbnailSignals()
    def run(self):
        try:
            reader = QImageReader(self.path)
            raw_sz = reader.size()  # RAW 尺寸（EXIF 旋轉前）
            reader.setAutoTransform(True)
            if raw_sz.isValid():
                reader.setScaledSize(raw_sz.scaled(self.size, Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    if img.width() > self.size.width() or img.height() > self.size.height():
                        img = img.scaled(self.size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.signals.finished.emit(self.item, QIcon(QPixmap.fromImage(img)))
        except: pass


class FeatureBucketWidget(QFrame):
    files_changed = pyqtSignal()
    text_dropped = pyqtSignal(str)

    # 🌟 拔除 idle_color 與 active_color 參數
    def __init__(self, title, is_positive, main_window, parent=None):
        super().__init__(parent)
        self.title = title
        self.is_positive = is_positive
        self.main_window = main_window

        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus) #  拔除系統焦點，消滅外圍方形虛線
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(2, 2, 2, 2)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("BucketListWidget")
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setIconSize(QSize(56, 56)); self.list_widget.setSpacing(4)
        #  加上終極 outline: none 宣告，連 item 內部的虛線一起殺掉

        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)

        # 綁定事件攔截器
        self.list_widget.viewport().installEventFilter(self)

        #  重構魔法：核發身分證與預設極性
        self.setObjectName("FeatureBucket")
        self.setProperty("polarity", "positive" if is_positive else "negative")

        self.placeholder = QLabel(f"拖曳圖片、文字或「點擊此處」輸入...\n({title})", self)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setObjectName("BucketPlaceholder") # 發放專屬身分證
        self.placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.layout.addWidget(self.list_widget)
        self.update_visual_state(False)

    def eventFilter(self, source, event):
        if source == self.list_widget.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                item = self.list_widget.itemAt(event.pos())
                if not item:
                    self.spawn_inline_editor()
                    return True #  攔截事件，防止失焦
        return super().eventFilter(source, event)

    def mousePressEvent(self, event):
        """ 終極防呆：就算點擊在清單邊緣 2px 的縫隙，一樣能觸發輸入"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.spawn_inline_editor()
        super().mousePressEvent(event)

    def spawn_inline_editor(self):
        feat = FeatureItem('text', "")
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 60))
        item.setData(Qt.ItemDataRole.UserRole, feat)
        self.list_widget.addItem(item)

        widget = TextFeatureWidget(feat, self.is_positive, self, item)
        self.list_widget.setItemWidget(item, widget)
        self.update_visual_state()

        #  延遲 10 毫秒奪取焦點，確保 Qt 渲染完成後游標能順利閃爍
        QTimer.singleShot(10, widget.edit.setFocus)

    def update_visual_state(self, is_hover=False):
        has_items = self.list_widget.count() > 0
        self.placeholder.setVisible(not has_items)
        self.list_widget.setVisible(True)

        #  重構魔法：只改變狀態屬性，讓 Qt 自動去 QSS 找對應的衣服穿！
        self.setProperty("drag_hover", "true" if is_hover else "false")

        # 強制 Qt 重新整理這件元件的樣式
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event):
        super().resizeEvent(event); self.placeholder.setGeometry(self.rect())

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction(); self.update_visual_state(True)

    def dragLeaveEvent(self, event): self.update_visual_state(False)

    def dropEvent(self, event):
        self.update_visual_state(False)
        added_new = False
        if event.mimeData().hasUrls():
            current_paths = [f.data for f in self.get_features() if f.type == 'image']
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = os.path.normpath(url.toLocalFile())
                    if path not in current_paths:
                        self.add_image_item(path); added_new = True
        elif event.mimeData().hasText():
            text = event.mimeData().text().strip()
            if text:
                self.add_text_item(text)
                self.text_dropped.emit(text)
                added_new = True
        if added_new: self.files_changed.emit()

    def add_image_item(self, path):
        feat = FeatureItem('image', path)
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, feat)
        self.list_widget.addItem(item)
        worker = ThumbnailWorker(item, path)
        worker.signals.finished.connect(self._on_thumbnail_ready)
        QThreadPool.globalInstance().start(worker)
        self.update_visual_state()

    def add_text_item(self, text):
        feat = FeatureItem('text', text)
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 36))
        item.setData(Qt.ItemDataRole.UserRole, feat)
        self.list_widget.addItem(item)
        widget = TextFeatureWidget(feat, self.is_positive, self, item)
        self.list_widget.setItemWidget(item, widget)
        self.preheat_text_vector(feat)
        self.update_visual_state()

    def preheat_text_vector(self, feat):
        if not hasattr(self, 'main_window') or not self.main_window.engine: return
        engine = self.main_window.engine
        class VectorWorker(QRunnable):
            def run(self):
                try: feat.vector = engine.get_text_vector(feat.data)
                except: pass
        QThreadPool.globalInstance().start(VectorWorker())

    def _on_thumbnail_ready(self, item, icon):
        if item.listWidget() is not None: item.setIcon(icon)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete: self.delete_selected()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_A: self.list_widget.selectAll()
        else: super().keyPressEvent(event)

    def show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        menu = QMenu(self)
        if item:
            action_delete = QAction("🗑️ 刪除 (Delete)", self)
            action_delete.triggered.connect(self.delete_selected)
            menu.addAction(action_delete); menu.addSeparator()
        action_clear = QAction("🚫 清除選擇 (Clear All)", self)
        action_clear.triggered.connect(self.clear_all)
        menu.addAction(action_clear); menu.exec(self.list_widget.mapToGlobal(pos))

    def clear_all(self):
        self.list_widget.clear(); self.update_visual_state(); self.files_changed.emit()

    def get_features(self):
        return [self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_widget.count())]

    # ==========================================
    #  徹底銷毀 UI 元件的刪除邏輯
    # ==========================================
    def delete_item_by_widget(self, list_item):
        """清除沒有輸入文字的幽靈框框，或清空現有文字的標籤"""
        row = self.list_widget.row(list_item)
        if row >= 0:
            #  關鍵修復：必須在 takeItem 「之前」先把 Widget 抓出來！
            # 否則脫離清單後，系統就再也認不得這個 UI 了
            widget = self.list_widget.itemWidget(list_item)

            # 將資料從清單中拔除
            self.list_widget.takeItem(row)

            # 強制從記憶體中把剛剛抓到的 UI 銷毀！
            if widget:
                widget.deleteLater()

            self.update_visual_state()
            self.files_changed.emit()

    def delete_selected(self):
        """使用者按 Delete 鍵或右鍵刪除時的邏輯"""
        for item in self.list_widget.selectedItems():
            #  同樣的防呆：先抓 UI，再拔資料，最後銷毀
            widget = self.list_widget.itemWidget(item)
            row = self.list_widget.row(item)

            self.list_widget.takeItem(row)

            if widget:
                widget.deleteLater()

        self.update_visual_state()
        self.files_changed.emit()

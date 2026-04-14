"""
ImageActionManager  –  單張影像的動作執行器
=============================================
從 MainWindow 抽離的職責：
  • 開啟檔案（os.startfile）
  • 複製影像像素到剪貼簿
  • 複製路徑文字到剪貼簿
  • 重新命名（engine.rename_file 包裹 + UI 對話框）
  • 屬性資訊面板（QMessageBox）

設計原則：
  • engine 延遲注入（load_engine 後呼叫 img_actions.engine = self.engine）
  • toast_fn callback 讓 MainWindow 的 status bar 保持控制權
  • parent_widget 傳入以作為 QDialog / QMessageBox 的父窗口
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (
    QApplication, QInputDialog, QMessageBox, QWidget,
)


class ImageActionManager:
    """封裝對單張影像的操作，供 MainWindow 右鍵選單委派呼叫。"""

    def __init__(
        self,
        parent_widget: QWidget,
        *,
        toast_fn: Optional[Callable[[str], None]] = None,
    ):
        self._parent = parent_widget
        self._toast_fn = toast_fn or (lambda _msg: None)
        self.engine = None  # 延遲注入

    # ------------------------------------------------------------------
    #  開啟檔案
    # ------------------------------------------------------------------
    def open_file(self, path: str) -> None:
        """以系統預設程式開啟圖片。"""
        try:
            os.startfile(path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  複製影像像素到剪貼簿
    # ------------------------------------------------------------------
    def copy_image(self, path: str) -> None:
        try:
            img = QImage(path)
            if not img.isNull():
                QApplication.clipboard().setImage(img)
                self._toast_fn("已複製影像到剪貼簿")
        except Exception as e:
            print(f"Copy image error: {e}")

    # ------------------------------------------------------------------
    #  複製路徑文字到剪貼簿
    # ------------------------------------------------------------------
    @staticmethod
    def copy_path(path: str) -> None:
        QApplication.clipboard().setText(path)

    # ------------------------------------------------------------------
    #  重新命名
    # ------------------------------------------------------------------
    def rename(self, index, item) -> None:
        """彈出輸入框，成功後更新 model 索引。

        Parameters
        ----------
        index : QModelIndex
        item  : ImageItem  (帶 .filename / .path)
        """
        new_name, ok = QInputDialog.getText(
            self._parent, "Rename", "New name:", text=item.filename,
        )
        if not (ok and new_name and new_name != item.filename):
            return

        if self.engine is None:
            QMessageBox.warning(self._parent, "Error", "Engine not ready.")
            return

        success, result = self.engine.rename_file(item.path, new_name)
        if success:
            item.filename = new_name
            item.path = result
            model = index.model()
            if model is not None:
                model.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        else:
            QMessageBox.warning(self._parent, "Error", f"Rename failed: {result}")

    # ------------------------------------------------------------------
    #  屬性資訊
    # ------------------------------------------------------------------
    def show_properties(self, item) -> None:
        date_str = "Unknown"
        if item.mtime > 0:
            date_str = datetime.fromtimestamp(item.mtime).strftime('%Y-%m-%d %H:%M')
        msg = (
            f"<h3>{item.filename}</h3><hr>"
            f"<b>Path:</b> {item.path}<br>"
            f"<b>Score:</b> {item.score:.4f}<br>"
            f"<b>Date:</b> {date_str}"
        )
        QMessageBox.information(self._parent, "Properties", msg)

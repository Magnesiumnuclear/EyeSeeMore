"""TransparentDragListWidget — drag-ghost half-opacity list widget."""
from PyQt6.QtWidgets import QListWidget
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QRegion, QCursor
from PyQt6.QtCore import Qt, QPoint


class TransparentDragListWidget(QListWidget):
    """Custom QListWidget that renders a semi-transparent ghost during drag."""

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return super().startDrag(supportedActions)

        drag = QDrag(self)
        mimeData = self.model().mimeData(self.selectedIndexes())
        drag.setMimeData(mimeData)

        rect = self.visualItemRect(item)
        pixmap = QPixmap(rect.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap, QPoint(), QRegion(rect))

        alpha_pixmap = QPixmap(pixmap.size())
        alpha_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(alpha_pixmap)
        painter.setOpacity(0.5)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()

        drag.setPixmap(alpha_pixmap)
        mouse_pos = self.viewport().mapFromGlobal(QCursor.pos())
        hotspot = mouse_pos - rect.topLeft()
        drag.setHotSpot(hotspot)
        drag.exec(supportedActions, Qt.DropAction.MoveAction)

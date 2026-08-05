"""Picker for the slice of media that feeds a surface.

Shows the media with a draggable rectangle over it. Dragging inside moves the
region, dragging a corner resizes it - the same vocabulary as the canvas, so
there is nothing new to learn.

Numbers live next to it in the property panel; this widget is the part you can
aim by eye.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from pm.media.image_cache import get_qimage
from pm.model.media import SourceRect

_ACCENT = QColor(0, 212, 170)
_DIM = QColor(120, 120, 128)


class SourceRegionPicker(QWidget):
    """Drag a rectangle over the media to choose the region it contributes."""

    region_changed = Signal(object)   # SourceRect, live during a drag
    region_committed = Signal(object)  # SourceRect, once on release

    HANDLE_PX = 9.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path = ""
        self._region = SourceRect()
        self._drag: Optional[str] = None
        self._grab_offset = QPointF()
        self.setMinimumHeight(110)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def set_media(self, path: str, region: SourceRect) -> None:
        self._path = path or ""
        self._region = region.normalised()
        self.update()

    def region(self) -> SourceRect:
        return self._region

    # --- geometry --------------------------------------------------------

    def _frame(self) -> QRectF:
        """Where the media is drawn, letterboxed into the widget."""
        image = get_qimage(self._path)
        area = QRectF(4, 4, max(self.width() - 8, 1), max(self.height() - 8, 1))
        if image is None or image.width() == 0 or image.height() == 0:
            return area

        scale = min(area.width() / image.width(), area.height() / image.height())
        w, h = image.width() * scale, image.height() * scale
        return QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)

    def _region_rect(self) -> QRectF:
        frame = self._frame()
        r = self._region
        return QRectF(
            frame.x() + r.u0 * frame.width(),
            frame.y() + r.v0 * frame.height(),
            r.width * frame.width(),
            r.height * frame.height(),
        )

    def _to_region(self, pos: QPointF) -> QPointF:
        frame = self._frame()
        if frame.width() <= 0 or frame.height() <= 0:
            return QPointF(0.0, 0.0)
        return QPointF(
            (pos.x() - frame.x()) / frame.width(),
            (pos.y() - frame.y()) / frame.height(),
        )

    def _corner_at(self, pos: QPointF) -> Optional[str]:
        rect = self._region_rect()
        corners = {
            "tl": rect.topLeft(),
            "tr": rect.topRight(),
            "bl": rect.bottomLeft(),
            "br": rect.bottomRight(),
        }
        for name, point in corners.items():
            if (pos - point).manhattanLength() <= self.HANDLE_PX * 1.6:
                return name
        return None

    # --- interaction -----------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position()
        corner = self._corner_at(pos)
        if corner:
            self._drag = corner
        elif self._region_rect().contains(pos):
            self._drag = "move"
            self._grab_offset = pos - self._region_rect().topLeft()
        else:
            # Clicking outside starts a fresh region from that corner.
            self._drag = "br"
            here = self._to_region(pos)
            self._region = SourceRect(here.x(), here.y(), here.x(), here.y())
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._drag:
            corner = self._corner_at(event.position())
            self.setCursor(Qt.SizeFDiagCursor if corner else Qt.CrossCursor)
            return

        here = self._to_region(event.position())
        r = self._region
        if self._drag == "move":
            top_left = self._to_region(event.position() - self._grab_offset)
            width, height = r.width, r.height
            # Slide, never resize: the region keeps its size against the edges.
            u0 = min(max(top_left.x(), 0.0), 1.0 - width)
            v0 = min(max(top_left.y(), 0.0), 1.0 - height)
            self._region = SourceRect(u0, v0, u0 + width, v0 + height)
        elif self._drag == "tl":
            self._region = SourceRect(here.x(), here.y(), r.u1, r.v1)
        elif self._drag == "tr":
            self._region = SourceRect(r.u0, here.y(), here.x(), r.v1)
        elif self._drag == "bl":
            self._region = SourceRect(here.x(), r.v0, r.u1, here.y())
        else:  # br
            self._region = SourceRect(r.u0, r.v0, here.x(), here.y())

        self._region = self._region.normalised()
        self.update()
        self.region_changed.emit(self._region)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if not self._drag:
            return
        self._drag = None
        self.region_committed.emit(self._region)
        event.accept()

    # --- painting --------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(18, 18, 22))

        frame = self._frame()
        image = get_qimage(self._path)
        if image is None:
            painter.setPen(QPen(_DIM, 1))
            painter.drawText(self.rect(), Qt.AlignCenter, "No image preview")
            painter.end()
            return

        painter.drawImage(frame, image)

        # Everything outside the region dimmed, so the selection reads at a
        # glance instead of having to trace an outline.
        rect = self._region_rect()
        shade = QColor(8, 8, 12, 150)
        painter.fillRect(QRectF(frame.x(), frame.y(), frame.width(), rect.y() - frame.y()), shade)
        painter.fillRect(
            QRectF(frame.x(), rect.bottom(), frame.width(), frame.bottom() - rect.bottom()), shade
        )
        painter.fillRect(QRectF(frame.x(), rect.y(), rect.x() - frame.x(), rect.height()), shade)
        painter.fillRect(
            QRectF(rect.right(), rect.y(), frame.right() - rect.right(), rect.height()), shade
        )

        painter.setPen(QPen(_ACCENT, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        painter.setBrush(QBrush(_ACCENT))
        painter.setPen(QPen(QColor(0, 90, 72), 1))
        half = self.HANDLE_PX / 2.0
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawRect(QRectF(point.x() - half, point.y() - half, self.HANDLE_PX, self.HANDLE_PX))

        painter.end()

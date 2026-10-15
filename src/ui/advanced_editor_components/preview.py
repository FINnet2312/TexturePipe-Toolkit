"""复杂编辑器的缩放、平移与拖放预览控件。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy


class PannableScrollArea(QScrollArea):
    """右键平移、滚轮缩放、双击恢复 100% 的图片预览。"""

    zoom_changed = Signal(float)

    ZOOM_MIN = 0.01
    ZOOM_MAX = 10.0
    ZOOM_STEP = 1.15

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pan_start = None
        self._zoom = 1.0
        self._base_pixmap: Optional[QPixmap] = None
        self.setWidgetResizable(False)
        self.setMouseTracking(True)
        self._lbl = QLabel()
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("background:#222;")
        self._lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setWidget(self._lbl)

    def set_base_pixmap(self, pixmap: QPixmap) -> None:
        self._base_pixmap = pixmap
        self._apply_zoom()

    def base_pixmap(self) -> Optional[QPixmap]:
        return self._base_pixmap

    def set_zoom(self, zoom: float) -> None:
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if abs(zoom - self._zoom) < 1e-6:
            return
        self._zoom = zoom
        self._apply_zoom()
        self.zoom_changed.emit(self._zoom)

    def zoom(self) -> float:
        return self._zoom

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def fit_to_viewport(self) -> None:
        if self._base_pixmap is None or self._base_pixmap.isNull():
            return
        viewport_width = max(1, self.viewport().width())
        viewport_height = max(1, self.viewport().height())
        image_width = self._base_pixmap.width()
        image_height = self._base_pixmap.height()
        if image_width <= 0 or image_height <= 0:
            return
        self.set_zoom(min(
            viewport_width / image_width,
            viewport_height / image_height,
        ))

    def _apply_zoom(self) -> None:
        if self._base_pixmap is None or self._base_pixmap.isNull():
            return
        width = max(1, int(self._base_pixmap.width() * self._zoom))
        height = max(1, int(self._base_pixmap.height() * self._zoom))
        scaled = self._base_pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._lbl.setPixmap(scaled)
        self._lbl.resize(width, height)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        factor = self.ZOOM_STEP if delta > 0 else 1.0 / self.ZOOM_STEP
        old_zoom = self._zoom
        new_zoom = max(
            self.ZOOM_MIN,
            min(self.ZOOM_MAX, old_zoom * factor),
        )
        if abs(new_zoom - old_zoom) < 1e-6:
            event.accept()
            return

        horizontal = self.horizontalScrollBar()
        vertical = self.verticalScrollBar()
        mouse_in_label = self._lbl.mapFrom(
            self.viewport(), event.position().toPoint(),
        )
        fraction_x = mouse_in_label.x() / (self._lbl.width() or 1)
        fraction_y = mouse_in_label.y() / (self._lbl.height() or 1)
        self._zoom = new_zoom
        self._apply_zoom()
        horizontal.setValue(int(
            fraction_x * self._lbl.width() - event.position().x(),
        ))
        vertical.setValue(int(
            fraction_y * self._lbl.height() - event.position().y(),
        ))
        self.zoom_changed.emit(self._zoom)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_start = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._pan_start is not None and (
            event.buttons() & Qt.MouseButton.RightButton
        ):
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            horizontal = self.horizontalScrollBar()
            vertical = self.verticalScrollBar()
            horizontal.setValue(horizontal.value() - delta.x())
            vertical.setValue(vertical.value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_start = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        event.accept()


class ClickableDropFrame(QFrame):
    """支持文件拖入和左键点击回调的 drop zone。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._on_click = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._on_click:
            self._on_click()
            event.accept()
            return
        super().mousePressEvent(event)


__all__ = ["ClickableDropFrame", "PannableScrollArea"]

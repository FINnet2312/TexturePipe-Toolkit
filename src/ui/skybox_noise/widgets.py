"""通用 UI 控件:可缩放预览 ImageLabel(带细节放大镜) / ParamSlider。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class ImageLabel(QWidget):
    """可缩放/平移的图像视图。

    - 初始自适应(Fit,只缩不放)
    - 滚轮缩放(0.05x ~ 16x)
    - 右键拖动平移
    - 双击复位到 Fit
    - 细节放大镜:鼠标悬停时,右上角固定小窗显示该处 4x 放大
    交互方式与主程序的「大图查看器」保持一致。
    """

    ZOOM_MIN = 0.05
    ZOOM_MAX = 16.0
    ZOOM_STEP = 1.15

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._pixmap: QPixmap | None = None
        self._zoom = 1.0
        self._need_fit = False
        self._pan_start: QPoint | None = None
        self.setMinimumSize(400, 200)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 承载图像的 QLabel,尺寸跟随缩放
        self._lbl = QLabel(f"{title}\n(无图像)")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed,
        )
        self._lbl.setStyleSheet(
            "QLabel { background:#1e1e1e; color:#888; }"
        )
        # 滚动区
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._lbl)
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setStyleSheet(
            "QScrollArea { background:#1e1e1e; border:1px solid #444; }",
        )
        root.addWidget(self._scroll, 1)
        # 缩放比例显示
        self._zoom_lbl = QLabel("")
        self._zoom_lbl.setStyleSheet("color:#888; padding:2px 6px;")
        self._zoom_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        root.addWidget(self._zoom_lbl)

        # 细节放大镜(右上角固定小窗,悬停跟随鼠标)
        self._loupe_size = 160
        self._loupe_zoom = 4.0
        self._loupe = QLabel(self)
        self._loupe.setFixedSize(self._loupe_size, self._loupe_size)
        self._loupe.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loupe.setStyleSheet(
            "QLabel { background:#141414; border:1px solid #0a84ff; color:#888; }",
        )
        self._loupe.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._loupe.hide()
        self._lbl.setMouseTracking(True)
        self._lbl.installEventFilter(self)

    # -- 数据 ----------------------------------------------------------
    def set_ndarray(self, arr, title: str | None = None) -> None:
        """换图并复位为 Fit。arr: HxW 或 HxWx3,范围 [0,1]。"""
        if title:
            self._title = title
        if arr is None:
            self._pixmap = None
            self._lbl.setText(f"{self._title}\n(无图像)")
            self._lbl.setPixmap(QPixmap())
            self._zoom_lbl.setText("")
            return
        u8 = np_clip01_to_uint8(arr)
        if u8.ndim == 2:
            h, w = u8.shape
            qimg = QImage(u8.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            h, w = u8.shape[:2]
            rgb = np.ascontiguousarray(u8[..., :3])
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimg)
        self._need_fit = True
        self._apply_zoom()
        self._fit_if_ready()

    # -- 缩放 ----------------------------------------------------------
    def _apply_zoom(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        w, h = self._pixmap.width(), self._pixmap.height()
        new_w = max(1, int(w * self._zoom))
        new_h = max(1, int(h * self._zoom))
        scaled = self._pixmap.scaled(
            new_w, new_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._lbl.setPixmap(scaled)
        self._lbl.resize(new_w, new_h)
        self._zoom_lbl.setText(
            f"{self._zoom * 100:.0f}%  ({w}x{h})   滚轮缩放 / 右键平移 / 双击复位",
        )

    def fit_to_view(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        vw = max(1, self._scroll.viewport().width())
        vh = max(1, self._scroll.viewport().height())
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw <= 0 or ph <= 0:
            return
        self._zoom = min(vw / pw, vh / ph, 1.0)  # 只缩不放
        self._apply_zoom()

    def _fit_if_ready(self) -> None:
        if not self._need_fit:
            return
        if self._scroll.viewport().width() > 10 and self._scroll.viewport().height() > 10:
            self._need_fit = False
            self.fit_to_view()

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self._fit_if_ready()
        self._place_loupe()

    # -- 细节放大镜 ------------------------------------------------------
    def eventFilter(self, obj, ev):  # noqa: N802
        # 防御:Shiboken 可能在析构序列里重建空包装(未跑 __init__),
        # 此时访问 _lbl 会抛 AttributeError 并污染事件派发。直接放行。
        if not hasattr(self, "_lbl"):
            return super().eventFilter(obj, ev)
        if obj is self._lbl:
            t = ev.type()
            if t == QEvent.Type.MouseMove:
                self._update_loupe(ev.position().toPoint())
                return False
            if t == QEvent.Type.Leave:
                self._loupe.hide()
                return False
        return super().eventFilter(obj, ev)

    def _place_loupe(self) -> None:
        self._loupe.move(self.width() - self._loupe_size - 8, 8)

    def _update_loupe(self, lbl_pos: QPoint) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        # 鼠标在缩放后 label 上的位置 → 原图像素坐标
        zoom = max(self._zoom, 1e-6)
        ox = lbl_pos.x() / zoom
        oy = lbl_pos.y() / zoom
        pw, ph = self._pixmap.width(), self._pixmap.height()
        size = max(2, int(self._loupe_size / self._loupe_zoom))
        x0 = int(np.clip(ox - size / 2, 0, pw - size))
        y0 = int(np.clip(oy - size / 2, 0, ph - size))
        src = self._pixmap.copy(QRect(x0, y0, size, size))
        if src.isNull():
            return
        scaled = src.scaled(
            self._loupe_size, self._loupe_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._loupe.setPixmap(scaled)
        self._place_loupe()
        self._loupe.show()

    # -- 交互 ----------------------------------------------------------
    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        if delta == 0:
            return
        factor = self.ZOOM_STEP if delta > 0 else 1.0 / self.ZOOM_STEP
        old = self._zoom
        new = max(self.ZOOM_MIN, min(self.ZOOM_MAX, old * factor))
        if abs(new - old) < 1e-6:
            ev.accept()
            return
        self._zoom = new
        self._apply_zoom()
        ev.accept()

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.RightButton:
            self._pan_start = ev.position().toPoint()
            self._scroll.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent):
        if self._pan_start is not None and (ev.buttons() & Qt.MouseButton.RightButton):
            delta = ev.position().toPoint() - self._pan_start
            self._pan_start = ev.position().toPoint()
            self._scroll.horizontalScrollBar().setValue(
                self._scroll.horizontalScrollBar().value() - delta.x(),
            )
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().value() - delta.y(),
            )
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.RightButton and self._pan_start is not None:
            self._pan_start = None
            self._scroll.viewport().unsetCursor()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._need_fit = True
            self._fit_if_ready()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


def np_clip01_to_uint8(arr):
    import numpy as np
    return (np.clip(arr, 0, 1) * 255).astype("uint8")


class ParamSlider(QWidget):
    """带标签 + 数值显示的滑块。"""

    def __init__(self, label: str, min_v: float, max_v: float, value: float,
                 step: float = 0.01, decimals: int = 3, callback=None,
                 parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLabel
        self.label = QLabel(f"{label}:")
        self.value_label = QLabel(f"{value:.{decimals}f}")
        self.value_label.setMinimumWidth(60)
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(round(min_v / step)))
        self.slider.setMaximum(int(round(max_v / step)))
        self.slider.setValue(int(round(value / step)))
        self.step = step
        self.decimals = decimals
        self.min_v = min_v
        self.max_v = max_v

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)

        self._callback = callback
        self.slider.valueChanged.connect(self._on_slider)

    def _on_slider(self, v: int) -> None:
        val = round(v * self.step, self.decimals)
        val = max(self.min_v, min(self.max_v, val))
        self.value_label.setText(f"{val:.{self.decimals}f}")
        if self._callback:
            self._callback(val)

    def value(self) -> float:
        return round(self.slider.value() * self.step, self.decimals)

    def setValue(self, v: float) -> None:  # noqa: N802
        self.slider.setValue(int(round(v / self.step)))


__all__ = ["ImageLabel", "ParamSlider"]

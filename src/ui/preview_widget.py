"""preview_widget — 通道预览面板。

显示:
- 4 张单通道灰度缩略图(R/G/B/A,按通道标色边)
- 最终打包的 RGBA 缩略图(按当前 OutputSpec.effective_size 取一次)
- "源格式"信息:哪个通道对应哪个 semantic(用 ChannelMap.to_dict 简易展示)
- 点击缩略图 → 弹大图查看器(支持滚轮缩放 + 右键 pan)

输入可为 H×W×4 uint8/uint16/float 数组；显示时生成8-bit预览副本。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.map import ChannelMap
from src.core.pixels import to_display_u8
from src.core.slot import Semantic, SourceType

_PREVIEW_MAX = 256  # 缩略图最大边


def _preview_sample(arr: np.ndarray, max_edge: int = _PREVIEW_MAX) -> np.ndarray:
    """先按步长取代理再转 8-bit，避免为 8K/16K 预览复制整张图。"""
    height, width = arr.shape[:2]
    step = max(1, int(np.ceil(max(height, width) / max_edge)))
    return arr[::step, ::step]


# ---------------------------------------------------------------------------
# 可滚轮缩放 + 右键 pan 的图片查看器(对话框内容)
# ---------------------------------------------------------------------------
class _ZoomableImageView(QWidget):
    """显示一张 numpy 图像,支持滚轮缩放 + 右键拖动 pan。"""

    ZOOM_MIN = 0.05
    ZOOM_MAX = 16.0
    ZOOM_STEP = 1.15

    def __init__(self, arr: np.ndarray, parent=None):
        super().__init__(parent)
        self._arr = arr
        self._zoom: float = 1.0
        self._pan_start: Optional[QPoint] = None
        # 准备 QPixmap
        self._pixmap = self._arr_to_pixmap(arr)
        # 内部 label 承载
        self._lbl = QLabel()
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("background:#222;")
        self._lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # 滚动区
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._lbl)
        self._scroll.setWidgetResizable(False)
        self._scroll.setStyleSheet("QScrollArea { background:#222; }")
        # 装到布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._scroll)
        # 缩放比例显示
        self._zoom_lbl = QLabel()
        self._zoom_lbl.setStyleSheet("color:#888; padding:4px;")
        layout.addWidget(self._zoom_lbl)
        # 初次按 fit 缩放
        self._zoom = 1.0
        self._apply_zoom()

    @staticmethod
    def _arr_to_pixmap(arr: np.ndarray) -> QPixmap:
        arr = to_display_u8(arr)
        if arr.ndim == 2:
            h, w = arr.shape
            data = np.ascontiguousarray(arr)
            qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            h, w = arr.shape[:2]
            if arr.shape[-1] >= 3:
                rgb = np.ascontiguousarray(arr[..., :3])
                qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
            else:
                data = np.ascontiguousarray(arr[..., 0])
                qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
        return QPixmap.fromImage(qimg)

    def _apply_zoom(self):
        if self._pixmap.isNull():
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
            f"缩放: {self._zoom * 100:.0f}%   尺寸: {w}×{h}   "
            f"(滚轮缩放 / 右键 pan / 双击重置)"
        )

    def fit_to_view(self):
        if self._pixmap.isNull():
            return
        vw = max(1, self._scroll.viewport().width())
        vh = max(1, self._scroll.viewport().height())
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw <= 0 or ph <= 0:
            return
        z = min(vw / pw, vh / ph, 1.0)  # 默认 fit,只缩不放
        self._zoom = z
        self._apply_zoom()

    def wheelEvent(self, ev: QWheelEvent):
        delta = ev.angleDelta().y()
        if delta == 0:
            return
        factor = self.ZOOM_STEP if delta > 0 else 1.0 / self.ZOOM_STEP
        old_zoom = self._zoom
        new_zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-6:
            ev.accept()
            return
        self._zoom = new_zoom
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
            hbar = self._scroll.horizontalScrollBar()
            vbar = self._scroll.verticalScrollBar()
            hbar.setValue(hbar.value() - delta.x())
            vbar.setValue(vbar.value() - delta.y())
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
            self._zoom = 1.0
            self._apply_zoom()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


# ---------------------------------------------------------------------------
# 大图查看对话框
# ---------------------------------------------------------------------------
class ImageViewDialog(QDialog):
    """大图查看对话框,用于点击缩略图时弹出。"""

    def __init__(self, arr: np.ndarray, title: str = "查看大图", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        info = QLabel(f"{arr.shape}  dtype={arr.dtype}")
        info.setStyleSheet("color:#888;")
        layout.addWidget(info)
        self._view = _ZoomableImageView(arr)
        layout.addWidget(self._view, 1)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(self.reject)
        btn.accepted.connect(self.accept)
        layout.addWidget(btn)

    def showEvent(self, ev):
        super().showEvent(ev)
        # 延迟到 fit 完整
        self._view.fit_to_view()


# ---------------------------------------------------------------------------
# 单张预览
# ---------------------------------------------------------------------------
class _ChannelPreview(QFrame):
    """单通道(灰度)预览:左边标题,右边缩略图。点击缩略图 = 弹大图。"""

    clicked = Signal(np.ndarray, str)  # (arr, title)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # 缩略图 + 大图数据缓存
        self._arr: Optional[np.ndarray] = None
        self._title: str = title

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 标题(通道名 + semantic)
        self.title_label = QLabel(title)
        self.title_label.setMinimumWidth(80)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label, stretch=0)

        # 缩略图(可点击 → 弹大图)
        self.thumb = QLabel()
        self.thumb.setMinimumSize(120, 120)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(
            "QLabel { background:#222; color:#888; border:1px solid #444; }"
            "QLabel:hover { border:1px solid #0a84ff; }"
        )
        self.thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thumb.setToolTip("点击查看大图(滚轮缩放 / 右键 pan / 双击重置)")
        layout.addWidget(self.thumb, stretch=1)

    def set_title(self, text: str) -> None:
        self._title = text
        self.title_label.setText(text)

    def set_array(self, arr: Optional[np.ndarray]) -> None:
        self._arr = arr
        if arr is None or arr.size == 0:
            self.thumb.setText("empty\n(点击查看)")
            self.thumb.setPixmap(QPixmap())
            return
        sampled = _preview_sample(arr)
        h, w = sampled.shape[:2]
        data = np.ascontiguousarray(to_display_u8(sampled))
        if data.ndim == 2:
            qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            rgb = np.ascontiguousarray(data[..., :3])
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        # 等比缩放
        pix = pix.scaled(
            QSize(_PREVIEW_MAX, _PREVIEW_MAX),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb.setText("")
        self.thumb.setPixmap(pix)

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.MouseButton.LeftButton and self._arr is not None:
            self.clicked.emit(self._arr, self._title)
            ev.accept()
            return
        super().mousePressEvent(ev)


# ---------------------------------------------------------------------------
# 总预览面板
# ---------------------------------------------------------------------------
class PreviewWidget(QGroupBox):
    """预览面板:4 通道灰度 + 最终 RGBA。点击缩略图可看大图。"""

    def __init__(self, parent=None):
        super().__init__("预览", parent)
        self._last_rgba: Optional[np.ndarray] = None
        self._last_map: Optional[ChannelMap] = None
        self._build_ui()
        self._wire_signals()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 4 通道灰度预览(2×2)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.previews: dict[str, _ChannelPreview] = {}
        for idx, name in enumerate(("R", "G", "B", "A")):
            p = _ChannelPreview(f"{name}: —")
            self.previews[name] = p
            p.clicked.connect(self._on_preview_clicked)
            grid.addWidget(p, idx // 2, idx % 2)
        root.addLayout(grid)

        # 最终 RGBA 拼图
        self.rgba_preview = _ChannelPreview("RGBA")
        self.rgba_preview.setMinimumHeight(280)
        self.rgba_preview.clicked.connect(self._on_preview_clicked)
        root.addWidget(self.rgba_preview, stretch=1)

        # 提示
        hint = QLabel("💡 点击任意缩略图可看大图(滚轮缩放 / 右键 pan / 双击重置)")
        hint.setStyleSheet("color:#888;")
        root.addWidget(hint)

    def _wire_signals(self) -> None:
        pass  # _ChannelPreview.clicked → _on_preview_clicked 已在 _build_ui 连

    def _on_preview_clicked(self, arr: np.ndarray, title: str) -> None:
        """用户点击缩略图 → 弹大图查看器。"""
        dlg = ImageViewDialog(arr, title=f"查看 - {title}", parent=self)
        dlg.exec()

    # -- 公开接口 -------------------------------------------------------
    def show_rgba(self, arr: np.ndarray) -> None:
        """外部(ChannelGrid)送来打包好的 H×W×4 数组,刷新预览。"""
        if arr is None:
            return
        self._last_rgba = arr
        # 拆出 4 通道
        for i, name in enumerate(("R", "G", "B", "A")):
            chan = arr[..., i] if arr.ndim == 3 and arr.shape[-1] >= 4 else None
            self.previews[name].set_array(chan)
        # 拼图本身
        self.rgba_preview.set_array(arr)

    def show_map(self, m: ChannelMap) -> None:
        """根据 ChannelMap 自身(更详细地展示每槽的 semantic / 显示名)。"""
        self._last_map = m
        for name, slot in m.slots():
            sem = slot.semantic.value if slot.semantic is not Semantic.EMPTY else "—"
            label = f"{name}: {sem}"
            if slot.display_name:
                label += f"\n({slot.display_name})"
            self.previews[name].set_title(label)

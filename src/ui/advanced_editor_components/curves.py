"""贝塞尔曲线计算与交互控件。"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget


def bezier_lut(points_with_tangents, size: int) -> np.ndarray:
    """将 ``(x, y, tx, ty)`` 控制点插值为指定长度的 LUT。"""
    if len(points_with_tangents) < 2:
        return np.linspace(0, 255, size).astype(np.float32)
    if len(points_with_tangents) == 2:
        xs = np.array([point[0] for point in points_with_tangents], dtype=np.float32)
        ys = np.array([point[1] for point in points_with_tangents], dtype=np.float32)
        return np.interp(np.linspace(0, 255, size), xs, ys).astype(np.float32)

    points = list(points_with_tangents)
    output = np.zeros(size, dtype=np.float32)
    for output_index in range(size):
        query_x = output_index * 255.0 / (size - 1)
        segment = len(points) - 2
        for index in range(len(points) - 1):
            if points[index][0] <= query_x <= points[index + 1][0]:
                segment = index
                break
        x0, y0, _tx0, ty0 = points[segment]
        x1, y1, _tx1, ty1 = points[segment + 1]
        length = x1 - x0
        t = (query_x - x0) / length if length > 0 else 0.0
        t = max(0.0, min(1.0, t))
        inverse = 1.0 - t
        output[output_index] = (
            inverse ** 3 * y0
            + 3.0 * inverse ** 2 * t * (y0 + ty0)
            + 3.0 * inverse * t ** 2 * (y1 - ty1)
            + t ** 3 * y1
        )
    return output


def catmull_rom_lut(points, size: int) -> np.ndarray:
    """旧 API 兼容层：从无切线锚点生成自动切线后计算 LUT。"""
    if len(points) < 2:
        return np.linspace(0, 255, size).astype(np.float32)
    anchors = sorted(
        [(float(point[0]), float(point[1])) for point in points],
        key=lambda point: point[0],
    )
    with_tangents = []
    for index, (x, y) in enumerate(anchors):
        if index < len(anchors) - 1:
            length = anchors[index + 1][0] - x
            tangent_y = (anchors[index + 1][1] - y) / 3.0
        else:
            length = x - anchors[index - 1][0]
            tangent_y = (y - anchors[index - 1][1]) / 3.0
        with_tangents.append((x, y, max(1.0, length / 3.0), tangent_y))
    return bezier_lut(with_tangents, size)


class CurveWidget(QWidget):
    """每个锚点带对称切线手柄的贝塞尔曲线编辑器。"""

    lut_changed = Signal()

    POINT_RADIUS = 5
    HANDLE_RADIUS = 4
    HIT_RADIUS = 8
    ADD_HIT_DIST = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[tuple[float, float, float, float]] = [
            (0.0, 0.0, 85.0, 0.0),
            (255.0, 255.0, 85.0, 0.0),
        ]
        self._drag_target: Optional[tuple[str, int]] = None
        self._lut_cache: Optional[np.ndarray] = None
        self._lut_dirty = True
        self.setMouseTracking(True)
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def points(self) -> list[tuple[float, float]]:
        return [(point[0], point[1]) for point in self._points]

    def points_with_tangents(self) -> list[tuple[float, float, float, float]]:
        return list(self._points)

    def set_points(self, points: list[tuple[float, float]]) -> None:
        anchors = sorted(
            [(float(x), float(y)) for x, y in points],
            key=lambda point: point[0],
        )
        if not anchors:
            anchors = [(0.0, 0.0), (255.0, 255.0)]
        if anchors[0][0] > 0:
            anchors.insert(0, (0.0, anchors[0][1]))
        if anchors[-1][0] < 255:
            anchors.append((255.0, anchors[-1][1]))
        merged = [anchors[0]]
        for point in anchors[1:]:
            if point[0] - merged[-1][0] >= 1.0:
                merged.append(point)

        with_tangents = []
        for index, (x, y) in enumerate(merged):
            if index < len(merged) - 1:
                length = merged[index + 1][0] - x
                tangent_y = (merged[index + 1][1] - y) / 3.0
            else:
                length = x - merged[index - 1][0]
                tangent_y = (y - merged[index - 1][1]) / 3.0
            with_tangents.append(
                (x, y, max(1.0, length / 3.0), tangent_y),
            )
        self._points = with_tangents
        self._mark_changed()

    def set_tangent(self, index: int, tx: float, ty: float) -> None:
        if 0 <= index < len(self._points):
            x, y, _old_tx, _old_ty = self._points[index]
            self._points[index] = (x, y, float(tx), float(ty))
            self._mark_changed()

    def reset(self) -> None:
        self.set_points([(0.0, 0.0), (255.0, 255.0)])

    def get_lut(self) -> np.ndarray:
        if self._lut_dirty or self._lut_cache is None:
            lut = bezier_lut(self._points, 256)
            self._lut_cache = np.clip(lut, 0, 255).astype(np.uint8)
            self._lut_dirty = False
        return self._lut_cache

    def is_default(self) -> bool:
        if len(self._points) != 2:
            return False
        x0, y0, _tx0, _ty0 = self._points[0]
        x1, y1, _tx1, _ty1 = self._points[1]
        return (
            abs(x0) < 1
            and abs(x1 - 255) < 1
            and abs(y0) < 1
            and abs(y1 - 255) < 1
        )

    def _mark_changed(self) -> None:
        self._lut_dirty = True
        self.update()
        self.lut_changed.emit()

    def _position_to_point(self, position) -> tuple[float, float]:
        width = max(1, self.width())
        height = max(1, self.height())
        x = max(0.0, min(255.0, position.x() * 255.0 / width))
        y = max(0.0, min(255.0, 255.0 - position.y() * 255.0 / height))
        return x, y

    def _point_to_position(self, x, y) -> tuple[int, int]:
        width = max(1, self.width())
        height = max(1, self.height())
        return int(x * width / 255.0), int((255.0 - y) * height / 255.0)

    def _find_target(self, position) -> Optional[tuple[str, int]]:
        best = None
        best_distance = self.HIT_RADIUS ** 2
        for index, (x, y, _tx, _ty) in enumerate(self._points):
            anchor_x, anchor_y = self._point_to_position(x, y)
            distance = (
                (position.x() - anchor_x) ** 2
                + (position.y() - anchor_y) ** 2
            )
            if distance < best_distance:
                best_distance = distance
                best = ("anchor", index)
        for index, (x, y, tx, ty) in enumerate(self._points):
            outgoing_x, outgoing_y = self._point_to_position(x + tx, y + ty)
            if (
                (position.x() - outgoing_x) ** 2
                + (position.y() - outgoing_y) ** 2
            ) < self.HANDLE_RADIUS ** 2:
                return "out", index
            incoming_x, incoming_y = self._point_to_position(x - tx, y - ty)
            if (
                (position.x() - incoming_x) ** 2
                + (position.y() - incoming_y) ** 2
            ) < self.HANDLE_RADIUS ** 2:
                return "in", index
        return best

    def _find_anchor(self, position) -> Optional[int]:
        for index, (x, y, _tx, _ty) in enumerate(self._points):
            anchor_x, anchor_y = self._point_to_position(x, y)
            if (
                (position.x() - anchor_x) ** 2
                + (position.y() - anchor_y) ** 2
            ) < self.HIT_RADIUS ** 2:
                return index
        return None

    def _distance_to_curve(self, position) -> float:
        if self.width() < 1 or self.height() < 1:
            return float("inf")
        index = max(
            0,
            min(255, int(round(position.x() * 255.0 / self.width()))),
        )
        curve_y = 255.0 - position.y() * 255.0 / self.height()
        return abs(curve_y - self.get_lut()[index]) * self.height() / 255.0

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            target = self._find_target(position)
            if target is not None:
                self._drag_target = target
                event.accept()
                return
            if self._distance_to_curve(position) < self.ADD_HIT_DIST:
                x, y = self._position_to_point(position)
                self.set_points(self.points() + [(x, y)])
                for index, point in enumerate(self._points):
                    if abs(point[0] - x) < 0.5 and abs(point[1] - y) < 0.5:
                        self._drag_target = ("anchor", index)
                        break
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_target is None or not (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            super().mouseMoveEvent(event)
            return
        kind, index = self._drag_target
        x, y = self._position_to_point(event.position().toPoint())
        anchor_x, anchor_y, old_tx, old_ty = self._points[index]
        count = len(self._points)
        if kind == "anchor":
            if index == 0:
                x = 0.0
            elif index == count - 1:
                x = 255.0
            else:
                minimum = self._points[index - 1][0] + 1.0
                maximum = max(minimum, self._points[index + 1][0] - 1.0)
                x = max(minimum, min(maximum, x))
            self._points[index] = (
                x, max(0.0, min(255.0, y)), old_tx, old_ty,
            )
        else:
            direction = 1.0 if kind == "out" else -1.0
            tx = direction * (x - anchor_x)
            ty = direction * (y - anchor_y)
            if kind == "out":
                neighbor_length = (
                    self._points[index + 1][0] - anchor_x
                    if index < count - 1
                    else anchor_x - self._points[index - 1][0]
                )
            else:
                neighbor_length = (
                    anchor_x - self._points[index - 1][0]
                    if index > 0
                    else self._points[index + 1][0] - anchor_x
                )
            neighbor_length = max(1.0, neighbor_length)
            tx = max(-neighbor_length * 0.8, min(neighbor_length * 0.8, tx))
            ty = max(-400.0, min(400.0, ty))
            self._points[index] = (anchor_x, anchor_y, tx, ty)
        self._mark_changed()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_target is not None:
            self._drag_target = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._find_anchor(event.position().toPoint())
            if index is not None and 0 < index < len(self._points) - 1:
                self._points.pop(index)
                self._mark_changed()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        height = self.height()
        painter.fillRect(0, 0, width, height, QBrush(Qt.GlobalColor.darkGray))
        painter.setPen(QPen(Qt.GlobalColor.gray, 1))
        painter.drawRect(0, 0, width - 1, height - 1)
        painter.setPen(QPen(Qt.GlobalColor.gray, 1, Qt.PenStyle.DotLine))
        for division in range(1, 4):
            x = int(width * division / 4)
            y = int(height * division / 4)
            painter.drawLine(x, 0, x, height)
            painter.drawLine(0, y, width, y)
        painter.setPen(QPen(Qt.GlobalColor.darkGreen, 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, height, width, 0)

        path = QPainterPath()
        for index, value in enumerate(self.get_lut().astype(np.int32)):
            x = index * width / 255.0
            y = (255 - value) * height / 255.0
            path.moveTo(x, y) if index == 0 else path.lineTo(x, y)
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawPath(path)

        for x, y, tx, ty in self._points:
            anchor_x, anchor_y = self._point_to_position(x, y)
            outgoing_x, outgoing_y = self._point_to_position(x + tx, y + ty)
            incoming_x, incoming_y = self._point_to_position(x - tx, y - ty)
            painter.setPen(QPen(Qt.GlobalColor.cyan, 1))
            painter.drawLine(anchor_x, anchor_y, outgoing_x, outgoing_y)
            painter.setBrush(QBrush(Qt.GlobalColor.cyan))
            painter.drawEllipse(outgoing_x - 3, outgoing_y - 3, 6, 6)
            painter.setPen(QPen(Qt.GlobalColor.darkCyan, 1))
            painter.drawLine(anchor_x, anchor_y, incoming_x, incoming_y)
            painter.setBrush(QBrush(Qt.GlobalColor.darkCyan))
            painter.drawEllipse(incoming_x - 3, incoming_y - 3, 6, 6)

        count = len(self._points)
        for index, (x, y, _tx, _ty) in enumerate(self._points):
            anchor_x, anchor_y = self._point_to_position(x, y)
            color = (
                Qt.GlobalColor.yellow
                if index in (0, count - 1)
                else Qt.GlobalColor.cyan
            )
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(
                anchor_x - self.POINT_RADIUS,
                anchor_y - self.POINT_RADIUS,
                self.POINT_RADIUS * 2,
                self.POINT_RADIUS * 2,
            )
        painter.end()


_bezier_lut = bezier_lut
_catmull_rom_lut = catmull_rom_lut


__all__ = ["CurveWidget", "bezier_lut", "catmull_rom_lut"]

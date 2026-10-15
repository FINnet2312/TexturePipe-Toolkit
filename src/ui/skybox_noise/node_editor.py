"""节点编辑器(Skybox 自定义噪声)。

基于 QGraphicsView 的画布式节点图编辑器:
- 左侧节点库(按分类),双击添加到画布
- 节点可拖动,端口连线(输出 → 输入,自动校验类型 / 环路)
- 选中节点 → 右侧属性面板编辑参数
- Del 删除节点,右键连线断开
- 快照式 undo / redo
- 自动预览(400ms debounce,小尺寸),保存 / 加载 JSON

对话框持有一个共享的 NodeGraph 引用(原地更新),主窗口渲染时直接读它。
"""
from __future__ import annotations

import json
import os

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QBrush, QColor, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QGraphicsEllipseItem,
    QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QPushButton, QScrollArea, QSplitter, QToolBar, QVBoxLayout, QWidget,
)

from src.core.file_cache import FileCache
from src.ui.i18n import tr
from .node_graph import (
    GraphEvaluator, NodeGraph, NodeGraphError, PORT_COORD, PORT_FIELD,
)
from .node_types import (
    NODE_CATEGORIES, NODES_BY_CATEGORY, NODE_REGISTRY, get_node_def,
)
from .widgets import ImageLabel, ParamSlider
from .image_io import load_rgb_float
from .core import NoiseContext

_EDGE_COLOR = QColor(0x88, 0x99, 0xbb)
_COORD_COLOR = QColor(0x4a, 0x9e, 0xff)
_FIELD_COLOR = QColor(0x7f, 0xd1, 0x4a)
_SELECT_COLOR = QColor(0x0a, 0x84, 0xff)


def _bezier_path(p0: QPointF, p1: QPointF) -> QPainterPath:
    dx = max(40.0, abs(p1.x() - p0.x()) * 0.5)
    path = QPainterPath(p0)
    path.cubicTo(p0.x() + dx, p0.y(), p1.x() - dx, p1.y(), p1.x(), p1.y())
    return path


# ---------------------------------------------------------------------------
# 图元:节点 / 端口 / 连线
# ---------------------------------------------------------------------------
class _PortItem(QGraphicsEllipseItem):
    """节点上的端口圆点;输出端口可按下拖出连线。"""

    def __init__(self, node_item, x, y, port, is_input, idx):
        super().__init__(node_item)
        self.node_item = node_item
        self.port = port
        self.is_input = is_input
        self.idx = idx
        r = 5.0
        if is_input:
            self.setRect(QRectF(-r, y - r, 2 * r, 2 * r))
        else:
            self.setRect(QRectF(node_item._w - r, y - r, 2 * r, 2 * r))
        color = _COORD_COLOR if port.kind == PORT_COORD else _FIELD_COLOR
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(0x22, 0x22, 0x22), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def scene_pos(self) -> QPointF:
        # 端口用 ``setRect`` 把圆放在父节点坐标中，item 自身的 pos 仍是
        # (0, 0)。scenePos() 因而只会得到节点原点，必须显式映射圆心。
        return self.mapToScene(self.rect().center())

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton and not self.is_input:
            scene = self.scene()
            if hasattr(scene, "start_connection"):
                scene.start_connection(self)
            ev.accept()
            return
        super().mousePressEvent(ev)


class _NodeItem(QGraphicsItem):
    """画布上的节点:标题 + 输入/输出端口。"""

    _w = 180
    _title_h = 28
    _port_h = 20

    def __init__(self, node, node_def, on_moved=None):
        super().__init__()
        self.node = node
        self.node_def = node_def
        self.on_moved = on_moved
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(*node.pos)
        n_in = len(node_def.inputs)
        n_out = len(node_def.outputs)
        self._h = self._title_h + max(n_in, n_out, 1) * self._port_h + 6
        for i, port in enumerate(node_def.inputs):
            _PortItem(self, 0, self._title_h + i * self._port_h + self._port_h / 2,
                      port, is_input=True, idx=i)
        for i, port in enumerate(node_def.outputs):
            _PortItem(self, self._w,
                      self._title_h + i * self._port_h + self._port_h / 2,
                      port, is_input=False, idx=i)
        self._drag_start = None

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._w, self._h)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self._w, self._h)
        pen = QPen(_SELECT_COLOR if self.isSelected() else QColor(0x55, 0x55, 0x55), 1.2)
        painter.setBrush(QColor(0x32, 0x32, 0x32))
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor(0xee, 0xee, 0xee))
        painter.drawText(QRectF(8, 4, self._w - 16, self._title_h - 8),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         tr(self.node_def.label))
        # 端口名
        painter.setPen(QColor(0xbb, 0xbb, 0xbb))
        for child in self.childItems():
            if isinstance(child, _PortItem):
                y = child.rect().center().y()
                if child.is_input:
                    painter.drawText(QRectF(14, y - 10, 120, 20),
                                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                                     tr(child.port.name))
                else:
                    painter.drawText(QRectF(self._w - 134, y - 10, 120, 20),
                                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                                     tr(child.port.name))

    def itemChange(self, change, value):
        if (change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
                and self.on_moved):
            self.node.pos = (value.x(), value.y())
        return super().itemChange(change, value)

    def mousePressEvent(self, ev):
        self._drag_start = self.pos()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._drag_start is not None and self.pos() != self._drag_start:
            if self.on_moved:
                self.on_moved()
        self._drag_start = None
        super().mouseReleaseEvent(ev)


class _EdgeItem(QGraphicsPathItem):
    """连接两个端口的贝塞尔曲线。"""

    def __init__(self, out_port: _PortItem, in_port: _PortItem):
        super().__init__()
        self.out_port = out_port
        self.in_port = in_port
        self.setPen(QPen(_EDGE_COLOR, 1.6))
        self.setZValue(-1)
        self.update_path()

    def update_path(self):
        self.setPath(_bezier_path(self.out_port.scene_pos(), self.in_port.scene_pos()))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            scene = self.scene()
            if hasattr(scene, "dialog"):
                scene.dialog.disconnect_edge(self)
            ev.accept()
            return
        super().mousePressEvent(ev)


# ---------------------------------------------------------------------------
# 场景 / 视图
# ---------------------------------------------------------------------------
class _NodeScene(QGraphicsScene):
    """画布:管理端口拖出连线的临时线。"""

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self._conn_start: _PortItem | None = None
        self._temp_edge = None
        self.setBackgroundBrush(QColor(0x1a, 0x1a, 0x1a))

    def start_connection(self, port_item: _PortItem):
        self._conn_start = port_item
        p0 = port_item.scene_pos()
        path = QPainterPath(p0)
        path.lineTo(p0)
        pen = QPen(QColor(0xaa, 0xaa, 0xaa), 1.5, Qt.PenStyle.DashLine)
        self._temp_edge = self.addPath(path, pen)
        self._temp_edge.setZValue(-2)

    def mouseMoveEvent(self, ev):
        if self._conn_start is not None and self._temp_edge is not None:
            p = ev.scenePos()
            self._temp_edge.setPath(_bezier_path(self._conn_start.scene_pos(), p))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._conn_start is not None:
            target = self._port_at(ev.scenePos(), want_input=True)
            if target is not None:
                self.dialog.connect_nodes(self._conn_start, target)
            if self._temp_edge is not None:
                self.removeItem(self._temp_edge)
                self._temp_edge = None
            self._conn_start = None
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def _port_at(self, pos: QPointF, want_input: bool) -> _PortItem | None:
        for item in self.items(pos):
            if isinstance(item, _PortItem) and item.is_input == want_input:
                if (item.scene_pos() - pos).manhattanLength() < 24:
                    return item
        return None


class _NodeView(QGraphicsView):
    def __init__(self, scene, dialog):
        super().__init__(scene)
        self._dlg = dialog
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setBackgroundBrush(QColor(0x1a, 0x1a, 0x1a))

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._dlg._delete_selected()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if ev.angleDelta().y() > 0 else 1.0 / 1.15
            self.scale(factor, factor)
            ev.accept()
            return
        super().wheelEvent(ev)


# ---------------------------------------------------------------------------
# 对话框
# ---------------------------------------------------------------------------
class NodeEditorDialog(QDialog):
    """节点图编辑器对话框(非模态)。"""

    graph_changed = Signal()

    def __init__(self, graph: NodeGraph, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("节点图编辑器 — 自定义噪声"))
        self.resize(1100, 720)
        self.graph = graph
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._selected_node_id: str | None = None
        self._file_cache = FileCache(max_size=4)
        self._preview_ctx = None
        self._slider_undo_active = False

        self._build_ui()
        self._rebuild_scene()
        self._push_state()

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(400)
        self.preview_timer.timeout.connect(self._refresh_preview)

    # -- UI 搭建 --------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 工具栏
        tb = QToolBar()
        tb.setMovable(False)
        for text, slot in [
            ("💾 保存图", self.save_graph),
            ("📂 加载图", self.load_graph),
            ("🎯 自动整理", self.auto_layout),
            ("👁 预览", self._refresh_preview),
        ]:
            act = tb.addAction(tr(text), slot)
        self._undo_act = tb.addAction(tr("↩ 撤销"), self.undo)
        self._redo_act = tb.addAction(tr("↪ 重做"), self.redo)
        self.chk_auto = QCheckBox(tr("自动预览"))
        self.chk_auto.setChecked(True)
        tb.addWidget(self.chk_auto)
        root.addWidget(tb)

        # 节点库 + 画布 + 属性
        split = QSplitter(Qt.Orientation.Horizontal)

        self.list_lib = QListWidget()
        self.list_lib.setMinimumWidth(190)
        self.list_lib.setMaximumWidth(240)
        for cat in NODE_CATEGORIES:
            if cat not in NODES_BY_CATEGORY or not NODES_BY_CATEGORY[cat]:
                continue
            head = QListWidgetItem(f"— {tr(cat)} —")
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setForeground(QColor(0x88, 0x88, 0x88))
            self.list_lib.addItem(head)
            for tid in NODES_BY_CATEGORY[cat]:
                nd = get_node_def(tid)
                item = QListWidgetItem(tr(nd.label))
                item.setData(Qt.ItemDataRole.UserRole, tid)
                item.setToolTip(tr(nd.hint))
                self.list_lib.addItem(item)
        self.list_lib.itemDoubleClicked.connect(self._on_lib_double_click)
        split.addWidget(self.list_lib)

        self._scene = _NodeScene(self)
        self._syncing_selection = False
        self._selection_signal_connected = False
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)
        self._selection_signal_connected = True
        self._view = _NodeView(self._scene, self)
        split.addWidget(self._view)

        # 属性面板
        panel = QWidget()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(360)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        self._props_title = QLabel(tr("未选中节点"))
        self._props_title.setStyleSheet("font-weight:bold;")
        pv.addWidget(self._props_title)
        self._props_scroll = QScrollArea()
        self._props_scroll.setWidgetResizable(True)
        self._form_host = QWidget()
        self._form_layout = QFormLayout(self._form_host)
        self._form_layout.setContentsMargins(4, 4, 4, 4)
        self._props_scroll.setWidget(self._form_host)
        pv.addWidget(self._props_scroll, 1)

        pv.addWidget(QLabel(tr("噪声预览:")))
        self._preview_lbl = ImageLabel(tr("节点图预览"))
        self._preview_lbl.setMinimumHeight(180)
        pv.addWidget(self._preview_lbl, 0)
        split.addWidget(panel)
        split.setSizes([210, 560, 300])
        root.addWidget(split, 1)

        self._status_lbl = QLabel(tr("就绪"))
        self._status_lbl.setStyleSheet("color:#888; padding:2px 6px;")
        root.addWidget(self._status_lbl)

    # -- 场景同步 --------------------------------------------------------
    def _rebuild_scene(self):
        self._scene.clear()
        self._edges: list[_EdgeItem] = []
        for node in self.graph.nodes.values():
            nd = get_node_def(node.type_id)
            item = _NodeItem(node, nd, on_moved=self._on_node_moved)
            self._scene.addItem(item)
            item.setSelected(node.id == self._selected_node_id)
        self._refresh_edges()

    def _refresh_edges(self):
        for e in self._edges:
            self._scene.removeItem(e)
        self._edges = []
        for (o_id, oi, i_id, ii) in self.graph.connections:
            out_port = self._find_port(o_id, oi, False)
            in_port = self._find_port(i_id, ii, True)
            if out_port is not None and in_port is not None:
                e = _EdgeItem(out_port, in_port)
                self._scene.addItem(e)
                self._edges.append(e)

    def _find_port(self, node_id: str, port_idx: int, is_input: bool):
        for item in self._scene.items():
            if isinstance(item, _NodeItem) and item.node.id == node_id:
                for child in item.childItems():
                    if (isinstance(child, _PortItem) and child.is_input == is_input
                            and child.idx == port_idx):
                        return child
        return None

    # -- 操作 ------------------------------------------------------------
    def _on_lib_double_click(self, item: QListWidgetItem):
        tid = item.data(Qt.ItemDataRole.UserRole)
        if tid:
            self._add_node(tid)

    def _add_node(self, type_id: str):
        center = self._view.mapToScene(self._view.viewport().rect().center())
        node = self.graph.add_node(
            type_id, pos=(center.x() - 90, center.y() - 40),
            params=get_node_def(type_id).default_params())
        self._rebuild_scene()
        self._push_state()
        self._select_node(node.id)
        self._mark_dirty()

    def _delete_selected(self):
        if not self._selected_node_id or self._selected_node_id not in self.graph.nodes:
            return
        self.graph.remove_node(self._selected_node_id)
        self._selected_node_id = None
        self._rebuild_scene()
        self._push_state()
        self._refresh_props()
        self._mark_dirty()

    def connect_nodes(self, out_port: _PortItem, in_port: _PortItem):
        out_node = out_port.node_item.node
        in_node = in_port.node_item.node
        try:
            self.graph.connect(out_node.id, out_port.idx,
                               in_node.id, in_port.idx, NODE_REGISTRY)
        except NodeGraphError as e:
            self._status(tr("连接失败: {}").format(e))
            return
        self._refresh_edges()
        self._push_state()
        self._mark_dirty()
        self._status(tr("已连接 {} → {}").format(out_node.type_id, in_node.type_id))

    def disconnect_edge(self, edge: _EdgeItem):
        out_node = edge.out_port.node_item.node
        in_node = edge.in_port.node_item.node
        self.graph.disconnect(out_node.id, edge.out_port.idx,
                              in_node.id, edge.in_port.idx)
        self._refresh_edges()
        self._push_state()
        self._mark_dirty()

    def _on_node_moved(self):
        # 移动后重算连线 + 记一次 undo
        self._refresh_edges()
        self._push_state()

    # -- 撤销 / 重做(快照式,原地恢复保持 graph 引用不变) ---------------
    def _snapshot(self) -> dict:
        return self.graph.to_dict()

    def _restore(self, snap: dict):
        g = NodeGraph.from_dict(snap)
        self.graph.nodes.clear()
        self.graph.nodes.update(g.nodes)
        self.graph.connections = list(g.connections)
        self.graph._next_id = g._next_id
        self._selected_node_id = None
        self._rebuild_scene()
        self._refresh_props()
        self._mark_dirty()

    def _push_state(self):
        """任何修改完成后调用:记录当前状态为一个撤销点。"""
        snap = self._snapshot()
        if self._undo and self._undo[-1] == snap:
            return
        self._undo.append(snap)
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()
        self._update_undo_btns()

    def undo(self):
        if len(self._undo) < 2:
            return
        self._redo.append(self._undo.pop())
        self._restore(self._undo[-1])
        self._update_undo_btns()

    def redo(self):
        if not self._redo:
            return
        nxt = self._redo.pop()
        self._undo.append(self._snapshot())
        self._restore(nxt)
        self._update_undo_btns()

    # 滑杆拖动:按下记起点,松开记终点,整体算一个撤销点
    def _on_slider_pressed(self):
        if not self._slider_undo_active:
            snap = self._snapshot()
            if not self._undo or self._undo[-1] != snap:
                self._undo.append(snap)
            self._slider_undo_active = True

    def _on_slider_released(self):
        self._slider_undo_active = False
        self._push_state()

    def _update_undo_btns(self):
        self._undo_act.setEnabled(len(self._undo) > 1)
        self._redo_act.setEnabled(bool(self._redo))

    # -- 属性面板 --------------------------------------------------------
    def _select_node(self, node_id: str):
        if node_id not in self.graph.nodes:
            node_id = None
        self._selected_node_id = node_id
        self._syncing_selection = True
        try:
            for item in self._scene.items():
                if isinstance(item, _NodeItem):
                    item.setSelected(item.node.id == node_id)
        finally:
            self._syncing_selection = False
        self._refresh_props()

    @Slot()
    def _on_scene_selection_changed(self) -> None:
        """把真实画布选择同步到属性面板和 Delete 操作。"""
        if getattr(self, "_syncing_selection", True):
            return
        selected = [
            item for item in self._scene.selectedItems()
            if isinstance(item, _NodeItem)
        ]
        self._selected_node_id = selected[0].node.id if selected else None
        self._refresh_props()

    def showEvent(self, event):  # noqa: N802
        if not self._selection_signal_connected:
            self._scene.selectionChanged.connect(
                self._on_scene_selection_changed,
            )
            self._selection_signal_connected = True
        super().showEvent(event)

    def closeEvent(self, event):  # noqa: N802
        # QGraphicsScene 在 Qt/Python 对象析构顺序交错时仍可能发
        # selectionChanged；关闭时断开，重新显示时再接回。
        if self._selection_signal_connected:
            try:
                self._scene.selectionChanged.disconnect(
                    self._on_scene_selection_changed,
                )
            except (RuntimeError, TypeError):
                pass
            self._selection_signal_connected = False
        self.preview_timer.stop()
        super().closeEvent(event)

    def _refresh_props(self):
        while self._form_layout.count():
            item = self._form_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if (not self._selected_node_id
                or self._selected_node_id not in self.graph.nodes):
            self._props_title.setText(tr("未选中节点 (在画布上点选)"))
            return
        node = self.graph.nodes[self._selected_node_id]
        nd = get_node_def(node.type_id)
        self._props_title.setText(tr(nd.label))
        if nd.hint:
            hint = QLabel(tr(nd.hint))
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#888;")
            self._form_layout.addRow(hint)
        for pd in nd.params:
            self._build_param_row(node, pd)

    def _build_param_row(self, node, pd):
        value = node.params.get(pd.key, pd.default)
        key = pd.key
        if pd.kind == "file":
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value))
            edit.setReadOnly(True)
            btn = QPushButton(tr("浏览…"))
            def _browse(_=None, k=key, e=edit):
                path, _ = QFileDialog.getOpenFileName(
                    self, tr("选择贴图"), "",
                    tr("图像 (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff *.exr)"))
                if path:
                    e.setText(path)
                    self._set_param(node, k, path, commit=True)
            btn.clicked.connect(_browse)
            lay.addWidget(edit, 1)
            lay.addWidget(btn)
            self._form_layout.addRow(tr(pd.label) + ":", row)
        elif pd.kind == "choice":
            cmb = QComboBox()
            for val, lab in pd.choices:
                cmb.addItem(tr(lab), val)
            idx = cmb.findData(value)
            cmb.setCurrentIndex(max(0, idx))
            cmb.currentIndexChanged.connect(
                lambda _i, k=key: self._set_param(node, k, cmb.currentData(), commit=True))
            self._form_layout.addRow(tr(pd.label) + ":", cmb)
        elif pd.kind == "bool":
            cb = QCheckBox(tr(pd.label))
            cb.setChecked(bool(value))
            cb.toggled.connect(
                lambda v, k=key: self._set_param(node, k, v, commit=True))
            self._form_layout.addRow("", cb)
        else:
            slider = ParamSlider(
                tr(pd.label), pd.min_v, pd.max_v, float(value),
                step=pd.step, decimals=pd.decimals,
                callback=lambda v, k=key: self._set_param(node, k, v, commit=False),
            )
            slider.slider.sliderPressed.connect(self._on_slider_pressed)
            slider.slider.sliderReleased.connect(self._on_slider_released)
            self._form_layout.addRow(slider)

    def _set_param(self, node, key, value, commit: bool):
        node.params[key] = value
        self._mark_dirty()
        if commit:
            self._push_state()

    # -- 保存 / 加载 -----------------------------------------------------
    def save_graph(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("保存节点图"), "custom_noise.json", tr("节点图 (*.json)"))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.graph.to_dict(), f, ensure_ascii=False, indent=1)
            self._status(tr("已保存: {}").format(path))
        except OSError as e:
            self._status(tr("保存失败: {}").format(e))

    def load_graph(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("加载节点图"), "", tr("节点图 (*.json)"))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            g = NodeGraph.from_dict(d, NODE_REGISTRY)
        except (OSError, json.JSONDecodeError, NodeGraphError,
                TypeError, ValueError, KeyError) as e:
            self._status(tr("加载失败: {}").format(e))
            return
        self.graph.nodes.clear()
        self.graph.nodes.update(g.nodes)
        self.graph.connections = list(g.connections)
        self.graph._next_id = g._next_id
        self._selected_node_id = None
        self._rebuild_scene()
        self._refresh_props()
        self._push_state()
        self._mark_dirty()
        self._status(tr("已加载: {}").format(path))

    # -- 自动整理 --------------------------------------------------------
    def auto_layout(self):
        def _depth(nid, _memo=None):
            if _memo is None:
                _memo = {}
            if nid in _memo:
                return _memo[nid]
            ins = [c[0] for c in self.graph.connections if c[2] == nid]
            if not ins:
                _memo[nid] = 0
            else:
                _memo[nid] = 1 + max(_depth(i, _memo) for i in ins)
            return _memo[nid]

        layers: dict[int, list] = {}
        for node in self.graph.nodes.values():
            layers.setdefault(_depth(node.id), []).append(node)
        x = 40
        for d in sorted(layers):
            for i, n in enumerate(layers[d]):
                n.pos = (x, 40 + i * 130)
            x += 220
        self._rebuild_scene()
        self._push_state()

    # -- 预览 ------------------------------------------------------------
    def _mark_dirty(self):
        self._refresh_edges()
        self.graph_changed.emit()
        if self.chk_auto.isChecked():
            self.preview_timer.start()

    def _ctx(self) -> dict:
        if self._preview_ctx is None:
            W, H = 256, 128
            u = np.linspace(0, 1, W, endpoint=False)
            v = np.linspace(0, 1, H, endpoint=False)
            U, V = np.meshgrid(u, v)
            from .projections import uv_to_xyz
            x, y, z = uv_to_xyz("equirectangular", U, V)
            self._preview_ctx = {
                "xyz": np.stack([x, y, z], axis=-1).astype(np.float32),
                "uv": np.stack([U, V], axis=-1).astype(np.float32),
                "load_texture": self._load_texture,
                "noise_context": NoiseContext(1337),
            }
        return self._preview_ctx

    def _load_texture(self, path: str) -> np.ndarray:
        return load_rgb_float(path, self._file_cache)

    def _refresh_preview(self):
        if not self.graph.nodes:
            self._preview_lbl.set_ndarray(None)
            return
        try:
            ev = GraphEvaluator(self.graph, self._ctx(), NODE_REGISTRY)
            field = ev.eval_output("output", 0)
            field = np.asarray(field, dtype=np.float32)
            mn, mx = float(np.nanmin(field)), float(np.nanmax(field))
            if mx - mn < 1e-9:
                disp = np.zeros_like(field)
            else:
                disp = (field - mn) / (mx - mn)
            self._preview_lbl.set_ndarray(
                disp, tr("噪声预览 {}x{}").format(field.shape[1], field.shape[0]),
            )
            self._status(tr("预览正常 (范围 {:.3f} ~ {:.3f})").format(mn, mx))
        except NodeGraphError as e:
            self._preview_lbl.set_ndarray(None)
            self._status(tr("预览: {}").format(e))
        except Exception as e:  # noqa: BLE001
            self._preview_lbl.set_ndarray(None)
            self._status(tr("预览出错: {}").format(e))

    # -- 其它 ------------------------------------------------------------
    def _status(self, msg: str):
        self._status_lbl.setText(msg)


__all__ = ["NodeEditorDialog"]

"""SkyboxNoiseWidget — texpipe 第 3 个 Tab 的内容(QWidget)。

打开图像 → 自动检测投影 → 调参 → 后台 QThread 渲染 → 实时显示合成预览。
支持保存 composite / mask / normal 三种输出。
支持拖拽图片到 Tab 内加载、恢复默认参数、LRU 缓存最近打开的原图。

依赖:只跟 PIL/numpy 共享,外加轻量的 src.core.file_cache(LRU)。
"""
from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QDragEnterEvent, QDropEvent, QImage, QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QProgressBar, QScrollArea,
    QSizePolicy, QSlider, QSplitter, QStatusBar, QToolBar,
    QVBoxLayout, QWidget,
)

from src.core.file_cache import FileCache
from src.core.pixels import from_normalized
from src.io.saver import IMAGE_SAVE_FILTER, save_image
from .compose import render
from .core import ALL_NOISE, NOISE_CAUSTICS, gen_noise
from .node_editor import NodeEditorDialog
from .node_types import default_graph
from .projections import ALL_PROJECTIONS, PROJ_EQUI, detect_projection
from .widgets import ImageLabel, ParamSlider
from .worker import RenderWorker
from .image_io import load_rgb_array

# 拖拽导入接受的图像扩展名
_SKYBOX_IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".tga",
    ".tif", ".tiff", ".exr",
}

# 噪声类型下拉里的「自定义」项(节点图)
NOISE_CUSTOM = "自定义 (节点图)"


class SkyboxNoiseWidget(QWidget):
    """作为 Tab 嵌入 texpipe 主窗口。"""

    status_message = Signal(str, str)

    DEFAULT_PARAMS = {
        "projection": PROJ_EQUI,
        "noise_type": NOISE_CAUSTICS,
        "noise_scale": 3.8,
        "octaves": 4,
        "persistence": 0.5,
        "lacunarity": 2.05,
        "seed": 1337,
        "intensity": 0.55,
        "mask_top": 0.18,
        "mask_bottom": 0.55,
        "mask_softness": 1.2,
        "caustic_power": 1.15,
        "warp_amount": 0.85,
        "lattice_freq": 9.0,
        "lattice_weight": 0.55,
        "normal_strength": 0.14,
        "tint_blue": 0.08,
        "highlight_knee": 0.85,
        "highlight_max": 1.05,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.src_image = None
        self.composite = None
        self.mask_gray = None
        self.normal_rgb = None
        self.caustic = None
        self.mask = None
        self.last_save_dir = ""
        self._source_dtype = np.dtype(np.uint8)
        self.worker: RenderWorker | None = None
        self._workers: set[RenderWorker] = set()
        self._pending_render_full: bool | None = None
        self._closing = False
        self._render_seq = 0
        self._result_is_full = False
        self._pending_saves: list[tuple[str, str]] = []
        self.params = dict(self.DEFAULT_PARAMS)
        self._param_widgets: dict[str, ParamSlider] = {}
        # 原图 LRU 缓存(天空图大,4 张足够;存 uint8,省内存)
        self._file_cache = FileCache(max_size=4)
        # 整个 Tab 接受拖拽图片
        self.setAcceptDrops(True)
        # 自定义噪声节点图 + 编辑器对话框(非模态,共享 graph 引用)
        self.node_graph = default_graph()
        self._node_dialog: NodeEditorDialog | None = None

        # debounce — 参数改完 400ms 后才重算,避免拖滑块时疯狂刷新
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(400)
        self.debounce.timeout.connect(self.regenerate)

        # 父 widget 可能是 MainWindow(QMainWindow),借用其 statusBar / addToolBar;
        # 顶层嵌入 Tab 时父是 QTabWidget 没有这些,就走本地 status。
        self._build_ui()
        self._build_statusbar()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 工具条
        tb = QToolBar()
        tb.setIconSize(self._qsize(16, 16))
        # 注意:在 Tab 嵌入场景下,父窗口是 QMainWindow,addToolBar 会被 MainWindow
        # 拦截;为了不污染主窗口工具栏,我们用更隐蔽的方式:
        # 把按钮放进一个顶部 bar widget 里。
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 4, 4, 4)
        bar_layout.setSpacing(6)

        for text, slot in [
            ("📂 打开图像", self.open_image),
            ("💾 保存合成图", self.save_composite),
            ("💾 保存 mask", self.save_mask),
            ("💾 保存法线", self.save_normal),
            ("🧩 编辑节点图", self.open_node_editor),
            ("🔄 强制重算", self.regenerate_now),
            ("↺ 恢复默认", self.reset_defaults),
        ]:
            btn = self._make_button(text, slot)
            bar_layout.addWidget(btn)
        bar_layout.addStretch(1)
        # 缩放 / 性能提示
        self.lbl_perf = QLabel("Numba: ?")
        self.lbl_perf.setStyleSheet("color:#888;")
        bar_layout.addWidget(self.lbl_perf)

        # 中心 splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.lbl_original = ImageLabel("原图")
        splitter.addWidget(self.lbl_original)
        self.lbl_composite = ImageLabel("合成预览")
        splitter.addWidget(self.lbl_composite)
        panel = QScrollArea()
        panel.setWidgetResizable(True)
        panel.setMinimumWidth(360)
        panel.setMaximumWidth(480)
        splitter.addWidget(panel)

        panel_widget = QWidget()
        panel_layout = QVBoxLayout(panel_widget)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel.setWidget(panel_widget)

        self._build_input_group(panel_layout)
        self._build_noise_group(panel_layout)
        self._build_compose_group(panel_layout)
        self._build_caustics_group(panel_layout)
        self._build_post_group(panel_layout)
        panel_layout.addStretch(1)

        splitter.setSizes([500, 500, 400])

        # 整体
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(bar)
        root.addWidget(splitter, 1)

        # Numba 状态提示
        from .core import NUMBA_OK
        self.lbl_perf.setText(
            f"Numba: {'✓ 加速 25-40x' if NUMBA_OK else '✗ (numpy fallback, 慢)'}",
        )

    def _build_statusbar(self) -> None:
        # 找最近的 QMainWindow 借 statusBar;否则本地用 QLabel 顶替
        top = self.window()
        if isinstance(top, QMainWindow):
            self._status = top.statusBar()
        else:
            self._status = None
        # 插件常在无 parent 状态下由 factory 创建，因此本地状态栏始终进入
        # 自己的布局；如果以后由 QMainWindow 承载，消息仍可同步给主状态栏。
        status_row = QWidget(self)
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(8, 3, 8, 3)
        self._local_status = QLabel("就绪")
        self._local_status.setStyleSheet("color:#888;")
        status_layout.addWidget(self._local_status, 1)
        self.progress_bar = QProgressBar(status_row)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setMaximumWidth(180)
        self.progress_bar.setVisible(False)
        status_layout.addWidget(self.progress_bar)
        self.layout().addWidget(status_row)

    def _status_msg(self, text: str) -> None:
        self._local_status.setText(text)
        if self._status is not None:
            self._status.showMessage(text)
        self.status_message.emit("info", text)

    @staticmethod
    def _qsize(w, h):
        from PySide6.QtCore import QSize
        return QSize(w, h)

    @staticmethod
    def _make_button(text: str, slot):
        from PySide6.QtWidgets import QPushButton
        b = QPushButton(text)
        b.clicked.connect(slot)
        return b

    # ------------------------------------------------------------------
    # 参数组
    # ------------------------------------------------------------------
    def _add_param(self, layout, key, label, min_v, max_v, value, step=0.01,
                   decimals=3):
        w = ParamSlider(label, min_v, max_v, value, step, decimals,
                        callback=self._on_param_changed)
        layout.addRow(w)
        self._param_widgets[key] = w
        return w

    def _build_input_group(self, layout):
        g = QGroupBox("输入")
        v = QFormLayout(g)
        self.cmb_proj = QComboBox()
        self.cmb_proj.addItems(ALL_PROJECTIONS)
        self.cmb_proj.setCurrentText(self.params["projection"])
        self.cmb_proj.currentTextChanged.connect(self._on_param_changed)
        v.addRow("投影方式:", self.cmb_proj)
        self.cmb_noise = QComboBox()
        self.cmb_noise.addItems(list(ALL_NOISE) + [NOISE_CUSTOM])
        self.cmb_noise.setCurrentText(self.params["noise_type"])
        self.cmb_noise.currentTextChanged.connect(self._on_param_changed)
        v.addRow("噪声类型:", self.cmb_noise)
        self._add_param(v, "seed", "Seed", 0, 9999, self.params["seed"],
                        step=1, decimals=0)
        layout.addWidget(g)

    def _build_noise_group(self, layout):
        g = QGroupBox("噪声参数")
        v = QFormLayout(g)
        self._add_param(v, "noise_scale", "空间尺度", 0.5, 20.0,
                        self.params["noise_scale"])
        self._add_param(v, "octaves", "Octaves", 1, 8, self.params["octaves"],
                        step=1, decimals=0)
        self._add_param(v, "persistence", "Persistence", 0.1, 1.0,
                        self.params["persistence"])
        self._add_param(v, "lacunarity", "Lacunarity", 1.5, 4.0,
                        self.params["lacunarity"])
        layout.addWidget(g)

    def _build_compose_group(self, layout):
        g = QGroupBox("合成 / Mask")
        v = QFormLayout(g)
        self._add_param(v, "intensity", "合成强度", 0.0, 2.0,
                        self.params["intensity"])
        self._add_param(v, "mask_top", "Mask Top", 0.0, 0.5,
                        self.params["mask_top"])
        self._add_param(v, "mask_bottom", "Mask Bottom", 0.3, 1.0,
                        self.params["mask_bottom"])
        self._add_param(v, "mask_softness", "Mask 软度", 0.5, 3.0,
                        self.params["mask_softness"])
        self._add_param(v, "normal_strength", "法线扰动", 0.0, 0.5,
                        self.params["normal_strength"])
        layout.addWidget(g)

    def _build_caustics_group(self, layout):
        g = QGroupBox("Caustics（仅 Caustics 噪声生效）")
        v = QFormLayout(g)
        self._add_param(v, "caustic_power", "线条锐度", 0.8, 3.0,
                        self.params["caustic_power"])
        self._add_param(v, "warp_amount", "域扭曲强度", 0.0, 2.0,
                        self.params["warp_amount"])
        self._add_param(v, "lattice_freq", "细线频率", 3.0, 20.0,
                        self.params["lattice_freq"])
        self._add_param(v, "lattice_weight", "细线权重", 0.0, 1.0,
                        self.params["lattice_weight"])
        layout.addWidget(g)

    def _build_post_group(self, layout):
        g = QGroupBox("后处理")
        v = QFormLayout(g)
        self._add_param(v, "tint_blue", "冷色调偏移", -0.3, 0.3,
                        self.params["tint_blue"])
        self._add_param(v, "highlight_knee", "高光压起点", 0.5, 0.99,
                        self.params["highlight_knee"])
        self._add_param(v, "highlight_max", "高光上限", 0.8, 1.5,
                        self.params["highlight_max"])
        layout.addWidget(g)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_param_changed(self, *_):
        self.params["projection"] = self.cmb_proj.currentText()
        self.params["noise_type"] = self.cmb_noise.currentText()
        for k, w in self._param_widgets.items():
            self.params[k] = w.value()
        self._result_is_full = False
        self.debounce.start()
        self._status_msg("参数已变 — 400ms 后重算…")

    def regenerate_now(self) -> None:
        self.debounce.stop()
        self.regenerate(full=True)

    def regenerate(self, full: bool = False) -> None:
        if self.src_image is None:
            return
        # 用户已经选择保存路径时，任何随后到来的参数变化都必须生成
        # 全分辨率结果，不能让 debounce 的代理渲染覆盖保存请求。
        if self._pending_saves:
            full = True
        # 同一时间只运行一个高开销任务。新请求只记录“最新一次”参数，取消
        # 完成后再启动，既不阻塞 GUI，也避免快速拖动产生多个并行 JIT。
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self._render_seq += 1
            self._pending_render_full = bool(full)
            self._status_msg("正在取消旧渲染，随后计算最新参数…")
            return
        self._pending_render_full = None
        self._render_seq += 1
        seq = self._render_seq
        scale = 1.0 if full else 0.4
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        label = "全分辨率" if full else "预览"
        self._status_msg(f"渲染中 [{label}]…")

        worker = RenderWorker(
            self.src_image,
            self.params["projection"],
            self.params["noise_type"],
            self.params,
            scale,
            graph_dict=(
                self.node_graph.to_dict()
                if self.params["noise_type"] == NOISE_CUSTOM else None
            ),
            parent=self,
        )
        self.worker = worker
        self._workers.add(worker)
        worker.progress.connect(
            lambda v, msg, s=seq: self._on_progress(s, v, msg))
        worker.finished_ok.connect(
            lambda *args, s=seq: self._on_render_done(s, *args))
        worker.failed.connect(
            lambda e, s=seq: self._on_render_failed(s, e))
        # QThread 跑完后让 Qt 在合适时机回收 C++ 句柄(下次 regen 触发旧
        # worker 的 deleteLater,主线程释放;此处不强制同步 wait 干扰时序)。
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_progress(self, seq: int, v: int, msg: str) -> None:
        if seq != self._render_seq:
            return
        self.progress_bar.setValue(v)
        if v < 100:
            self._status_msg(f"{msg}  ({v}%)")

    def _on_render_done(self, seq, composite, mask_gray, normal, caustic,
                        mask, sH, sW, dt) -> None:
        if seq != self._render_seq:
            return
        self.composite = composite
        self.mask_gray = mask_gray
        self.normal_rgb = normal
        self.caustic = caustic
        self.mask = mask
        self._result_is_full = (
            self.src_image is not None
            and (sH, sW) == self.src_image.shape[:2]
        )
        self.lbl_composite.set_ndarray(composite, "合成预览")
        self.progress_bar.setValue(100)
        QTimer.singleShot(400, lambda: self.progress_bar.setVisible(False))
        self._status_msg(f"渲染完成 {sW}x{sH}, {dt:.2f}s")
        if self._result_is_full and self._pending_saves:
            pending = self._pending_saves
            self._pending_saves = []
            for attribute, path in pending:
                self._write_output(getattr(self, attribute), path)

    def _on_render_failed(self, seq: int, err: str) -> None:
        if seq != self._render_seq:
            return
        self.progress_bar.setVisible(False)
        if self._pending_saves:
            self._pending_saves = []
            err = f"{err}（已取消待处理的保存请求）"
        self._status_msg(f"渲染失败: {err}")
        # 用 QMessageBox 会阻塞 Tab;改用 status_bar,已经显示在状态栏
        # 仍保留一个非模态 log 到 stdout,方便调试
        import logging
        logging.error("[skybox_noise] render failed: %s", err)

    def _on_worker_finished(self, worker=None) -> None:
        """QThread 内置 finished 信号:运行结束(不管成功失败 cancel)时回收。
        注意这里可能收到旧 worker 的信号(已被新 worker 顶替),所以不能清
        任何当前状态,只能安全释放 QThread 对象本身。
        """
        w = worker or self.sender()
        if w is not None:
            self._workers.discard(w)
            if self.worker is w:
                self.worker = None
            w.deleteLater()
        if (
            not self._closing
            and self._pending_render_full is not None
            and not any(worker.isRunning() for worker in self._workers)
        ):
            full = self._pending_render_full
            self._pending_render_full = None
            QTimer.singleShot(0, lambda value=full: self.regenerate(value))

    def closeEvent(self, event):  # noqa: N802
        """关闭时仅请求取消；不阻塞 GUI 等待 JIT/NumPy 计算。"""
        self._closing = True
        self._pending_render_full = None
        self._pending_saves = []
        self.debounce.stop()
        self._render_seq += 1
        for worker in tuple(self._workers):
            if worker.isRunning():
                worker.cancel()
        if self._node_dialog is not None:
            self._node_dialog.close()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # 打开 / 保存
    # ------------------------------------------------------------------
    def open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开贴图", self.last_save_dir,
            "图像 (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff *.exr)",
        )
        if not path:
            return
        self._load_image(path)

    def _load_image(self, path: str) -> None:
        """加载一张图并刷新预览(文件对话框与拖拽共用入口)。"""
        try:
            arr = self._load_image_cached(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "加载失败", str(e))
            return
        self.src_image = arr
        self._result_is_full = False
        self.last_save_dir = os.path.dirname(path)
        self.lbl_original.set_ndarray(
            arr, f"原图 {arr.shape[1]}x{arr.shape[0]}",
        )
        detected = detect_projection(arr.shape[1], arr.shape[0])
        self.cmb_proj.setCurrentText(detected)
        self.params["projection"] = detected
        self._status_msg(
            f"已加载: {os.path.basename(path)}  →  投影: {detected}",
        )
        self.regenerate_now()

    def _load_image_cached(self, path: str) -> np.ndarray:
        """带 LRU 的高精度解码；浮点 HDR 值不会被裁切。"""
        raw = load_rgb_array(path, self._file_cache)
        self._source_dtype = raw.dtype
        from src.core.pixels import normalized_float
        return np.ascontiguousarray(normalized_float(raw), dtype=np.float32)

    # ------------------------------------------------------------------
    # 拖拽导入
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._first_image_path(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        path = self._first_image_path(event)
        if path:
            self._load_image(path)
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _first_image_path(event) -> str | None:
        md = event.mimeData()
        if md is None or not md.hasUrls():
            return None
        for url in md.urls():
            p = url.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in _SKYBOX_IMAGE_EXTS:
                return p
        return None

    # ------------------------------------------------------------------
    # 节点图编辑器
    # ------------------------------------------------------------------
    def open_node_editor(self) -> None:
        """打开/唤起节点图编辑器(非模态,共享 self.node_graph)。"""
        if self._node_dialog is None:
            self._node_dialog = NodeEditorDialog(self.node_graph, parent=self)
            self._node_dialog.graph_changed.connect(
                self._on_node_graph_changed,
            )
        self._node_dialog.show()
        self._node_dialog.raise_()
        self._node_dialog.activateWindow()

    def _on_node_graph_changed(self) -> None:
        """自定义图变化后让主预览失效，并按主窗口节奏重新渲染。"""
        self._result_is_full = False
        if self.cmb_noise.currentText() == NOISE_CUSTOM:
            self.debounce.start()
            self._status_msg("节点图已修改 — 400ms 后重算…")

    # ------------------------------------------------------------------
    # 恢复默认
    # ------------------------------------------------------------------
    def reset_defaults(self) -> None:
        self.cmb_proj.setCurrentText(self.DEFAULT_PARAMS["projection"])
        self.cmb_noise.setCurrentText(self.DEFAULT_PARAMS["noise_type"])
        for k, w in self._param_widgets.items():
            w.setValue(self.DEFAULT_PARAMS[k])
        # setValue 会逐次触发 _on_param_changed,最后统一强制重算一次
        self._status_msg("已恢复默认参数")
        self.regenerate_now()

    def _save(self, attribute: str, default_name: str) -> None:
        if self.src_image is None:
            QMessageBox.warning(self, "无数据", "请先生成图像")
            return
        if self._source_dtype.kind == "f":
            default_name = os.path.splitext(default_name)[0] + ".exr"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存", os.path.join(self.last_save_dir, default_name),
            IMAGE_SAVE_FILTER,
        )
        if not path:
            return
        arr = getattr(self, attribute)
        if (
            arr is None
            or not self._result_is_full
            or self.worker is not None
            or self.debounce.isActive()
        ):
            # 选择路径后异步生成最新的全分辨率结果；同一输出类型只保留
            # 用户最后一次选择的路径，三个输出可共用一次全分辨率渲染。
            self._pending_saves = [
                request for request in self._pending_saves
                if request[0] != attribute
            ]
            self._pending_saves.append((attribute, path))
            self._status_msg("正在生成最新的全分辨率结果，完成后自动保存…")
            self.regenerate_now()
            return
        self._write_output(arr, path)

    def _write_output(self, arr: np.ndarray, path: str) -> None:
        """把已确认是当前结果的数组按源位深写盘。"""
        try:
            suffix = os.path.splitext(path)[1].lower()
            values = np.asarray(arr)
            if suffix == ".exr":
                output = values.astype(np.float32, copy=False)
            elif suffix in {".tif", ".tiff"}:
                output = (
                    values.astype(np.float32, copy=False)
                    if self._source_dtype.kind == "f"
                    else from_normalized(np.clip(values, 0, 1), self._source_dtype)
                )
            elif suffix == ".png":
                if self._source_dtype.kind == "f":
                    raise ValueError("浮点/HDR 结果请保存为 EXR 或 TIFF，PNG 会丢失 HDR 范围")
                output = from_normalized(
                    np.clip(values, 0, 1), self._source_dtype,
                )
            else:
                if self._source_dtype != np.dtype(np.uint8):
                    raise ValueError("当前源图不是 8-bit，请改存 PNG/TIFF/EXR")
                output = from_normalized(np.clip(values, 0, 1), np.uint8)
            save_image(output, path)
            self.last_save_dir = os.path.dirname(path)
            self._status_msg(f"已保存: {path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(e))

    def save_composite(self) -> None:
        self._save("composite", "composite.png")

    def save_mask(self) -> None:
        self._save("mask_gray", "mask.png")

    def save_normal(self) -> None:
        self._save("normal_rgb", "normal.png")


# 入口:plugin 加载用
def create_widget(parent=None) -> SkyboxNoiseWidget:
    return SkyboxNoiseWidget(parent=parent)


__all__ = ["SkyboxNoiseWidget", "create_widget", "render"]

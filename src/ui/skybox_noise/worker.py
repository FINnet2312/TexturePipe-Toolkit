"""后台渲染 Worker。

在 QThread 中跑 render(),通过信号汇报进度和结果。
支持中途取消(主线程调 cancel() 后,worker 在下个 checkpoint 退出)。
支持节点图自定义噪声(graph_dict 非 None 时先求值节点图)。

线程模型:Perlin perm 表 / fbm 状态是模块全局,而 worker 跑在独立 QThread
里。直接共享会让 UI 线程和 worker 同时改 _P,产生撕裂的噪声。本 worker 在
构造时拷贝一份本地 perm + grad,所有 numba 调用都用本地副本,完全不碰模块
全局——这同时让 numba 编译链在进程内可被多个 worker 复用(签名只跟 dtype
挂钩,不跟具体数组挂钩)。
"""
from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from src.core.file_cache import FileCache
from src.ui.i18n import tr
from .compose import render
from .compose import preview_size, resize_preview
from .image_io import load_rgb_float
from .core import NoiseContext


# 拿到 core 模块的 grad 数组(只读,所有线程共享——它从来不会被改)
try:
    from . import core as _core
    _GRAD3 = _core._GRAD3
except Exception:  # noqa: BLE001
    _GRAD3 = None


class RenderWorker(QThread):
    """QThread 子类,负责跑一次 render。

    信号:
        progress(int, str)    — 0..100 + 状态文本
        finished_ok(...)      — composite, mask_gray, normal, caustic, mask_soft, sH, sW, dt
        failed(str)           — 错误消息
    """

    progress = Signal(int, str)
    finished_ok = Signal(object, object, object, object,
                         object, int, int, float)
    failed = Signal(str)

    def __init__(self, src: np.ndarray, projection: str, noise_type: str,
                 p: dict, scale: float, graph_dict: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.src = src
        self.projection = projection
        self.noise_type = noise_type
        # 拷贝, 避免主线程改 p 时 worker 读到不一致
        self.p = dict(p)
        self.scale = scale
        self.graph_dict = graph_dict
        self._cancel = False
        self._cache = FileCache(max_size=4)
        # 本线程独立的 perm 表:构造时跟 core 同步,运行期只在本地重置,
        # 不动 core._PERM / core._P,避免与 UI 线程(节点图预览可能走
        # gen_noise → fbm3d → _reset_perm)发生撕裂。numba 编译链仍然
        # 在 worker 间共享(签名按 dtype,而不是按数组实例)。
        self._noise_context = NoiseContext(int(self.p.get("seed", 0)))
        # 兼容诊断代码；数组本身只属于本 worker。
        self._local_P = self._noise_context.P
        self._grad = _GRAD3 if _GRAD3 is not None else _core._GRAD3
        self._local_seed = self._noise_context.seed

    def cancel(self) -> None:
        self._cancel = True

    def _reseed(self, seed: int) -> None:
        """重置本线程的 perm 表(不动模块全局)。"""
        self._noise_context.reseed(seed)
        self._local_seed = self._noise_context.seed

    def _gen_noise(self, noise_type, x, y, z, p: dict) -> np.ndarray:
        """使用本 worker 私有的噪声上下文。"""
        return self._noise_context.gen_noise(noise_type, x, y, z, p)

    def run(self) -> None:
        try:
            t0 = time.time()
            self._emit(5, tr("准备中…"))
            H, W = self.src.shape[:2]
            if self.scale < 1.0:
                sH, sW = preview_size(H, W, self.scale)
                src_small = resize_preview(self.src, sH, sW)
            else:
                sH, sW = H, W
                src_small = self.src
            if self._cancel:
                return

            self._emit(15, tr("UV 网格…"))
            u = np.linspace(0, 1, sW, endpoint=False)
            v = np.linspace(0, 1, sH, endpoint=False)
            U, V = np.meshgrid(u, v)
            sx, sy, sz = self._uv_to_xyz(self.projection, U, V)
            if self._cancel:
                return

            self._emit(25, tr("生成 {} 噪声…").format(self.noise_type))
            if self.graph_dict:
                # 节点图自定义噪声
                caustic = self._eval_graph(sx, sy, sz, U, V)
            else:
                # 用本线程独立的 perm 表,完全不动模块全局 _P(线程安全)
                caustic = self._gen_noise(
                    self.noise_type, sx, sy, sz, self.p)
            if self._cancel:
                return

            self._emit(55, tr("Mask / 渐变…"))
            tt = np.clip(
                (V - self.p["mask_top"])
                / max(self.p["mask_bottom"] - self.p["mask_top"], 1e-6),
                0, 1,
            )
            mask = (1.0 - tt) ** self.p["mask_softness"]
            grad_y = np.gradient(caustic, axis=0)
            grad_x = np.gradient(caustic, axis=1)
            if self._cancel:
                return

            self._emit(70, tr("合成…"))
            slope_mod = np.clip(
                1.0 - self.p["normal_strength"]
                * (np.abs(grad_x) + np.abs(grad_y)) * 6.0,
                0.6, 1.0,
            )
            from .compose import compose
            composite = compose(src_small, caustic, mask, slope_mod, self.p)
            mask_gray = np.clip(caustic * mask, 0, 1)
            if self._cancel:
                return

            self._emit(88, tr("法线贴图…"))
            nx = np.clip(-grad_x * 6.0, -50.0, 50.0)
            ny = np.clip(-grad_y * 6.0, -50.0, 50.0)
            nz = np.ones_like(nx)
            L = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-8
            nx /= L; ny /= L; nz /= L
            normal = np.stack(
                [nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5],
                axis=-1,
            )
            if self._cancel:
                return

            dt = time.time() - t0
            self._emit(100, tr("完成 ({:.2f}s)").format(dt))
            self.finished_ok.emit(
                composite, mask_gray, np.clip(normal, 0, 1),
                caustic, mask, sH, sW, dt,
            )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

    def _emit(self, v: int, msg: str) -> None:
        # 避免在 cancel 后还 emit
        if not self._cancel:
            self.progress.emit(v, msg)

    def _eval_graph(self, sx, sy, sz, U, V) -> np.ndarray:
        """求值节点图,返回 HxW 噪声场(float32)。"""
        from .node_graph import GraphEvaluator, NodeGraph
        from .node_types import NODE_REGISTRY
        graph = NodeGraph.from_dict(self.graph_dict, NODE_REGISTRY)
        xyz = np.stack([sx, sy, sz], axis=-1).astype(np.float32)
        uv = np.stack([U, V], axis=-1).astype(np.float32)
        ctx = {
            "xyz": xyz,
            "uv": uv,
            "load_texture": self._load_texture,
            "noise_context": self._noise_context,
        }
        ev = GraphEvaluator(graph, ctx, NODE_REGISTRY)
        field = ev.eval_output("output", 0)
        return np.asarray(field, dtype=np.float32)

    def _load_texture(self, path: str) -> np.ndarray:
        """带 LRU 的高精度贴图解码。"""
        return load_rgb_float(path, self._cache)

    @staticmethod
    def _uv_to_xyz(projection, u, v):
        from .projections import uv_to_xyz
        return uv_to_xyz(projection, u, v)


# 暴露给主程序(避免直接 import .compose,稍微轻一点)
__all__ = ["RenderWorker", "render"]

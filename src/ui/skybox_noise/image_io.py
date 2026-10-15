"""Skybox 的高精度图像桥接。

所有入口复用应用公共 I/O，缓存中保存原始 dtype；渲染前才转换为 float32，
从而避免 Pillow ``convert('RGB')`` 对 16-bit/EXR 的静默量化。
"""
from __future__ import annotations

import numpy as np

from src.core.file_cache import FileCache
from src.core.pixels import normalized_float
from src.io.loader import load_image


def ensure_rgb(array: np.ndarray) -> np.ndarray:
    """把灰度/RGB/RGBA 转为保留 dtype 的三通道 RGB。"""
    array = np.asarray(array)
    if array.ndim == 2:
        return np.ascontiguousarray(np.repeat(array[..., None], 3, axis=-1))
    if array.ndim == 3 and array.shape[-1] in (3, 4):
        return np.ascontiguousarray(array[..., :3])
    raise ValueError(f"Skybox 只支持灰度/RGB/RGBA，收到 {array.shape}")


def load_rgb_array(path: str, cache: FileCache | None = None) -> np.ndarray:
    """读取并返回保留源位深的 RGB 数组。"""
    if cache is not None:
        cached = cache.get(path, "SKYBOX_RGB", 0, 0)
        if cached is not None:
            return cached
    rgb = ensure_rgb(load_image(path))
    if cache is not None:
        cache.put(path, "SKYBOX_RGB", 0, 0, rgb)
    return rgb


def load_rgb_float(path: str, cache: FileCache | None = None) -> np.ndarray:
    """读取为渲染使用的 float32 RGB；浮点 HDR 值不会裁到 0..1。"""
    rgb = load_rgb_array(path, cache)
    return np.ascontiguousarray(normalized_float(rgb), dtype=np.float32)


__all__ = ["ensure_rgb", "load_rgb_array", "load_rgb_float"]

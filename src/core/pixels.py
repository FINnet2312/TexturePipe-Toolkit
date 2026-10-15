"""像素位深与显示转换的公共工具。

处理管线支持 uint8、uint16 和浮点 EXR。整数白点是 dtype 最大值，
浮点数据贴图以 1.0 为白点；无编辑的 EXR 转换不会裁掉 HDR 值。
"""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def validate_pixel_array(arr: np.ndarray) -> np.ndarray:
    if not isinstance(arr, np.ndarray):
        raise TypeError("像素数据必须是 numpy.ndarray")
    if arr.dtype.kind not in ("u", "f"):
        raise ValueError(f"不支持的像素 dtype: {arr.dtype}")
    if arr.dtype.kind == "u" and arr.dtype.itemsize not in (1, 2, 4):
        raise ValueError(f"不支持的无符号整数位深: {arr.dtype}")
    if arr.dtype.kind == "f" and arr.dtype.itemsize not in (2, 4, 8):
        raise ValueError(f"不支持的浮点位深: {arr.dtype}")
    return arr


def full_scale(dtype_or_array) -> float | int:
    """返回该 dtype 的白点：整数最大值，浮点为 1.0。"""
    dtype = (
        dtype_or_array.dtype
        if isinstance(dtype_or_array, np.ndarray)
        else np.dtype(dtype_or_array)
    )
    if dtype.kind == "u":
        return int(np.iinfo(dtype).max)
    if dtype.kind == "f":
        return 1.0
    raise ValueError(f"不支持的像素 dtype: {dtype}")


def normalized_float(arr: np.ndarray) -> np.ndarray:
    """转成 float32 标准值；整数映射至 0..1，浮点值原样保留。"""
    validate_pixel_array(arr)
    out = arr.astype(np.float32, copy=False)
    if arr.dtype.kind == "u":
        out = out / float(full_scale(arr.dtype))
    return out


def from_normalized(values: np.ndarray, dtype, *, clip: bool = True) -> np.ndarray:
    """把标准值恢复到目标 dtype，不降低整数位深。"""
    dtype = np.dtype(dtype)
    values = np.asarray(values, dtype=np.float32)
    if dtype.kind == "f":
        if clip:
            values = np.clip(values, 0.0, 1.0)
        return values.astype(dtype)
    if dtype.kind == "u":
        if clip:
            values = np.clip(values, 0.0, 1.0)
        return np.rint(values * float(full_scale(dtype))).astype(dtype)
    raise ValueError(f"不支持的目标像素 dtype: {dtype}")


def convert_dtype(arr: np.ndarray, dtype) -> np.ndarray:
    """按归一化含义转换位深，例如 uint8 255 → uint16 65535。"""
    dtype = np.dtype(dtype)
    if arr.dtype == dtype:
        return arr.copy()
    return from_normalized(normalized_float(arr), dtype, clip=False)


def common_pixel_dtype(arrays: Iterable[np.ndarray]) -> np.dtype:
    """选择能容纳所有输入的管线 dtype。浮点优先，其次最高位宽整数。"""
    dtypes = [np.asarray(arr).dtype for arr in arrays if arr is not None]
    if not dtypes:
        return np.dtype(np.uint8)
    for dtype in dtypes:
        validate_pixel_array(np.empty((0,), dtype=dtype))
    if any(dtype.kind == "f" for dtype in dtypes):
        return np.dtype(np.float32)
    return max(dtypes, key=lambda dtype: dtype.itemsize)


def white_array(shape, dtype) -> np.ndarray:
    return np.full(shape, full_scale(dtype), dtype=dtype)


def invert_values(arr: np.ndarray) -> np.ndarray:
    """按位深执行反相：255-x / 65535-x / 1.0-x。"""
    return (full_scale(arr.dtype) - arr).astype(arr.dtype, copy=False)


def scalar_from_u8(value: int, dtype) -> float | int:
    """把 UI/CLI 的 0..255 常量映射到目标位深。"""
    value = max(0, min(255, int(value)))
    normalized = value / 255.0
    dtype = np.dtype(dtype)
    if dtype.kind == "f":
        return float(normalized)
    return int(round(normalized * float(full_scale(dtype))))


def to_display_u8(arr: np.ndarray) -> np.ndarray:
    """生成 Qt 预览用8-bit副本，不改变高精度母版。"""
    values = normalized_float(arr)
    values = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0)
    return np.rint(np.clip(values, 0.0, 1.0) * 255.0).astype(np.uint8)

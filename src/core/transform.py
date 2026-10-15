"""几何变换，保持 uint8、uint16 与浮点像素精度。"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image

from .pixels import validate_pixel_array


def normalize_angle(angle_degrees: float) -> float:
    """把角度规整到 [-180, 180]，并消除接近整数的浮点误差。"""
    angle = (float(angle_degrees) + 180.0) % 360.0 - 180.0
    rounded = round(angle)
    return float(rounded) if math.isclose(angle, rounded, abs_tol=1e-7) else angle


def _restore_dtype(values: np.ndarray, dtype: np.dtype) -> np.ndarray:
    dtype = np.dtype(dtype)
    if dtype.kind == "u":
        info = np.iinfo(dtype)
        return np.rint(np.clip(values, 0, info.max)).astype(dtype)
    return values.astype(dtype, copy=False)


def _rotate_plane(plane: np.ndarray, angle: float, resample: Image.Resampling) -> np.ndarray:
    pil = Image.fromarray(plane.astype(np.float32, copy=False), mode="F")
    rotated = pil.rotate(angle, resample=resample, expand=True, fillcolor=0.0)
    return _restore_dtype(np.asarray(rotated), plane.dtype)


def rotate_image(
    arr: np.ndarray,
    angle_degrees: float,
    *,
    resample: Image.Resampling = Image.Resampling.BICUBIC,
) -> np.ndarray:
    """逆时针旋转并扩展画布，不裁切图像。

    90° 的整数倍走 ``np.rot90``，因此不会插值或损失原始像素。
    其他角度逐通道以 Pillow 的 32-bit 浮点模式插值，再恢复输入 dtype。
    """
    validate_pixel_array(arr)
    angle = normalize_angle(angle_degrees)
    if angle == 0:
        return arr.copy()

    quarter_turns = angle / 90.0
    if math.isclose(quarter_turns, round(quarter_turns), abs_tol=1e-7):
        return np.rot90(arr, k=int(round(quarter_turns))).copy()

    if arr.ndim == 2:
        return _rotate_plane(arr, angle, resample)
    planes = [_rotate_plane(arr[..., index], angle, resample) for index in range(arr.shape[2])]
    return np.stack(planes, axis=2)


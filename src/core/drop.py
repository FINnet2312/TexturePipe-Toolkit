"""
drop — 把 RGBA 某一通道清成 0 或 255。

典型用法:导出的 PNG A 通道是无效数据,用 255 填掉,避免 UE 误用。
"""
from __future__ import annotations

import numpy as np

from .pixels import scalar_from_u8

def drop_channel(arr_hwc: np.ndarray, channel: str, fill: int = 255) -> np.ndarray:
    """把指定通道清成 fill(默认 255)。

    Args:
        arr_hwc: H×W×4 uint8
        channel: R / G / B / A
        fill: 0..255
    """
    if arr_hwc.ndim != 3 or arr_hwc.shape[-1] != 4:
        raise ValueError(f"drop_channel expects H×W×4, got {arr_hwc.shape}")
    ch = channel.upper()
    if ch not in ("R", "G", "B", "A"):
        raise ValueError(f"channel must be R/G/B/A, got {channel!r}")
    out = arr_hwc.copy()
    idx = {"R": 0, "G": 1, "B": 2, "A": 3}[ch]
    out[..., idx] = scalar_from_u8(fill, out.dtype)
    return out

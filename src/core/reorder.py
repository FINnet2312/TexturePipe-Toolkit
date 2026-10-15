"""
reorder — RGBA 通道重排。

支持 4! = 24 种排列,用户用 4 字符字符串指定目标顺序,如 "ABGR"。
"""
from __future__ import annotations

import numpy as np


def reorder_rgba(arr_hwc: np.ndarray, order: str) -> np.ndarray:
    """按 order 重新排列 4 通道。

    Args:
        arr_hwc: H×W×4 uint8
        order: 4 字符,每个字符 ∈ {R, G, B, A};第 i 个字符表示"目标第 i 通道
            取自源哪个通道"。例: "ABGR" → 目标 R=A, G=B, B=G, A=R。

    Returns:
        H×W×4 uint8
    """
    if arr_hwc.ndim != 3 or arr_hwc.shape[-1] != 4:
        raise ValueError(f"reorder_rgba expects H×W×4, got {arr_hwc.shape}")
    order = order.upper()
    if len(order) != 4 or set(order) != {"R", "G", "B", "A"}:
        raise ValueError(f"order 必须是 RGBA 的一个排列,如 'ABGR', got {order!r}")
    idx_map = {"R": 0, "G": 1, "B": 2, "A": 3}
    src_indices = [idx_map[c] for c in order]
    out = np.stack([arr_hwc[..., i] for i in src_indices], axis=-1)
    return out.copy()

"""
invert — 通道取反(255 - x)。

支持对 RGBA 数组的指定通道取反,或对 ChannelSlot 取反。
"""
from __future__ import annotations

import numpy as np

from .pixels import invert_values

def invert_rgba(arr_hwc: np.ndarray, channels: str = "RGBA") -> np.ndarray:
    """对 RGBA 数组的指定通道取反。

    Args:
        arr_hwc: H×W×4 uint8
        channels: 取哪些通道,例 "G" / "RGB" / "A";默认全取
    """
    if arr_hwc.ndim != 3 or arr_hwc.shape[-1] != 4:
        raise ValueError(f"invert_rgba expects H×W×4, got {arr_hwc.shape}")
    ch_set = set(channels.upper())
    if not ch_set.issubset({"R", "G", "B", "A"}):
        raise ValueError(f"channels must be subset of RGBA, got {channels!r}")
    out = arr_hwc.copy()
    for c in ch_set:
        idx = {"R": 0, "G": 1, "B": 2, "A": 3}[c]
        out[..., idx] = invert_values(out[..., idx])
    return out


def invert_slot(slot) -> None:
    """对单个 ChannelSlot 切换 token 的反相状态。"""
    from .slot import ChannelToken

    pairs = {
        ChannelToken.R: ChannelToken.INV_R,
        ChannelToken.G: ChannelToken.INV_G,
        ChannelToken.B: ChannelToken.INV_B,
        ChannelToken.A: ChannelToken.INV_A,
        ChannelToken.INV_R: ChannelToken.R,
        ChannelToken.INV_G: ChannelToken.G,
        ChannelToken.INV_B: ChannelToken.B,
        ChannelToken.INV_A: ChannelToken.A,
        ChannelToken.BLACK: ChannelToken.WHITE,
        ChannelToken.WHITE: ChannelToken.BLACK,
    }
    slot.token = pairs[slot.token]
    if slot.data is not None:
        slot.data = invert_values(slot.data)
    if slot.source_data is not None:
        slot.source_data = invert_values(slot.source_data)

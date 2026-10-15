"""
packer — ChannelMap → H×W×4 RGBA 数组，保留最高输入精度。

不写盘,只产出 numpy 数组(给 saver 落盘或给 UI 预览)。
"""
from __future__ import annotations

import numpy as np

from .map import ChannelMap
from .pixels import common_pixel_dtype, convert_dtype, full_scale


def pack_rgba(m: ChannelMap) -> np.ndarray:
    """把 4 个槽的 data 拼成 H×W×4 数组。

    - 槽空(无 data)→ 该位深的白点（255 / 65535 / 1.0）
    - 各槽形状不一致时,按各槽自身的 shape 拼接(要求 loader 已按 spec 对齐)
    - 颜色空间不在这里处理(由 saver 在写盘时编码)
    """
    h, w = None, None
    for _, s in m.slots():
        if s.data is not None:
            h, w = s.data.shape
            break
    if h is None:
        raise ValueError("ChannelMap 全空,无法 pack")

    dtype = common_pixel_dtype(
        s.data for _, s in m.slots() if s.data is not None
    )
    out = np.full((h, w, 4), full_scale(dtype), dtype=dtype)
    for i, (_, s) in enumerate(m.slots()):
        if s.data is None:
            continue
        if s.data.shape != (h, w):
            raise ValueError(
                f"通道 {s.semantic} 形状 {s.data.shape} 与目标 {(h, w)} 不一致"
            )
        out[..., i] = convert_dtype(s.data, dtype)
    return out

"""
unpacker — H×W×4 RGBA 数组 → ChannelMap(4 槽填满)，保持 dtype。

可与"源格式"配合使用:告知工具"这张图是 ORM / RMA / ROM ..."
工具会按源格式把 4 个通道填到对应的 semantic 槽里。
"""
from __future__ import annotations

import numpy as np

from .map import ChannelMap
from .slot import ChannelSlot, ColorSpace, Semantic, SourceType


def unpack_rgba(arr_hwc: np.ndarray, semantics: list[Semantic] | None = None,
                color_space: ColorSpace = ColorSpace.LINEAR) -> ChannelMap:
    """把 H×W×4 RGBA 拆回 ChannelMap。

    Args:
        arr_hwc: H×W×4 uint8/uint16/float 数组
        semantics: [R 槽 semantic, G 槽 semantic, B 槽 semantic, A 槽 semantic]
            默认全 EMPTY
        color_space: 拆出来的通道颜色空间

    Returns:
        ChannelMap,4 槽均填好 data
    """
    if arr_hwc.ndim != 3 or arr_hwc.shape[-1] != 4:
        raise ValueError(f"unpack_rgba expects H×W×4, got {arr_hwc.shape}")

    sems = semantics or [Semantic.EMPTY] * 4
    if len(sems) != 4:
        raise ValueError("semantics 长度必须为 4")

    cm = ChannelMap()
    for i, ((name, slot), sem) in enumerate(zip(cm.slots(), sems)):
        s: ChannelSlot = slot
        s.semantic = sem
        s.source_type = SourceType.EXTRACTED
        s.color_space = color_space
        s.data = arr_hwc[..., i].copy()
        s.source_data = s.data.copy()
    return cm

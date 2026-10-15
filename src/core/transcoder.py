"""
transcoder — 按 token 模型把源图按 4 个 token 打包成新图。

工作流:
    src_arr (H×W×4) + 4 tokens + remove_alpha → packed (H×W×3/4)，保持 dtype

对齐 UEToolbox 的 services/texture_channels.py::convert_image 风格。
每个 token 决定"目标 R/G/B/A 槽各自从源图取哪通道(可 invert / BLACK / WHITE)"。
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from .pixels import full_scale, invert_values, white_array
from .slot import ChannelToken


_PHYSICAL_TOKENS = (
    ChannelToken.R,
    ChannelToken.G,
    ChannelToken.B,
    ChannelToken.A,
)


def _token_for(channel: str, inverted: bool = False) -> ChannelToken:
    prefix = "INV_" if inverted else ""
    return ChannelToken.from_str(prefix + channel)


def compose_token_mappings(
    src_mapping: Sequence[ChannelToken],
    dst_mapping: Sequence[ChannelToken],
) -> tuple[ChannelToken, ChannelToken, ChannelToken, ChannelToken]:
    """组合"规范→源格式"与"规范→目标格式"映射。

    返回的 4 个 token 可直接作用于物理源图。源格式没有携带的规范通道
    使用 WHITE 补齐。若源、目标映射相同则返回物理 identity,保证同格式
    转换像素不变。
    """
    if len(src_mapping) != 4 or len(dst_mapping) != 4:
        raise ValueError("src_mapping / dst_mapping 长度必须均为 4")
    if tuple(src_mapping) == tuple(dst_mapping):
        return _PHYSICAL_TOKENS

    # canonical channel -> 从物理源图哪个通道可还原
    decode: dict[str, ChannelToken] = {}
    for physical, encoded in zip("RGBA", src_mapping):
        base = encoded.base_channel()
        if base is None or base in decode:
            continue
        decode[base] = _token_for(physical, encoded.is_inverted())

    composed: list[ChannelToken] = []
    for wanted in dst_mapping:
        if wanted.is_solid():
            composed.append(wanted)
            continue
        base = wanted.base_channel()
        recovered = decode.get(base or "", ChannelToken.WHITE)
        if recovered.is_solid():
            composed.append(recovered)
            continue
        inverted = recovered.is_inverted() ^ wanted.is_inverted()
        composed.append(_token_for(recovered.base_channel() or "R", inverted))
    return tuple(composed)  # type: ignore[return-value]


def transcode_between_presets(src: np.ndarray, src_preset, dst_preset) -> np.ndarray:
    """按源/目标 ChannelPreset 完成真正的格式互转。"""
    mapping = compose_token_mappings(src_preset.mapping, dst_preset.mapping)
    return transcode_rgba(src, mapping, remove_alpha=dst_preset.remove_alpha)


def _channel_from_token(rgba: np.ndarray, token: ChannelToken) -> np.ndarray:
    """按 token 从 H×W×4 源图取一通道(可 invert / 替换 BLACK/WHITE)。

    rgba 必须是 H×W×4 的受支持像素 dtype。
    """
    if not rgba.ndim == 3 or rgba.shape[-1] != 4:
        raise ValueError(f"_channel_from_token expects H×W×4, got {rgba.shape}")

    if token is ChannelToken.BLACK:
        return np.zeros(rgba.shape[:2], dtype=rgba.dtype)
    if token is ChannelToken.WHITE:
        return white_array(rgba.shape[:2], rgba.dtype)

    base = token.base_channel()
    if base is None:
        raise ValueError(f"未知 token: {token!r}")
    if base == "A" and rgba.shape[-1] < 4:
        # 源图没有 alpha → 视为全 255
        ch = white_array(rgba.shape[:2], rgba.dtype)
    else:
        idx = {"R": 0, "G": 1, "B": 2, "A": 3}[base]
        ch = rgba[..., idx]
    if token.is_inverted():
        ch = invert_values(ch)
    return ch


def transcode_rgba(
    src: np.ndarray,
    mapping: Sequence[ChannelToken],
    remove_alpha: bool = True,
) -> np.ndarray:
    """把 H×W×4 源图按 4 token 打包成新图。

    Args:
        src: H×W×4 源图(若是 H×W / H×W×3,会先升到 H×W×4)
        mapping: 4 个 token,描述目标 R/G/B/A 槽各从源图取哪通道
        remove_alpha: True → 输出 H×W×3 (RGB),False → H×W×4 (RGBA)

    Returns:
        H×W×3 或 H×W×4，dtype 与源图一致
    """
    if len(mapping) != 4:
        raise ValueError(f"mapping 长度必须为 4,got {len(mapping)}")

    # 升到 RGBA
    if src.ndim == 2:
        rgba = np.zeros(src.shape + (4,), dtype=src.dtype)
        rgba[..., 0] = src
        rgba[..., 3] = full_scale(src.dtype)
    elif src.ndim == 3 and src.shape[-1] == 3:
        rgba = np.zeros(src.shape[:2] + (4,), dtype=src.dtype)
        rgba[..., :3] = src
        rgba[..., 3] = full_scale(src.dtype)
    else:
        rgba = src

    bands = [_channel_from_token(rgba, t) for t in mapping]
    if remove_alpha:
        return np.stack(bands[:3], axis=-1)  # H×W×3
    return np.stack(bands, axis=-1)  # H×W×4


# 旧接口保留(单 source RGBA → 4 槽的 ChannelMap,带 semantic)-----------------
def transcode_map(src: np.ndarray, src_format, dst_format, color_space=None):
    """旧 API:按 semantic 解析源 + 重新打包(保留向后兼容)。

    推荐新代码直接用 transcode_rgba(token 列表)。
    """
    from .unpacker import unpack_rgba
    from .slot import ColorSpace, Semantic

    src_map = unpack_rgba(
        src, src_format, color_space=color_space or ColorSpace.LINEAR,
    )
    out = np.full(
        src.shape[:2] + (4,),
        full_scale(src.dtype),
        dtype=src.dtype,
    )
    for i, dst_sem in enumerate(dst_format):
        if dst_sem is Semantic.EMPTY:
            continue
        found = src_map.find_by_semantic(dst_sem)
        if found is None:
            continue
        _, src_slot = found
        if src_slot.data is None:
            continue
        out[..., i] = src_slot.data
    return out

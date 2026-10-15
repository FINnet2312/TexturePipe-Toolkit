"""
presets — 13 个内置打包预设。

约定:
- 规范中间布局为 ORMH:R=AO,G=Roughness,B=Metallic,A=辅助数据(Height/Detail)
- preset.mapping 描述"从规范 ORMH 编码成该格式时,目标 R/G/B/A 各取哪个规范通道"
- 任意源→目标转换由 transcoder.compose_token_mappings 组合源解码和目标编码

例子(以 ORM 排布的源:R=AO=11, G=Rough=22, B=Metal=33 为参考):
- ORM: 目标 R=AO, G=Rough, B=Metal, A=empty → mapping = (R, G, B, A)(identity)
- RMA: 目标 R=Rough(22), G=Metal(33), B=AO(11) → mapping = (G, B, R, A)
- MRA: 目标 R=Metal(33), G=Rough(22), B=AO(11) → mapping = (B, G, R, A)
- ROM: 目标 R=Rough(22), G=AO(11), B=Metal(33), A=empty = (G, R, B, A)
- ORMH: 同 ORM 但保留 A → mapping = (R, G, B, A), remove_alpha=False
- ORDp: 目标 R=AO(11), G=Rough(22), B=empty(0), A=Disp(B=源 B) → mapping = (R, G, BLACK, B)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .slot import ChannelToken


@dataclass(frozen=True)
class ChannelPreset:
    id: str
    label: str
    mapping: Tuple[ChannelToken, ChannelToken, ChannelToken, ChannelToken]
    remove_alpha: bool = True
    suffix: str = "_ORM"


# 13 个预设
PRESETS: tuple[ChannelPreset, ...] = (
    ChannelPreset(
        "orm", "ORM / ARM (R=AO, G=粗糙度, B=金属度)",
        (ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A),
        suffix="_ORM",
    ),
    ChannelPreset(
        "rom", "ROM (R=粗糙度, G=AO, B=金属度)",
        (ChannelToken.G, ChannelToken.R, ChannelToken.B, ChannelToken.A),
        suffix="_ROM",
    ),
    ChannelPreset(
        "rma", "RMA (R=粗糙度, G=金属度, B=AO)",
        (ChannelToken.G, ChannelToken.B, ChannelToken.R, ChannelToken.A),
        suffix="_RMA",
    ),
    ChannelPreset(
        "mra", "MRA (R=金属度, G=粗糙度, B=AO)",
        (ChannelToken.B, ChannelToken.G, ChannelToken.R, ChannelToken.A),
        suffix="_MRA",
    ),
    ChannelPreset(
        "unity_mask", "Unity HDRP Mask Map (R=Metal, G=AO, B=DetailMask, A=Smoothness)",
        (ChannelToken.B, ChannelToken.R, ChannelToken.A, ChannelToken.INV_G),
        remove_alpha=False, suffix="_MaskMap",
    ),
    ChannelPreset(
        "unity_standard", "Unity Standard (R=Metallic, G=any, B=any, A=Smoothness)",
        (ChannelToken.B, ChannelToken.WHITE, ChannelToken.WHITE, ChannelToken.INV_G),
        remove_alpha=False, suffix="_MetallicSmoothness",
    ),
    ChannelPreset(
        "gltf", "glTF Packed (R=AO, G=粗糙度, B=金属度)",
        (ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A),
        suffix="_ORM",
    ),
    ChannelPreset(
        "gltf_no_ao", "glTF 无 AO (G=粗糙度, B=金属度)",
        (ChannelToken.WHITE, ChannelToken.G, ChannelToken.B, ChannelToken.A),
        suffix="_MR",
    ),
    ChannelPreset(
        "ormh", "ORMH (A=高度,保留 alpha)",
        (ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A),
        remove_alpha=False, suffix="_ORMH",
    ),
    ChannelPreset(
        "rmah", "RMAH (A=高度,保留 alpha)",
        (ChannelToken.G, ChannelToken.B, ChannelToken.R, ChannelToken.A),
        remove_alpha=False, suffix="_RMAH",
    ),
    ChannelPreset(
        "mrah", "MRAH (A=高度,保留 alpha)",
        (ChannelToken.B, ChannelToken.G, ChannelToken.R, ChannelToken.A),
        remove_alpha=False, suffix="_MRAH",
    ),
    ChannelPreset(
        "ordp", "ORDp (B=位移, A 通道保留位移)",
        (ChannelToken.R, ChannelToken.G, ChannelToken.BLACK, ChannelToken.B),
        remove_alpha=False, suffix="_ORDp",
    ),
    ChannelPreset(
        "custom", "自定义通道映射",
        (ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A),
        remove_alpha=True, suffix="_Packed",
    ),
)

PRESET_BY_ID: dict[str, ChannelPreset] = {p.id: p for p in PRESETS}


def get_preset(preset_id: str) -> ChannelPreset:
    try:
        return PRESET_BY_ID[str(preset_id)]
    except KeyError as exc:
        raise ValueError(f"未知 preset: {preset_id!r};可选 {[p.id for p in PRESETS]}") from exc


# 已知打包后缀(供 derive_output_name 识别替换)
KNOWN_PACKED_SUFFIXES: tuple[str, ...] = (
    "_MetallicSmoothness",
    "_MaskMap",
    "_GLTF",
    "_MR",
    "_ORMH",
    "_RMAH",
    "_MRAH",
    "_ORDp",
    "_ORM",
    "_ARM",
    "_ROM",
    "_RMA",
    "_MRA",
)

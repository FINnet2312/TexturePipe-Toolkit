"""core 包 — 通道编辑器的纯逻辑核心(无 UI 依赖)。"""

from .slot import (
    ChannelSlot,
    ChannelToken,
    ColorSpace,
    Semantic,
    SourceType,
)
from .output_spec import (
    OutputSpec,
    PotStrategy,
    ResizeFilter,
    ResizeMode,
    SizePreset,
)
from .map import ChannelMap
from . import colorspace
from . import resize
from .presets import (
    ChannelPreset,
    PRESETS,
    PRESET_BY_ID,
    get_preset,
    KNOWN_PACKED_SUFFIXES,
)
from .naming import (
    validate_output_suffix,
    derive_output_name,
    derive_output_path,
)
from .packer import pack_rgba
from .unpacker import unpack_rgba
from .reorder import reorder_rgba
from .drop import drop_channel
from .invert import invert_rgba
from .transcoder import (
    compose_token_mappings,
    transcode_between_presets,
    transcode_rgba,
    transcode_map,
)
from .transform import normalize_angle, rotate_image

__all__ = [
    # 数据类
    "ChannelSlot",
    "ChannelToken",
    "ColorSpace",
    "Semantic",
    "SourceType",
    "OutputSpec",
    "PotStrategy",
    "ResizeFilter",
    "ResizeMode",
    "SizePreset",
    "ChannelMap",
    # 工具模块
    "colorspace",
    "resize",
    # 预设与命名
    "ChannelPreset",
    "PRESETS",
    "PRESET_BY_ID",
    "get_preset",
    "KNOWN_PACKED_SUFFIXES",
    "validate_output_suffix",
    "derive_output_name",
    "derive_output_path",
    # 算法
    "pack_rgba",
    "unpack_rgba",
    "reorder_rgba",
    "drop_channel",
    "invert_rgba",
    "transcode_rgba",
    "compose_token_mappings",
    "transcode_between_presets",
    "transcode_map",
    "normalize_angle",
    "rotate_image",
]

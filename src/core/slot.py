"""
ChannelSlot — 单个通道槽的核心数据类。

v2 模型(token 化):
- `token` 描述"从源图哪个 channel 取,要不要 invert,要不要替换成 BLACK/WHITE"
- 一个 ChannelSlot 仍然代表"目标 R/G/B/A 位置之一"
- 但 token 决定了它"从源图怎么来"

支持 token:
    R / G / B / A        — 直接取源图对应通道
    INV_R / INV_G / INV_B / INV_A — 取对应通道并取反
    BLACK                — 全 0(8bit: 0)
    WHITE                — 全 255(8bit: 255)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import numpy as np


# ---------------------------------------------------------------------------
# ChannelToken(通道 + transform)
# ---------------------------------------------------------------------------
class ChannelToken(Enum):
    """从源贴图取一个通道的描述(可叠加 invert / 替换)。"""

    R = "R"
    G = "G"
    B = "B"
    A = "A"
    INV_R = "INV_R"
    INV_G = "INV_G"
    INV_B = "INV_B"
    INV_A = "INV_A"
    BLACK = "BLACK"
    WHITE = "WHITE"

    @classmethod
    def from_str(cls, s: str) -> "ChannelToken":
        s = str(s).strip().upper()
        try:
            return cls(s)
        except ValueError as exc:
            raise ValueError(
                f"未知通道 token: {s!r};可选 {list(cls.__members__.keys())}"
            ) from exc

    def is_inverted(self) -> bool:
        return self.value.startswith("INV_")

    def base_channel(self) -> Optional[str]:
        """如果 token 表示取源图某通道(直接或取反),返回该通道名;否则 None。"""
        if self.value.startswith("INV_"):
            return self.value[4:]
        if self.value in ("R", "G", "B", "A"):
            return self.value
        return None  # BLACK / WHITE

    def is_solid(self) -> bool:
        return self in (ChannelToken.BLACK, ChannelToken.WHITE)


# ---------------------------------------------------------------------------
# Semantic(通道语义,roughness/metallic/ao/...)
# ---------------------------------------------------------------------------
class Semantic(Enum):
    """通道语义标签。决定该通道数据代表什么(roughness/metallic/ao...)。"""

    EMPTY = "empty"
    ROUGHNESS = "roughness"
    METALLIC = "metallic"
    AO = "ao"
    HEIGHT = "height"
    CAVITY = "cavity"
    OPACITY = "opacity"
    DETAIL_MASK = "detail_mask"
    CURVATURE = "curvature"
    THICKNESS = "thickness"
    BASECOLOR_R = "basecolor_r"
    BASECOLOR_G = "basecolor_g"
    BASECOLOR_B = "basecolor_b"
    BASECOLOR_A = "basecolor_a"
    EMISSIVE_R = "emissive_r"
    EMISSIVE_G = "emissive_g"
    EMISSIVE_B = "emissive_b"

    @classmethod
    def data_channels(cls) -> list[Semantic]:
        return [s for s in cls if s is not cls.EMPTY]

    @classmethod
    def default_color_space(cls, sem: Semantic) -> ColorSpace:
        if sem in (cls.BASECOLOR_R, cls.BASECOLOR_G, cls.BASECOLOR_B,
                   cls.BASECOLOR_A, cls.EMISSIVE_R, cls.EMISSIVE_G, cls.EMISSIVE_B):
            return ColorSpace.SRGB
        return ColorSpace.LINEAR


# ---------------------------------------------------------------------------
# ColorSpace
# ---------------------------------------------------------------------------
class ColorSpace(Enum):
    """颜色空间。SRGB 用于 albedo/emissive 类,LINEAR 用于数据贴图。"""

    SRGB = "sRGB"
    LINEAR = "Linear"


# ---------------------------------------------------------------------------
# SourceType
# ---------------------------------------------------------------------------
class SourceType(Enum):
    """通道内容的来源类型。"""

    EMPTY = "empty"
    FILE = "file"
    SOLID = "solid"
    EXTRACTED = "extracted"


# ---------------------------------------------------------------------------
# ChannelSlot
# ---------------------------------------------------------------------------
@dataclass
class ChannelSlot:
    """单个通道槽。

    Attributes:
        semantic: 该通道代表的语义(roughness/metallic/ao/...)。
        display_name: 用户可见名。
        source_type: 数据来源。
        file_path: 当 source_type=FILE 时的源文件路径。
        token: 从源文件取哪一通道(可叠加 invert / BLACK / WHITE)。
        solid_value: 当 source_type=SOLID 时的填充值(0-255)。
        color_space: 颜色空间。
        data: 最终像素(H×W uint8),已应用 token。color_space 仅作语义标签。
        source_data: 原始像素(token 之前)。
    """

    semantic: Semantic = Semantic.EMPTY
    display_name: str = ""
    source_type: SourceType = SourceType.EMPTY
    file_path: Optional[Path] = None
    token: ChannelToken = ChannelToken.R
    solid_value: int = 0
    color_space: ColorSpace = ColorSpace.LINEAR

    data: Optional[np.ndarray] = field(default=None, repr=False, compare=False)
    source_data: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    # --- 便捷 ---------------------------------------------------------
    def is_empty(self) -> bool:
        return self.source_type is SourceType.EMPTY or self.data is None

    def shape(self) -> Optional[tuple[int, int]]:
        return None if self.data is None else self.data.shape

    def apply_post(self) -> None:
        """把已完成 token 提取的 source_data 设为最终 data。

        8bit 打包贴图不自动做 gamma 转换;color_space 只记录导入器应如何解释
        该通道,避免对数据贴图二次编码。
        """
        if self.source_data is None:
            self.data = None
            return
        out = self.source_data
        # 注意:source_data 已经是 token 处理后的"该槽对应通道"的灰度数据
        # 颜色空间仅作元数据;byte 值保持不变。
        self.data = out

    def to_dict(self) -> dict:
        return {
            "semantic": self.semantic.value,
            "display_name": self.display_name,
            "source_type": self.source_type.value,
            "file_path": str(self.file_path) if self.file_path else None,
            "token": self.token.value,
            "solid_value": self.solid_value,
            "color_space": self.color_space.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelSlot":
        return cls(
            semantic=Semantic(d.get("semantic", "empty")),
            display_name=d.get("display_name", ""),
            source_type=SourceType(d.get("source_type", "empty")),
            file_path=Path(d["file_path"]) if d.get("file_path") else None,
            token=ChannelToken.from_str(d.get("token", "R")),
            solid_value=int(d.get("solid_value", 0)),
            color_space=ColorSpace(d.get("color_space", "Linear")),
        )

    # --- 工厂方法 -----------------------------------------------------
    @classmethod
    def from_file(cls, path: Union[str, Path], token: ChannelToken = ChannelToken.R,
                  semantic: Semantic = Semantic.EMPTY,
                  display_name: str = "",
                  color_space: Optional[ColorSpace] = None) -> "ChannelSlot":
        s = cls(
            semantic=semantic,
            display_name=display_name or (path if isinstance(path, str) else str(path)),
            source_type=SourceType.FILE,
            file_path=Path(path),
            token=token,
            color_space=color_space if color_space is not None else Semantic.default_color_space(semantic),
        )
        return s

    @classmethod
    def from_solid(cls, value: int, semantic: Semantic = Semantic.EMPTY,
                   display_name: str = "(solid)") -> "ChannelSlot":
        v = max(0, min(255, int(value)))
        s = cls(
            semantic=semantic,
            display_name=display_name,
            source_type=SourceType.SOLID,
            solid_value=v,
            color_space=Semantic.default_color_space(semantic),
        )
        s.data = np.full((1, 1), v, dtype=np.uint8)
        s.source_data = s.data.copy()
        return s

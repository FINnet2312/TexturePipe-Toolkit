"""
OutputSpec — 输出规格(尺寸、resize 模式、滤镜、POT 策略)。

分辨率是"输出"的属性,不属于任一通道。源图分辨率不一时,统一按 resize_mode 处理再打包。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 尺寸档位
# ---------------------------------------------------------------------------
class SizePreset(Enum):
    """常用尺寸档位(方形)。"""

    CUSTOM = "custom"
    P512 = "512"
    P1K = "1K"
    P2K = "2K"
    P4K = "4K"
    P8K = "8K"

    def pixels(self) -> Optional[int]:
        return {
            SizePreset.P512: 512,
            SizePreset.P1K: 1024,
            SizePreset.P2K: 2048,
            SizePreset.P4K: 4096,
            SizePreset.P8K: 8192,
        }.get(self)


# ---------------------------------------------------------------------------
# Resize
# ---------------------------------------------------------------------------
class ResizeMode(Enum):
    """源图与目标尺寸不一致时的处理方式。"""

    FIT = "fit"           # 等比缩放到完全覆盖目标(可能裁切)
    FILL = "fill"         # 等比缩放到完全放入目标(可能留白)
    STRETCH = "stretch"   # 强制拉伸(不变形则失真)
    NONE = "none"         # 报错(要求手动选)


class ResizeFilter(Enum):
    """resize 滤镜算法。"""

    NEAREST = "nearest"
    BILINEAR = "bilinear"
    BICUBIC = "bicubic"
    LANCZOS = "lanczos"


class PotStrategy(Enum):
    """POT 强制对齐方向。"""

    ROUND_UP = "round_up"
    ROUND_DOWN = "round_down"
    NEAREST = "nearest"


# ---------------------------------------------------------------------------
# OutputSpec
# ---------------------------------------------------------------------------
@dataclass
class OutputSpec:
    """输出规格。

    Attributes:
        width: 输出宽
        height: 输出高
        size_preset: 尺寸档位(优先于 width/height)
        resize_mode: 源图与目标尺寸不一致时的处理
        resize_filter: resize 滤镜
        force_pot: 是否强制对齐到 2 的幂
        pot_strategy: POT 对齐方向
    """

    width: int = 2048
    height: int = 2048
    size_preset: SizePreset = SizePreset.CUSTOM
    resize_mode: ResizeMode = ResizeMode.FIT
    resize_filter: ResizeFilter = ResizeFilter.LANCZOS
    force_pot: bool = False
    pot_strategy: PotStrategy = PotStrategy.ROUND_UP

    def effective_size(self) -> tuple[int, int]:
        """返回(可能经过 POT 对齐的)最终输出尺寸 ``(width, height)``。"""
        p = self.size_preset.pixels()
        if p is not None and self.size_preset is not SizePreset.CUSTOM:
            w, h = p, p
        else:
            w, h = int(self.width), int(self.height)
        if self.force_pot:
            w = _align_pot(w, self.pot_strategy)
            h = _align_pot(h, self.pot_strategy)
        return max(1, w), max(1, h)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "size_preset": self.size_preset.value,
            "resize_mode": self.resize_mode.value,
            "resize_filter": self.resize_filter.value,
            "force_pot": self.force_pot,
            "pot_strategy": self.pot_strategy.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OutputSpec":
        return cls(
            width=int(d.get("width", 2048)),
            height=int(d.get("height", 2048)),
            size_preset=SizePreset(d.get("size_preset", "custom")),
            resize_mode=ResizeMode(d.get("resize_mode", "fit")),
            resize_filter=ResizeFilter(d.get("resize_filter", "lanczos")),
            force_pot=bool(d.get("force_pot", False)),
            pot_strategy=PotStrategy(d.get("pot_strategy", "round_up")),
        )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _align_pot(n: int, strategy: PotStrategy) -> int:
    """把 n 对齐到 2 的幂。"""
    if n <= 1:
        return 1
    import math
    if (n & (n - 1)) == 0:
        return n
    log2 = math.log2(n)
    if strategy is PotStrategy.ROUND_UP:
        return 1 << (int(log2) + 1)
    if strategy is PotStrategy.ROUND_DOWN:
        return 1 << int(log2)
    # nearest
    low = 1 << int(log2)
    high = low << 1
    return low if (n - low) <= (high - n) else high

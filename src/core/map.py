"""
ChannelMap — 4 个目标槽 R/G/B/A 的容器。

提供:
- 4 个槽的便捷访问
- semantic 索引(按语义找槽位)
- 序列化(工作区保存/加载)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional

from .slot import ChannelSlot, ChannelToken, Semantic, SourceType


@dataclass
class ChannelMap:
    """4 槽的通道映射。"""

    # 注意:每槽的默认 ChannelSlot 要按"槽位置"设默认 token,
    # 这样 ChannelMap() 创建的 4 槽分别对应 R/G/B/A 的物理位置。
    R: ChannelSlot = field(default_factory=lambda: ChannelSlot(token=ChannelToken.R))
    G: ChannelSlot = field(default_factory=lambda: ChannelSlot(token=ChannelToken.G))
    B: ChannelSlot = field(default_factory=lambda: ChannelSlot(token=ChannelToken.B))
    A: ChannelSlot = field(default_factory=lambda: ChannelSlot(token=ChannelToken.A))

    # --- 访问 ---------------------------------------------------------
    def slot(self, name: str) -> ChannelSlot:
        return getattr(self, name.upper())

    def slots(self) -> Iterator[tuple[str, ChannelSlot]]:
        for n in ("R", "G", "B", "A"):
            yield n, getattr(self, n)

    def find_by_semantic(self, sem: Semantic) -> Optional[tuple[str, ChannelSlot]]:
        """按语义找第一个匹配的槽位。"""
        for n, s in self.slots():
            if s.semantic is sem:
                return n, s
        return None

    def find_all_by_semantic(self, sem: Semantic) -> list[tuple[str, ChannelSlot]]:
        return [(n, s) for n, s in self.slots() if s.semantic is sem]

    # --- 状态 ---------------------------------------------------------
    def all_empty(self) -> bool:
        return all(s.source_type is SourceType.EMPTY for _, s in self.slots())

    def non_empty(self) -> list[tuple[str, ChannelSlot]]:
        return [(n, s) for n, s in self.slots() if not s.is_empty()]

    def common_shape(self) -> Optional[tuple[int, int]]:
        """返回第一个非空槽的 (H, W);如果全空则 None。"""
        for _, s in self.slots():
            if s.data is not None:
                return s.data.shape
        return None

    # --- 序列化 -------------------------------------------------------
    def to_dict(self) -> dict:
        return {n: s.to_dict() for n, s in self.slots()}

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelMap":
        defaults = cls()
        slots = {}
        for name in ("R", "G", "B", "A"):
            slots[name] = (
                ChannelSlot.from_dict(d[name]) if name in d
                else getattr(defaults, name)
            )
        return cls(**slots)

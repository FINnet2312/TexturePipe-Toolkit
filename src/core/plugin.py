"""Plugin 描述子 — 轻量级元数据,延迟 import 重依赖。

Plugin = 一个可被 texpipe 主窗口加载的 UI 扩展。
每个 plugin 自带一个 factory,负责返回 QWidget 实例(会被作为 Tab 嵌入)。
所有重依赖(numba / OpenEXR / ...)都应放在 plugin 自己的模块里,
主程序不会主动 import,因此 plugin 缺依赖时主程序仍能正常启动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class Plugin:
    """插件描述子。

    字段:
        id:          唯一标识(小写英文 + 下划线)
        name:        显示名(用作 Tab 标题)
        factory:     无参 callable,返回 QWidget 实例
        description: 简短描述(用于状态栏 tooltip / 关于面板)
        requires:    软依赖列表(pip 包名,用于缺包时给出友好提示)
        position:    "append" 追加到末尾,或 "prepend" 加到前面
    """

    id: str
    name: str
    factory: Callable
    description: str = ""
    requires: Tuple[str, ...] = field(default_factory=tuple)
    position: str = "append"

    def is_available(self) -> Tuple[bool, Optional[str]]:
        """检查软依赖是否就绪。返回 (是否可用, 缺失包名或 None)。"""
        for pkg in self.requires:
            try:
                __import__(pkg)
            except ImportError:
                return False, pkg
        return True, None

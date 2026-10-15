"""Plugin 注册表。

简单的内存注册:启动时调 `discover()` 把所有内置 plugin 注册进 manager,
主窗口遍历 `manager.all()` 把每个 plugin 作为一个 Tab 加载。

外部脚本也可以 `manager.register(my_plugin)` 注入自己的 plugin。
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from .plugin import Plugin


class PluginManager:
    def __init__(self) -> None:
        self._plugins: List[Plugin] = []

    def register(self, plugin: Plugin) -> None:
        if any(p.id == plugin.id for p in self._plugins):
            raise ValueError(f"Plugin id '{plugin.id}' already registered")
        self._plugins.append(plugin)

    def unregister(self, plugin_id: str) -> None:
        self._plugins = [p for p in self._plugins if p.id != plugin_id]

    def all(self) -> List[Plugin]:
        return list(self._plugins)

    def get(self, plugin_id: str) -> Optional[Plugin]:
        for p in self._plugins:
            if p.id == plugin_id:
                return p
        return None

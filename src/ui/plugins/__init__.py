"""texpipe 内置插件发现。

主程序调 `discover()` 拿到一个填好所有内置 plugin 的 PluginManager。
每个 plugin 的 import 都在这里 try/except 兜底 — 软依赖(numba 等)
就算缺了也只是这个 plugin 不出现,主程序照常启动。
"""
from __future__ import annotations

from src.core.plugin import Plugin
from src.core.plugin_manager import PluginManager


def discover() -> PluginManager:
    """扫描并注册所有内置 plugin。返回填好的 PluginManager。"""
    pm = PluginManager()

    # 1) skybox noise — 球面/盒/圆柱 投影上叠程序化噪声
    try:
        from src.ui.skybox_noise.plugin import PLUGIN as _skybox
        pm.register(_skybox)
    except Exception as exc:  # noqa: BLE001
        # 严重错误(代码本身坏),但不影响其他 plugin
        import warnings
        warnings.warn(f"[plugin] skybox_noise 注册失败: {exc}")

    return pm


__all__ = ["discover", "Plugin", "PluginManager"]

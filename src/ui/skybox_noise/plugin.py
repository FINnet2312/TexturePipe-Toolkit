"""Skybox Noise 插件描述子。

被 src/ui/plugins/discover() 调用,注册到 PluginManager。
factory 延迟 import Skybox UI；numba 只是核心内部的可选加速器，
未安装时仍加载插件并使用 NumPy fallback。
"""
from __future__ import annotations

from src.core.plugin import Plugin


def _make_widget():
    # 延迟 import：缩短不使用该功能时的主窗口模块加载链。
    from .main_window import SkyboxNoiseWidget
    return SkyboxNoiseWidget()


PLUGIN = Plugin(
    id="skybox_noise",
    name="Skybox Noise",
    description=(
        "在 equirectangular / cubemap / 圆柱投影的贴图上叠加程序化噪声\n"
        "(FBM / Caustics / Voronoi),后线程渲染,可输出 composite / mask / normal"
    ),
    factory=_make_widget,
    # 不把 numba 声明为插件门槛；core.py 已提供等价 NumPy fallback。
    requires=(),
    position="append",
)

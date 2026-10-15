"""Skybox Noise — texpipe 插件。

按识别出的投影(equirectangular / cubemap-cross / cylindrical)在 3D 单位球
上采样程序化噪声,合成输出到原图。支持 FBM / Caustics / Voronoi 三种噪声。

子模块:
    core          — Perlin / FBM / 噪声生成
    projections   — UV → 球面坐标
    compose       — 与原图合成 + 法线 / mask 计算
    worker        — QThread 后台渲染
    widgets       — 通用 UI 控件(ImageLabel / ParamSlider)
    main_window   — 主 QWidget(被 plugin 加载)

依赖:
    numpy, Pillow  (必需,跟 texpipe 共享)
    numba          (可选;提升噪声生成 25-40x,缺了走 numpy fallback)
"""

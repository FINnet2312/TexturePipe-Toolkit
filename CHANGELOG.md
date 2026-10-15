# 更新记录

本文件记录每个版本的主要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [1.0.0] - 2026-08-13

首个公开发布版本。

### 功能

- 桌面 GUI + CLI 双入口(`texpipe.bat` / `texpipe` 命令)
- 贴图通道打包 / 拆分:ORM、RMA、ROM、MRA 等多种排布互转
- 复杂编辑器:PS 风格调整(亮度/对比度/曝光/伽马/曲线)、15 种混合模式、贝塞尔曲线
- Skybox Noise 插件:equirect / cubemap-cross / 圆柱投影的程序化噪声,可视化节点图编辑器,可选 numba 加速
- 高精度 I/O:8-bit PNG/JPG、16-bit TIFF、浮点 EXR
- Windows EXE 打包(PyInstaller)

### 测试

- 150 个单元测试,覆盖核心算法、UI headless、Skybox 插件与节点图

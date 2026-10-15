# 更新记录

本文件记录每个版本的主要变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [1.1.1] - 2026-10-15

### 修复

- Skybox 冒烟脚本在非 UTF-8 控制台(如 CI 的 cp1252 环境)打印中文时 UnicodeEncodeError 崩溃,改为强制 UTF-8 输出
- 节点图点击选中测试在 CI 无桌面会话中触发 Qt 原生堆损坏(0xC0000374):`QTest.mouseClick` 的操作系统级输入注入改为直接投递 `QMouseEvent`

### 构建 / CI

- 新增 CI 工作流:push / PR 到 main 时,在 Windows + Python 3.10 / 3.11 / 3.12 上运行 150 个单元测试与 Skybox 冒烟测试
- 新增发布工作流:推送 `v*` 标签自动 PyInstaller 打包 exe、计算 sha256、创建 GitHub Release;带后缀的标签(如 `-rc.1`)自动标记为预发布

## [1.1.0] - 2026-10-15

### 功能

- 界面语言切换:菜单栏 `语言(&L)` 一键切换 中文 / English,选择持久化、下次启动自动恢复
- 覆盖编辑模式、互转模式、复杂编辑器、Skybox Noise 插件及节点图编辑器的全部界面文案(约 370 条)
- 噪声类型等功能键与显示文本分离,切换语言不影响渲染结果
- 长存的节点图编辑器对话框跟随语言切换即时刷新
- README 新增英文界面截图

### 测试

- 新增翻译 key 完整性检查(`examples/check_i18n_keys.py`,AST 解析)
- 新增中英双向切换冒烟(`examples/verify_i18n_smoke.py`)

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

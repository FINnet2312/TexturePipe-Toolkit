# 贡献指南

感谢你对 TexturePipe-Toolkit 的兴趣！以下是参与贡献的方式。

## 环境准备

- Python 3.10+
- 安装依赖：`pip install -r requirements.txt`
- 可选：`pip install numba`（Skybox Noise 噪声加速，没有也能跑）

## 运行测试

提交前请确保全部测试通过：

```bash
# 单元测试(150 个)
python -m unittest discover -s tests -q

# Skybox 冒烟测试
python examples/verify_skybox_smoke.py
```

测试默认运行在 headless(offscreen Qt)模式，无显示器也能跑。

## 代码结构

- `src/core/` — 核心算法(通道映射 / packer / unpacker / 调整管线)，不依赖 Qt
- `src/io/` — 图片加载 / 保存 / 工作区
- `src/ui/` — PySide6 桌面 GUI
- `src/ui/plugins/` — 插件发现 / 注册
- `src/cli/` — 命令行入口
- `tests/` — unittest 测试
- `examples/` — verify 脚本和测试用图

## 提交流程

1. Fork 本仓库并创建分支：`git checkout -b feature/你的功能`
2. 提交代码，commit message 用英文简述改动
3. 确保测试全部通过
4. 发起 Pull Request，描述改动动机和效果

## 报告 Bug

使用 Issue 的 Bug 模板，附上：复现步骤、期望行为、实际行为、Python 版本和操作系统。涉及 UI 的问题建议附截图。

# Texpipe Windows EXE 构建说明

工程已经按桌面软件的方式组织，可在 Windows 上构建为无需安装 Python
即可运行的 `Texpipe.exe`。构建使用独立的 `.venv-build`，不会向日常开发
环境安装打包工具。

## 环境要求

- Windows 10/11，64 位
- Python 3.10 或更新版本，64 位
- 首次构建需要联网下载依赖

PyInstaller 不能跨平台生成 Windows 程序，因此 EXE 必须在 Windows 上构建。

## 推荐：目录版

双击 `build_exe.bat`，或在 PowerShell 中运行：

```powershell
.\build_exe.ps1
```

产物位于：

```text
dist\Texpipe\Texpipe.exe
```

发布时必须复制整个 `dist\Texpipe` 文件夹。目录版启动更快，也更便于检查
Qt、OpenEXR 等原生依赖，建议作为日常发布格式。

## 可选：单文件版

```powershell
.\build_exe.ps1 -Mode onefile
```

产物位于：

```text
dist\Texpipe.exe
```

单文件版更便于传递，但每次启动都要先将 Qt 和图像编解码库解压到系统临时
目录，所以启动速度会比目录版慢。

## 构建过程做了什么

1. 创建或复用 `.venv-build` 隔离环境；
2. 安装 `requirements-build.txt` 中的运行与构建依赖；
3. 清理本工程上一次可能中断的 PyInstaller 分析缓存；
4. 根据 `texpipe.spec` 生成无控制台 Windows GUI 程序；
5. 自动启动 `Texpipe.exe --smoke-test`，验证主窗口、Qt 平台插件，以及
   16-bit PNG、16-bit TIFF、EXR 的实际读写；
6. 验证 Skybox Noise 与节点图模块已被收集，并能在无 numba 时使用 NumPy
   fallback。

重新构建但不重复安装依赖：

```powershell
.\build_exe.ps1 -SkipInstall
```

仅在排查构建环境时跳过产物自检：

```powershell
.\build_exe.ps1 -SkipSmokeTest
```

## 发布注意事项

- 当前 EXE 未做代码签名，Windows SmartScreen 可能显示“未知发布者”；
- 1.0.0 的标准发布包不捆绑 numba/LLVM，以控制体积并提高可复现性；Skybox
  Noise 在 EXE 中使用 NumPy fallback，功能可用但生成速度低于装有 numba 的
  源码版本；
- 版本号由 `src/app_info.py`、`pyproject.toml` 和
  `packaging/windows_version_info.txt`、根目录 `VERSION` 共同维护；
- 若以后加入图标，可在 `texpipe.spec` 的 `EXE` 配置中增加 `icon`；
- 不要只复制目录版的 `Texpipe.exe`，它依赖同目录下的 `_internal`。

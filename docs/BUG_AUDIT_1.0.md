# 1.0 压缩包分支 BUG 审查与修复计划

- 审查日期：2026-08-13
- 审查分支：`review/agent-1.0`
- 导入基线：`da9be1d`
- 对照分支：`main`（`9835db1`）

## 1. 导入与重叠结论

`1.0.rar` 是当前项目的同源变体，不是无关项目。排除 `.git`、构建目录、
`__pycache__` 和 `.pyc` 后：

- 压缩包有效文件：158
- 当前 `main` 有效文件：142
- 路径重合：131
- 内容完全一致：96
- 同路径但内容不同：35
- 压缩包独有：27（主要是 Skybox Noise、节点图和插件框架）
- `main` 独有：11（主要是 EXE 打包、`src/__main__.py`、应用信息和新 UI 主题）

为避免把两个 Agent 的实现直接混成不可追溯的工作树，压缩包被作为独立版本
快照导入 `review/agent-1.0`。`main` 未被修改。原始压缩包中的 Python/Numba
缓存未纳入 Git；生成示例图保留，以忠实记录压缩包内容。

## 2. 验证结果

- `python -m compileall -q src tests examples`：通过。
- `python -m src.ui.main --offscreen --smoke`：通过。
- 完整 `unittest`：127 项，126 通过，1 失败。
- 失败项：
  `test_worker_gen_noise_matches_core_gen_noise`，2048 个采样中 1980 个
  （96.7%）不一致，最大绝对差约 `0.78275`。
- `_smoke_skybox.py`：退出码 0，但同时报告 Skybox 插件不可用，仍打印
  `ALL SMOKE OK`，因此该脚本存在假阳性。
- `python -m src`：失败，缺少 `src.__main__`。

### 2.1 EXE 打包阶段更新

以上结果记录的是导入基线 `da9be1d`。后续 EXE 打包阶段已完成以下修复：

- B03：numba 不再是 Skybox 插件加载门槛；标准 EXE 使用 NumPy fallback。
- B04：worker 的 NumPy fallback 改为使用线程本地 permutation，结果一致性测试通过。
- B13：恢复 `src.__main__`、应用元数据、PyInstaller spec、构建脚本和打包测试。
- 源码测试更新为 131/131 通过，`python -m src --smoke-test` 通过。
- 目录版与单文件版 Windows EXE 均成功构建；冻结程序冒烟测试退出码为 0，
  文件版本与产品版本均为 `1.0.0`。

### 2.2 交互、精度与性能修复阶段更新

按照审计计划继续完成了以下修复：

- B01、B02：端口锚点改为真实圆心，场景选择与属性面板同步，并加入
  Qt 鼠标点击及可见端口命中测试。
- B05、B08：实现 4×3 Cubemap 六面方向映射；代理尺寸保持源宽高比。
- B06：Skybox 主窗口、worker 和节点贴图统一使用公共 16-bit/EXR I/O；
  保存通过公共 saver，浮点结果不允许静默写成 PNG。
- B07、B09：新增每个求值任务私有的 `NoiseContext`，Perlin Seed 生效，
  节点预览与 worker 不再共享可变 permutation。
- B10、B11：本地状态与进度条进入插件布局；重算只发取消令牌，GUI 线程
  不再 `wait()`，同一时刻最多运行一个渲染任务。
- B12：节点图加载验证根结构、节点 ID/类型、坐标、端口、悬空连接、
  重复连接和环路，错误停留在状态区。
- B14、B15、B16、B17：恢复 1% 缩放下限和等比缩略图，去除重复状态派发，
  冒烟脚本改为断言式检查并删除硬编码的一次性修复脚本。
- 性能基础：复杂编辑使用最长边 1024 的代理预览；缩略图先采样再转 8-bit；
  `FileCache` 同时受条目数和字节预算约束。
- 当前源码测试为 144/144 通过，`python -m src --smoke-test` 和断言式
  `_smoke_skybox.py` 通过。

### 2.3 兼容性与最终输出修复阶段更新

- planar separate RGB/RGBA TIFF 会按 TIFF sample axis 转换为应用使用的
  `H×W×C`，兼容 DCC/渲染器常见的 `S×H×W` 文件。
- Skybox HDR 合成不再硬裁到 1.0，`highlight_max` 高于 1 时可写入 EXR/
  浮点 TIFF；屏幕预览仍安全裁切显示。
- 保存 Skybox 结果时若当前只有代理预览，会异步重算最新全分辨率结果后
  自动写盘，避免误把 0.4x 预览作为成品。
- 自定义节点图修改会使主预览失效并自动触发 debounce 重算。
- 打包脚本会实际启动 `.venv-build` 的 Python；失效环境会明确提示并重建。
- 当前源码测试为 150/150 通过，源码与 Skybox 冒烟测试均通过。

下表保留导入时的完整发现作为历史记录；B01-B17 当前均已解决。

## 3. 已确认 BUG

| ID | 优先级 | 问题 | 证据与影响 | 主要位置 |
|---|---|---|---|---|
| B01 | P1 | 节点图鼠标交互基本失效 | 端口的 `scene_pos()` 返回子项原点而不是圆点中心；在可见输入端口中心做命中测试返回 `False`。连线会画到节点左上角，拖拽连线难以/无法落到输入端口，端口文字也会重叠。 | `src/ui/skybox_noise/node_editor.py:74` |
| B02 | P1 | 点击节点不会同步属性选择 | 场景没有连接 `selectionChanged`；点击已有节点后 `_selected_node_id` 仍为 `None`。属性面板、Delete/Backspace 因而不作用于用户刚点击的节点。现有测试直接调用私有 `_select_node()`，绕开了真实交互。 | `src/ui/skybox_noise/node_editor.py:273`, `:511` |
| B03 | P1 | “numba 可选”与实际加载逻辑矛盾 | `requirements.txt` 和 README 声称缺 numba 会使用 NumPy fallback，但插件描述子把 numba 列为硬门槛。当前审查环境中 `NUMBA_OK=False`，主窗口只有“编辑模式/互转模式”，整个 Skybox Tab 消失。 | `src/ui/skybox_noise/plugin.py:25`, `README.md:23`, `README.md:188` |
| B04 | P1 | NumPy fallback 的 worker 噪声计算错误 | 无 numba 时 worker 的 fallback 调用共享的 `core.perlin3d()`，没有使用 worker 自己的 `_local_P`。这既破坏结果一致性，也破坏设计目标中的线程隔离；完整测试因此失败。 | `src/ui/skybox_noise/worker.py:89`, `:113` |
| B05 | P1 | Cubemap 投影只是占位实现 | `cubemap-cross (4x3)` 分支最终直接调用 equirectangular；数值复现显示两种投影逐元素完全相同。用户选择 Cubemap 得到错误方向和接缝。 | `src/ui/skybox_noise/projections.py:29`, `:41` |
| B06 | P1 | Skybox 绕过高位深/EXR 公共 I/O | 界面宣称支持 TIFF/EXR/HDR，但使用 Pillow `convert("RGB")` 强制 8-bit。复现中 16-bit TIFF 的 12 个不同值只剩 7 个，EXR 抛出 `UnidentifiedImageError`；保存也始终量化为 uint8。 | `src/ui/skybox_noise/main_window.py:423`, `:431`, `:487`, `:498`；节点贴图加载器和 worker 有同样问题 |
| B07 | P1 | 自定义节点图仍共享全局噪声状态 | 标准 worker 尝试使用本地 permutation，但 `_eval_graph()` 调用的节点定义仍走全局 `gen_noise/fbm3d/perlin3d`。节点预览与后台渲染并发时可相互改写 `_P/_CURRENT_SEED`，产生不稳定结果。 | `src/ui/skybox_noise/worker.py:246`, `src/ui/skybox_noise/node_types.py:18` |
| B08 | P2 | 非 2:1 图像的预览被强制拉伸 | 缩放预览时固定 `sH = sW // 2`。4:3 Cubemap 的 160×120 输入按 0.5 预览变成 80×40，而正确保持比例应为 80×60；圆柱或其他比例也会变形。 | `src/ui/skybox_noise/compose.py:62`, `src/ui/skybox_noise/worker.py:163` |
| B09 | P2 | Perlin 节点的 Seed 参数无效 | `_eval_perlin()` 从不读取 `params["seed"]`。用 seed 1 与 seed 2 求值，最大差为 0；输出还会受其他节点最近一次修改的全局 seed 影响。 | `src/ui/skybox_noise/node_types.py:123` |
| B10 | P2 | Skybox 进度和状态反馈未挂载 | 插件 factory 无 parent 创建 widget；构造时 `self.window()` 不是主窗口，于是 `_status=None`，进度条也没有 parent/布局。渲染、保存和错误状态对用户不可见。 | `src/ui/skybox_noise/main_window.py:173-186` |
| B11 | P2 | 重算会阻塞 UI，旧线程仍可能失去引用 | 参数重算在主线程同步 `wait(2000)`，失败后再 `wait(6000)`，界面可冻结约 8 秒；如果仍未退出，代码继续替换 `self.worker`。关闭窗口也没有统一 cancel/wait 生命周期。 | `src/ui/skybox_noise/main_window.py:299-335` |
| B12 | P2 | 节点图文件缺少结构校验和异常边界 | `load_graph()` 只捕获文件/JSON 解码错误；未知节点类型、缺字段、非法端口、悬空连接和重复 ID 会在 `from_dict()` 或场景重建时未捕获地抛出。 | `src/ui/skybox_noise/node_editor.py:604-622`, `src/ui/skybox_noise/node_graph.py:157-175` |
| B13 | P2 | 1.0 分支丢失可执行包与统一入口 | 相对 `main` 删除了 `texpipe.spec`、构建脚本、版本资源、`pyproject.toml`、`src/__main__.py` 和打包测试；`python -m src` 已确认失败，也不能延续当前工程的 EXE 交付链。 | 分支差异；运行复现 |
| B14 | P3 | 大贴图“适应窗口”有下限回归 | 最小缩放从 `0.01` 改为 `0.1`。16K 宽贴图在约 598px 视口中仍显示为 1638px，不能真正适应窗口。 | `src/ui/advanced_editor_components/preview.py:16` |
| B15 | P3 | 槽缩略图破坏宽高比 | 非方形贴图使用 `IgnoreAspectRatio` 强制显示为 64×64；128×32 的输入已复现为方形缩略图。 | `src/ui/slot_widget.py:270` |
| B16 | P3 | 主窗口状态消息重复派发 | `show_status()` 先发信号、再直接调用 banner；该信号又连接到同一个 `show_message()`，一次状态会执行两遍并重复重启计时器。 | `src/ui/app.py:195-203`, `:224` |
| B17 | P3 | 审查/发布辅助文件存在假阳性和硬编码 | `_smoke_skybox.py` 在插件不可用时仍返回成功；README 仍写“123/123”，实际为 126/127；`_fix_curve.py` 含失效的 `C:\Documents\贴图转换` 绝对路径和直接二进制覆写逻辑。 | `_smoke_skybox.py`, `_fix_curve.py`, `README.md:504`, `:550` |

说明：P1 表示核心功能错误或主要功能不可用；P2 表示明显功能/稳定性问题；
P3 表示体验、维护性或验证可靠性问题。当前没有发现会直接删除用户源贴图的 P0
数据破坏问题。

## 4. 与 `main` 合并时的额外回归风险

不建议把 `review/agent-1.0` 整体 merge 回 `main`。该快照在新增 Skybox/节点图的
同时，回退了已经完成的 UI 和交付能力：

- 删除统一主题 `src/ui/theme.py`，复杂编辑器从聚焦式 Tab 回退成三个并排面板。
- 删除互转模式的上下文工具栏、格式交换和按模式隐藏无关预览等体验改进。
- 删除 EXE/PyInstaller 配置与打包测试。
- 删除 `src/__main__.py` 和应用版本信息。
- 缩略图、复杂编辑缩放下限出现可复现回归。

推荐从该分支选择性迁移 `plugin.py/plugin_manager.py`、
`src/ui/skybox_noise/` 和对应测试，再适配 `main` 的主题、入口、打包和 I/O，
而不是合并整棵工作树。

## 5. 分阶段修复计划

### 阶段 A：先补真实交互回归测试

1. 增加 Qt 鼠标级测试：点击节点、删除节点、从可见输出圆点拖到可见输入圆点。
2. 把 Skybox 测试拆成“无 numba”和“有 numba”两套；无 numba 必须显示插件并走 fallback。
3. 将 `_smoke_skybox.py` 改成断言式检查，插件缺失、投影相同或测试失败时返回非零。
4. 为 16-bit TIFF/PNG、float EXR、4:3 Cubemap、16K 预览增加回归测试。

### 阶段 B：修复节点编辑器阻断项（B01、B02、B09、B12）

1. 端口锚点改为 `mapToScene(rect().center())`，文字布局也用端口 rect 中心。
2. 连接 `scene.selectionChanged`，以真实选中项更新 `_selected_node_id` 和属性面板。
3. 把拖动过程的边刷新与“拖动结束记录一次 undo”分开，避免一次拖拽塞满 100 个快照。
4. Perlin 节点真正应用 seed；加载 JSON 前验证节点类型、ID、端口、连接和环路。

### 阶段 C：把噪声核心改成无全局可变状态（B04、B07）

1. 引入显式 `NoiseContext(seed)` 或把 permutation 作为参数传入所有 Perlin/FBM 调用。
2. NumPy 与 Numba 共用同一算法入口和同一 permutation，删除 worker 内复制的风格化逻辑。
3. 修正初始 `_P` 与 `_CURRENT_SEED` 不一致（当前分别对应 1337 与 0）。
4. 节点图预览和后台 worker 各持有独立 context；并发测试验证结果可重复。

### 阶段 D：修复投影、尺寸和精度（B05、B06、B08）

1. 实现完整 4×3 cross 的六面映射，并加方向/接缝 golden tests。
2. 预览尺寸按源宽高同比缩放，不再固定 2:1；针对不同投影设置合法布局检查。
3. Skybox 与节点贴图统一调用 `src.io.loader.load_image()`，保留 uint16/float HDR。
4. 保存统一走 `src.io.saver.save_image()`；PNG/TIFF/EXR 不允许静默降位深。

### 阶段 E：修复线程生命周期与反馈（B10、B11）

1. 为插件定义 `status_message/progress` 信号，由主窗口在插入 Tab 后连接；本地进度条必须进入布局。
2. 取消操作只发取消令牌，不在 GUI 线程累计阻塞等待；完成回调用 render sequence 丢弃旧结果。
3. widget/main window 关闭时 cancel，并异步等待所有 worker 完成后再销毁。
4. 对“连续拖滑块、立即关闭窗口、大图首次 JIT”加入稳定性测试。

### 阶段 F：选择性合入 `main` 并恢复交付链（B13-B17）

1. 以 `main` 为目标分支迁移插件功能，保留主题、复杂编辑 Tab、互转 UX 和入口文件。
2. 扩展 PyInstaller spec 的 hidden imports/collect 配置，覆盖 OpenEXR、tifffile、PyPNG，numba 仍保持可选。
3. 保留 `tests/test_packaging.py`，构建后验证 EXE 启动、主窗口三 Tab、基础导入导出。
4. 恢复 1% 最小缩放、KeepAspectRatio 缩略图，移除重复状态派发。
5. 删除一次性修复脚本和编译缓存，更新 README 的能力、限制与测试数字。

## 6. 完成标准

- 无 numba：Skybox Tab 可见，NumPy fallback 结果正确，完整测试全绿。
- 有 numba：与 NumPy 结果在容差内一致，多 worker 并发不会互相污染 seed。
- Cubemap 与 equirectangular 不再相同，4×3 预览保持比例且六面方向正确。
- 节点可用鼠标选择、连线、断线、删除、撤销/重做，加载坏图文件只显示错误而不抛出窗口。
- Skybox 16-bit TIFF/PNG 和 float EXR 导入/导出不静默降位深，HDR 值策略有明确测试。
- 连续重算与关闭窗口不出现 UI 长时间冻结或 `QThread: Destroyed while thread is still running`。
- `python -m src`、源码启动、打包测试和 EXE 冒烟全部通过。

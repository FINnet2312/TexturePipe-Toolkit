# TexturePipe-Toolkit — 贴图通道转换工具(texpipe)

把几张单通道灰度图合成一张打包贴图(ORM / RMA 之类),或者反过来拆,
或者不同命名约定之间互转 —— 这就是 `texpipe` 干的事。面向游戏美术 / TA,
纯 Python 实现,开箱即用。

工具是双击 `texpipe.bat` 启动的桌面 GUI,同时带一个命令行(CLI),批处理和流水线场景用。

---

## 怎么打开

在当前工具文件夹里找到 **`texpipe.bat`**,**双击它**。
会弹一个黑色命令行窗口跑几秒(自动检查 Python、自动装依赖),然后 GUI 窗口会开起来。
第一次用可能要等一两分钟装依赖,以后都是秒开。

GUI 主窗口约 1500×820,**顶部 Tab:`编辑模式` / `互转模式` / `Skybox Noise`(插件)**。默认进编辑模式。

> **首次使用**:`texpipe.bat` 会自动跑 `pip install -r requirements.txt`,装好后每次都秒开。需要 Python 3.10+。如果自动装失败,手动跑 `pip install numpy Pillow PySide6 pypng tifffile OpenEXR` 也行。
>
> **没装 Python?** 启动器会自动检测并给出安装引导(含 `winget install Python.Python.3.12` 一键命令 / python.org / Microsoft Store 三种方式),不会再一闪而过或报莫名错误。装了但版本低于 3.10 也会明确提示。
>
> **可选 numba**:`texpipe.bat` 启动时还会顺便试装 numba(失败也不报错,只是 Skybox Noise 噪声会慢一些)。

### 依赖一览

- **Python** 3.10+（3.14 已测过）
- **numpy** ≥ 1.24 — 数组计算
- **Pillow** ≥ 10.0 — 8-bit PNG/JPG 读 + 通用图
- **PySide6** ≥ 6.5 — GUI
- **pypng** ≥ 0.2022 — 8-bit PNG 备用
- **tifffile** ≥ 2024.8 — 16-bit 整数 + 浮点 TIFF
- **OpenEXR** ≥ 3.3 — 浮点 EXR 读 + 写
- **numba** ≥ 0.58 — **可选**;Skybox Noise 噪声加速 25-40x,缺了走 numpy fallback(慢但功能完全等价)

不依赖任何游戏引擎,纯 Python。

### Windows EXE 版本

推荐发布目录版，双击 `build_exe.bat` 或运行：

```powershell
.\build_exe.ps1
```

完成后启动 `dist\Texpipe\Texpipe.exe`。发布时要复制整个 `dist\Texpipe`
文件夹；需要单文件时可运行 `.\build_exe.ps1 -Mode onefile`。构建结束会自动
执行冻结程序冒烟测试，检查 Qt、PNG/TIFF/EXR 高位深编解码、Skybox Noise
和节点图模块。完整说明见 `BUILDING.md`。

标准 EXE 不捆绑 numba/LLVM，Skybox Noise 会使用 NumPy fallback；源码运行时
仍可安装 numba 获得加速。

---

## 三分钟上手

最常见的场景:从烘焙工具里拿了 4 张灰度图(roughness、metallic、AO、height),想合成一张 ORM 打包贴图。

1. **启动** — 双击 `texpipe.bat`,GUI 起来
2. **拖图** — 按 ORM 排布拖入:`R=AO`、`G=roughness`、`B=metallic`、`A=height(可选)`。
   如果只有 1 张 RGBA 图,直接拖到**最上面中央那个大方框**(叫"drop zone"),会自动按 R/G/B/A 拆到 4 槽
3. **导出** — 顶部点 **`导出贴图`**,或者按 **`Ctrl+E`**,选择 PNG / TIFF / EXR 保存路径

打开输出文件看一眼,如果 4 个通道分布对得上,丢进项目直接用。

---

## 这个工具能做什么

- **合成(Pack)**:N 张单通道灰度图 → 1 张 RGBA / RGB 图
- **拆分(Unpack)**:1 张 RGBA 图 → 4 张单通道灰度图
- **互转(Transcode)**:不同打包规则之间换格式(比如手里的图是 ORM 排布,目标项目要 RMA,直接转)
- **单通道独立处理**:每个槽的源通道、取反、填纯色,都能单独配
- **单通道复杂编辑**:旋转、亮度、对比度、伽马、曲线、阈值、混合等
- **高位深管线**:16-bit PNG/TIFF 与浮点 EXR 从读取、缩放、编辑到导出均保留精度
- **批处理**:一文件夹里的图按一个规则统一转,产出 CSV 报告(哪些图转成功了、输出在哪)
- **目录化工程**:配置、内嵌源图、高精度槽快照和自动恢复数据统一保存在可移动工程目录
- **插件式扩展**:`Skybox Noise` 等独立工具通过 `src/ui/plugins/` 动态加载;缺依赖不出现,主程序不挂

> **最近一轮加进来的**:贝塞尔曲线编辑器(可拖切线手柄)、3 段可拖动 splitter + 滚轮缩放 + 右键 pan 的复杂编辑大窗、4 槽主题色(R 红 / G 绿 / B 蓝 / A 紫)、底部彩色状态横幅(代替弹窗)、导入后先编辑、缩略图点击放大、文件 LRU 缓存(64 项,改图自动失效)、**Skybox Noise 插件**(equirect / cubemap / 圆柱投影上叠 FBM / Caustics / Voronoi,后线程 + Numba 多核)。

**内置 13 种打包规则**(选 → 转,不用手排):

| ID | 名称 | 用途 |
|---|---|---|
| `orm` | ORM / ARM | 最常用 |
| `rom` | ROM | |
| `rma` | RMA | |
| `mra` | MRA | |
| `unity_mask` | Unity HDRP Mask | |
| `unity_standard` | Unity Standard | |
| `gltf` | glTF | |
| `gltf_no_ao` | glTF 无 AO | |
| `ormh` / `rmah` / `mrah` | *H 三个 | 保留 Height / A 通道 |
| `ordp` | ORDp | 替换 Displacement |
| `custom` | 自定义 | 4 槽随便配 |

> 这 13 个只是预设,任何一格你都可以在 UI 里手动改成不同的源通道或取反。

---

## 编辑模式 怎么用

默认 Tab,适合"我要从一堆散图合成一张"或者"我要拆一张图"。

**界面布局(从上到下)**:
- 顶部工具条:`载入`、`导出贴图`、`撤销`、`重做`、`保存工程`、`加载工程`、**`导入后先编辑` 勾选框**
- 中央 drop zone(顶部那个大虚线框):拖一张 RGBA 图进来,**自动按 R/G/B/A 拆到下面 4 槽**
  - **RGBA 通道勾选**(drop zone 下方):四个 checkbox,未勾选的通道在导入时直接视为空(不占用槽数据)
  - 框体本身也支持**点击 / 拖拽**两种方式导入,任选一种
- **导入后先编辑**(勾选后):导入图片后,**先弹复杂编辑窗口**让你对原图做 PS 风格调整 / 混合 / 曲线 / 缩放 pan,点"应用并关闭"后才按 R/G/B/A 拆到 4 槽
  - 适合"原图差不多但差点意思"的微调场景
- 下方 4 槽:`R / G / B / A`,每槽单独配
- 4 槽右边的预览缩略图(每个槽 1 张):**点击任意缩略图弹大图查看器**(滚轮缩放 0.05x-16x,右键 pan,双击重置),不用先导出就能看清每个通道的实际样子
- 底部:`输出尺寸` 档位(1K / 2K / 4K / 自定义) + `POT 对齐` + `resize 算法` + **彩色状态横幅**实时显示所有操作反馈(成功绿 / 警告黄 / 错误红,自动消失,可手动关)

### 4 槽每槽能配什么

- **拖入文件** — 拖灰度图 / RGBA 图都行
- **源通道 token** — 从拖进来的图里取哪个通道:
  - `R / G / B / A` 直接取
  - `INV_R / INV_G / INV_B / INV_A` 取反(常用于 height → 别的语义时反向)
  - `BLACK` 填纯黑(0)
  - `WHITE` 填纯白(255)
- **语义(semantic)** — 标签提示:roughness / metallic / ao / height / normal / ...
  主要是给"以后自己看到这张图时"提醒用的,不影响最终像素
- **颜色空间标签** — sRGB / Linear,仅记录给导入器/美术查看,不会自动改写通道值或文件 gamma
- **复杂编辑(PS 风格调整窗口)**:点槽里的"复杂编辑"按钮,会弹一个独立窗口,完整 PS 风格的图像调整:
  - **旋转**:任意角度（0.1° 精度）；带左转 90° / 右转 90° / 180° 快捷按钮，自动扩展画布而不裁切
  - **基础**:亮度(-100~+100) / 对比(0~2) / 曝光(-2~+2 EV)
  - **明暗分区**:阴影 / 高光(分别作用于暗部 / 亮部,蒙版加权)
  - **伽马 / 饱和度**
  - **阈值**(0-255,-1=关) / **色调分离**(2-256 级) / **反相**
  - **曲线编辑器**(贝塞尔风格):可视化画布,可拖动控制点改变曲线;**每个控制点有 2 条切线手柄**(出向亮色 + 入向暗色,对称模式)可自由拖动,做出任意形状的贝塞尔曲线;点曲线空白处 = 加新点;双击控制点 = 删除(端点不删);5 个预设(原样 / 提亮 / 压暗 / 高对比 / 反转)+ 一键重置
  - **混合模式**:加载第二张图后,可选 15 种 PS 风格混合(Normal / Multiply / Screen / Overlay / Darken / Lighten / Color Dodge / Color Burn / Hard Light / Soft Light / Difference / Exclusion / Add / Subtract / Divide)
  - **第二张图也支持 RGBA 通道勾选**、拉伸 / 包含 / 截取 / 平铺、偏移与 X/Y 缩放，以及嵌套编辑(点"✎ 编辑这张"再开一个复杂编辑窗口,可多层递归)
  - **预览可右键拖拽 pan** 看大图
  - **3 段可拖动 splitter**:原图 / 结果 / 控制面板之间的边界可以自由拉宽拉窄,布局完全自定义
  - **滚轮缩放预览**(0.1x - 10x,以鼠标位置为锚点),左键双击重置,缩放比实时显示在底部状态栏
  - 点"应用并关闭"才把结果写回父槽

> 取反 / 全黑 / 全白 **都是 token**,不是后处理。意思是"这个槽就从源图取反通道"和"这个槽填纯白"可以在同一次合成里混用,不需要先转图。

**4 槽按通道分色**,边框和标题色固定(R 红 / G 绿 / B 蓝 / A 紫),扫一眼就知道哪槽是哪通道,不用看字。

### 调输出规格

底部那条:
- **尺寸档位** — `512` / `1K` / `2K` / `4K` / `8K` / `custom`
- **自定义宽高** — `custom` 模式下填
- **POT** — 输出尺寸对齐到 2 的幂(老硬件/老管线要求)
- **resize 模式** — 源图和目标尺寸不一致时:`fit`(等比覆盖并居中裁切) / `fill`(等比完整放入并黑边填充) / `stretch`(直接拉伸) / `none`(尺寸不一致就报错)
- **滤镜** — `nearest` / `bilinear` / `bicubic` / `lanczos`(默认 lanczos,质量最好)

### 导出

顶部 **`导出贴图`** 或 **`Ctrl+E`**,弹出文件对话框选保存路径。
输出格式由扩展名决定。16-bit 输入导出 PNG/TIFF 时保持 16-bit；浮点输入建议导出 EXR 或浮点 TIFF。工具不会静默降为 8-bit。

---

### 保存工程

第一次点击 **`保存工程`** 时选择或新建一个目录，工具会生成：

```text
工程目录/
├─ project.json
├─ assets/
│  ├─ sources/    # 外部源贴图的内嵌副本（按内容哈希去重）
│  └─ state/      # 当前槽数据的精确 .npy 快照
├─ cache/         # 可重建缓存
└─ autosave/
   ├─ recovery.json
   └─ assets/     # 未正式保存操作的恢复快照
```

- `project.json` 只使用相对路径，整个目录可以直接移动或复制。
- `.npy` 快照精确保留 `uint16`、`float32`、HDR 和负值。
- 工程建立后，编辑停止约 1.5 秒会写入自动恢复数据。
- 下次加载发现未正式保存的操作时，会询问是否恢复。
- 原来的单 JSON 工作区仍然可以加载；重新保存后会转为目录化工程。

---

## 互转模式 怎么用

第二个 Tab,适合"手里的图是 A 排布,目标要 B 排布"。

**流程**:
1. 顶部 **`载入源图…`** — 选择 PNG / TIFF / EXR 等贴图
2. 左侧选 **源 preset**(这张图本身的排布规则,比如 `orm`)
3. 左侧选 **目标 preset**(想转成什么,比如 `rma`)
4. 右侧实时预览 — 改 preset 立刻看到重排后的样子
5. 顶部 **`导出目标图…`** — 选保存路径,落盘

> **怎么知道手里的图是哪种排布?** 看材质里那张贴图节点的注释,或者问资产作者;或者先猜一个(比如 `orm` 或 `rma`),看预览对不对。

---

## Skybox Noise 插件 怎么用

**第 3 个 Tab**,按插件形式动态加载(`src/ui/plugins/discover()` 在启动时扫一遍)。numba 只是可选加速器；缺少时 Tab 仍会出现并自动使用 NumPy fallback。

**用途**:给天空盒 / 球 / 圆柱投影的贴图上叠程序化噪声,输出 composite / mask / normal 三种图。常见场景:水下焦散、星空、极光、云团、异界天空、纹理微扰。

**支持 3 种投影**(按宽高比自动检测,也可手动改):

| 投影 | 宽高比 | 用途 |
|---|---|---|
| `equirectangular` | 2:1 | 标准全景 / 天空球(主流引擎默认) |
| `cubemap-cross (4x3)` | 4:3 | 4×3 十字布局的 cubemap |
| `cylindrical` | 其他 | 圆柱侧壁展开 |

**支持 4 种噪声风格**:

| 噪声 | 特点 | 适合 |
|---|---|---|
| `FBM (基础)` | 标准分形 Perlin | 通用云团、扰动 |
| `Caustics (焦散)` | 域扭曲 + 锐化 + 细线栅格叠加 | 水下焦散、能量场、藤蔓 |
| `Voronoi (细胞)` | 双层 FBM 距离锐化 | 晶格、生物组织 |
| `自定义 (节点图)` | 可视化节点图自由组合,可保存复用 | 任意复杂噪声配方 |

**工作流**:

1. 加载一张 equirect / cubemap / 圆柱展开的贴图 — 两种方式:
   - 点 `📂 打开图像` 选文件
   - 直接把图片**拖进 Skybox Noise 的 Tab** 里(拖非图片文件会被忽略)
2. 改右侧参数(空间尺度 / 强度 / Mask 上下限 / 色调 / 高光压限...);所有改动 **400ms debounce** 后后台重算
3. 想要更自由的噪声组合,点 `🧩 编辑节点图` 打开可视化节点图编辑器(见下节)
4. 进度条 + 状态栏显示渲染进度(`UV 网格 → 噪声生成 → 合成 → 法线`)
5. 满意了点 `💾 保存合成图` / `💾 保存 mask` / `💾 保存法线`；如果当前仍是 0.4x 代理预览，程序会先在后台重算全分辨率结果，再自动保存
6. `🔄 强制重算` = 手动触发全分辨率重渲；调乱了点 `↺ 恢复默认` 一键复位

**预览交互**(与原图 / 合成预览一致):

- **滚轮缩放**(5% ~ 1600%),**右键拖动平移**,**双击复位**到自适应大小
- 底部显示当前缩放比例;换图后自动回到自适应
- **细节放大镜**:鼠标悬停在图上时,预览区右上角固定小窗显示该处 **4x 放大细节**,移出即隐藏 — 适合核对噪声纹理、焦散细线这类细节

### 节点图编辑器(自定义噪声)

`🧩 编辑节点图` 打开可视化节点图画布,把「噪声源 / 数学运算 / 混合 / 变换 / 后处理」自由连成一张图,得到任意复杂的噪声配方:

- **左侧节点库**按分类分组,**双击添加**到画布;**中间画布**拖拽节点、从输出端口拖线连到输入端口(类型不匹配 / 输入端口重复连接 / 成环都会被拒绝)
- **右侧属性面板**编辑选中节点的参数(滑杆 / 下拉 / 勾选 / 文件路径)
- **Del** 删除选中节点;**右键点连线**断开;**Ctrl+滚轮**缩放画布;`🎯 自动整理` 按拓扑自动排布
- **撤销 / 重做**(`↩` / `↪`,最多 100 步;滑杆拖动整体算一步)
- **自动预览**:属性面板下方小窗实时渲染当前图(400ms debounce,256×128),可取消勾选「自动预览」
- **保存 / 加载**:`💾 保存图` / `📂 加载图` 存成 JSON,下次直接复用

**端口类型**(画布上按颜色区分):

| 端口 | 颜色 | 内容 |
|---|---|---|
| 坐标 `coord` | 蓝 | HxWx3 球面坐标(坐标源 / 域扭曲) |
| 场 `field` | 绿 | HxW 单通道噪声场 |

**内置节点**:

| 分类 | 节点 |
|---|---|
| 源 | 球面坐标源(投影自动计算,噪声源未连坐标时默认使用) |
| 噪声 | FBM / 焦散 / Voronoi / Perlin 单频 / **导入噪声贴图** |
| 数学 | 相加 / 相减 / 相乘 / 相除 / 取大 / 取小 / 幂 / 绝对值 / 取反(带标量常量) |
| 混合 | PS 风格 15 种混合模式(复用主编辑器)+ 混合强度 |
| 变换 | 域扭曲(用低频噪声扭曲坐标,产生流动感) |
| 后处理 | 亮度/对比度/伽马、范围重映射 |
| 输出 | 输出(图上第一个输出节点即最终噪声场) |

**导入噪声贴图**节点可以直接把**自己的噪声贴图**(灰度/彩色均可)当作噪声源:按 UV 平铺采样,可调平铺次数 / 取用通道(R/G/B/亮度)/ 平铺循环 / 亮度对比度。预设噪声、导入噪声、节点化自定义三种方式可以混用在同一条链路里(比如「导入噪声 × FBM 域扭曲 → 混合 → 输出」)。

**多线程**:

- **渲染**:独立的 QThread,UI 不卡;改参数时旧 worker 立即取消,启新的
- **噪声生成**:Numba `parallel=True` 走 OpenMP 多核(4 核机器约 25-40x 加速)
- **缺 numba**:自动 fallback 到纯 numpy,功能完全一样,只是慢(8s → 0.3s → 8s 之类)

**Numba 状态提示**:工具右上角会显示 `Numba: ✓ 加速 25-40x` 或 `Numba: ✗ (numpy fallback, 慢)`,一眼能看出当前用没用上加速。

**插件架构**(`src/ui/skybox_noise/`):

- `core.py` — Perlin / FBM / 噪声(纯函数,可单测)
- `projections.py` — UV → 球面坐标
- `compose.py` — 合成 + 法线生成
- `worker.py` — `QThread` 后台渲染
- `widgets.py` — `ImageLabel`(缩放 / 平移 / 细节放大镜)/ `ParamSlider`
- `node_graph.py` — 节点图数据模型 + 求值引擎(无 UI 依赖,可单测)
- `node_types.py` — 节点类型注册表(参数 / 端口 / 求值函数)
- `node_editor.py` — `NodeEditorDialog` 可视化节点图编辑器
- `main_window.py` — `SkyboxNoiseWidget`(被 plugin 嵌入 Tab)
- `plugin.py` — `Plugin` 描述子 + 工厂

新增插件只需在 `src/ui/plugins/__init__.py` 加一行 `register(PLUGIN)`,自动出现在主窗口。

---

## 典型场景

### 场景 A:从烘焙拿了 4 张灰度图,合成一张 ORM

最常见的工作流。烘焙工具(Substance / Knald / 自家工具)一般会输出 roughness、metallic、AO、height 各一张。

1. 双击 `texpipe.bat` 启动
2. 4 张图分别拖到 4 槽(R=AO、G=roughness、B=metallic、A=height)
3. 4 槽的 token 全部选 **`R`**(因为都是单通道灰度图,只有 R 有数据)
4. semantic 标签随手标一下,方便以后认
5. 底部选 `2K`、`POT`、`fit`、lanczos
6. **`Ctrl+E`** 导出,文件名后缀 `ORM`
7. 拖进引擎,在材质里接到 ORM 贴图节点(常见约定 R=AO、G=rough、B=metal、A=忽略)

### 场景 B:项目组用 RMA,我手里的资产是 ORM

手里一堆 `T_*_ORM.png`,目标项目要 `T_*_RMA.png`。

**走 GUI**:切到 `互转模式`,把每张图分别载入 → 源 `orm` → 目标 `rma` → 导出。
**走 CLI**(量大的时候更快,见下文 "命令行怎么用")。

### 场景 C:整文件夹批处理

几十上百张图,统一从一个格式换到另一个:

- **GUI 暂时没有"批处理面板"**(只有 CLI 支持)
- 用 CLI 一条命令搞定,跑完会出一个 CSV 报告(哪些成功、哪些失败、输出路径在哪)

详见下一节。

---

## 命令行怎么用

GUI 不便的场景(批处理、脚本化、CI)用 CLI。**在 `贴图转换` 目录下**打开 cmd / PowerShell:

```bash
# 3 张灰度 → RGB ORM
python -m src.cli.main pack --r ao.png --g rough.png --b metal.png --out T_Floor_ORM.png --size 2K --pot --remove-alpha

# 互转:ORM → RMA
python -m src.cli.main transcode T_Floor_ORM.png --src-preset orm --dst-preset rma --out T_Floor_RMA.png

# 拆:RGBA → 4 张灰度
python -m src.cli.main unpack T_Floor_ORM.png --out-dir ./unpacked/

# 批处理:源 ORM 文件夹 → RMA,产出 CSV 报告
python -m src.cli.main batch --input-dir ./in/ --output-dir ./out/ --src-preset orm --preset rma --report-name rma_batch.csv
```

**文件名自动识别**:输入 `T_Floor_ORM.png` + preset `rma` → 输出 `T_Floor_RMA.png`。若推导结果会与源文件同名,会追加 `_Converted` 避免原地覆盖。

**CSV 报告**列:源文件、目标文件、目标 preset、实际输出映射、是否带 A、状态(成功/失败)。

> CLI 命令记不住没关系,`python -m src.cli.main <子命令> --help` 永远能看完整参数。

---

## 支持的格式

- ✅ PNG：8-bit 与 16-bit，灰度 / RGB / RGBA
- ✅ TIFF：8/16-bit 整数与浮点，灰度 / RGB / RGBA
- ✅ OpenEXR：单 Part、非 Deep 的 Y / RGB / RGBA，内部以 `float32` 处理并保留 HDR 值
- ✅ JPG / TGA / BMP / WebP：8-bit
- 暂不支持多 Part EXR 与 Deep EXR

预览始终显示为 8-bit 副本，但原始母版、通道处理和导出不会因此降位深。对 EXR 做亮度、曲线等有界调整后，结果按数据贴图范围裁到 0..1；不做色调调整或只做旋转时可保留大于 1 的 HDR 值。

---

## 快捷键

| 快捷键 | 干啥 |
|---|---|
| `Ctrl+Z` | 撤销(槽配置、preset 选择都算) |
| `Ctrl+Y` | 重做 |
| `Ctrl+E` | 导出贴图(直接弹文件对话框) |
| `Ctrl+S` | 保存当前目录化工程 |
| `Ctrl+O` | 加载 `project.json` 或旧工作区 JSON |

---

## 常见问题

### 双击 `texpipe.bat` 没反应 / 一闪而过

通常是 Python 没装好。现在的启动器会自己检测:没找到 Python / 只装了 Microsoft Store 占位符 / 版本低于 3.10 时,会停在命令行窗口里给出**安装引导**(winget 一键命令、python.org、Microsoft Store 三种方式),不会直接闪掉。

**排查步骤**:
1. 打开 cmd,敲 `py -3 --version` 或 `python --version`,看有没有版本号
2. 没有 → Python 没装,按命令行窗口里的引导装 3.10+,**装的时候勾上 `Add Python to PATH`**
3. 有版本号但 `texpipe.bat` 还报错 → 把错误信息复制下来问 TA

### 拖图进去槽里没显示 / 显示黑色

先看底部错误提示。常见原因是文件实际格式与扩展名不符、EXR 是 Deep / 多 Part，或贴图通道数不是 1/2/3/4。

### EXR 有什么限制?

目前支持常规单 Part、非 Deep 的 Y / RGB / RGBA EXR。多 Part 或 Deep EXR 需要先在 DCC / 合成软件中展平为普通 scanline EXR。

### 预览里"颜色不对" / 太黑 / 太白

按顺序排查:
1. token 选对没?(R/G/B/A 跟源的图排布对得上吗)
2. 源图的位深、通道数和预期是否一致?
3. 是不是 height 图想用但取了反(很多管线 height 是反的)—— 试一下 `INV_*`
4. semantic 标签只是标签,不影响像素
5. 如果想调单个通道的明暗/对比,用槽里的"复杂编辑"

### 互转之后颜色跟源图差很多,正常吗?

**正常**。互转的本质就是"重新排一下通道",如果你选错了源 preset(比如源图其实是 RMA,你选了 ORM),出来的图就会跟想的不一样 —— 因为 R/G/B/A 跟内容错位了。

验证方法:在 `互转模式` 里源/目标选同一个 preset。RGB/RGBA 有效通道的像素应一致;目标为 RGB 预设时会按规则移除 Alpha。

### 输出图是 RGB 还是 RGBA?

取决于目标 preset:
- `orm` / `rma` / `gltf` 这些 → **RGB(3 通道)**,A 通道扔掉
- `ormh` / `rmah` / `mrah` / `ordp` / `unity_mask` / `unity_standard` → **RGBA(4 通道)**,保留 A

导入引擎时,选 `RGB` 的就不带 alpha;选 `RGBA` 的 alpha 通道会被读到(可以塞 height)。

### 文件名后缀我想自己控,工具会不会乱改?

- **编辑模式导出**:`Ctrl+E` 弹文件对话框,**保存路径和名字完全你定**,工具不干预
- **互转模式导出**:`导出目标图…` 也是文件对话框,同上
- **CLI / 批处理**:`--out` 你给什么就是什么;`batch` 子命令会自动按 preset 改后缀(觉得不喜欢可以 `--output-dir` + 自己的命名规则)

### 拖 RGBA 图到 drop zone,4 槽分别是什么?

- `R 槽` ← 源图 R 通道
- `G 槽` ← 源图 G 通道
- `B 槽` ← 源图 B 通道
- `A 槽` ← 源图 A 通道

每槽默认 token 与物理槽位一致(R/G/B/A);对真正的灰度图取 R/G/B 得到的值相同。

### 我只想要 RGBA 源图里的部分通道,怎么办?

中央 drop zone 下面有 4 个 checkbox(`R / G / B / A`),**未勾选的通道在导入时直接视为空**:
- 比如只想用 R 和 G,只勾 R 和 G,导入后 B 和 A 槽都是空
- 不勾的通道既不占内存,也不参与后面的 export
- 复杂编辑窗口里加载"第二张图"时,也有同样 4 个 checkbox,逻辑一致

如果发现"明明只勾了 R 和 G,导出后 B 槽还是有数据",检查一下你拖进去的那张图是不是本来就是灰度(灰度图所有像素 R=G=B,所以勾哪个都拿到一样的图)。

### 复杂编辑窗口里的"第二张图"是什么?怎么用?

第二张图用于"用另一张图去修本槽的图"。典型场景:
- 手里有 rough,想乘一个 mask(在 mask=0 的地方不要粗糙度)
- 把 mask 图当第二张图加载,选 Multiply → 应用后只保留 mask 区域

支持 15 种 PS 风格混合模式(Normal / Multiply / Screen / Overlay / ... / Divide)。

**嵌套编辑**:第二张图自己也可以再开一个复杂编辑窗口调整(点"✎ 编辑这张")。理论上可以无限嵌套下去,适合"对 mask 先反相、再阈值、再乘"这种链式操作。

### 批处理跑了一半挂了,跑过的会重做吗?

**会**。`batch` 不记忆进度,重跑会重新生成输出。需要断点续跑时,请先根据 CSV 的 `Status=OK` 清理输入清单;`FAIL` 行包含失败原因。

### 复杂编辑窗口里 3 段 splitter / 滚轮缩放怎么用?

- 窗口里能看到几道**浅灰分隔条**,鼠标移到上面会变蓝色,按住左右拖动就能改各区域大小
- 预览图上**滚轮** = 缩放(以鼠标位置为锚点),范围 0.1x - 10x,缩放比实时显示在窗口底部
- 缩放过大图看不见时:**右键拖** = pan,**左键双击** = 重置回 100%

### 顶部那个"导入后先编辑"勾选是干嘛的?

- 不勾:拖 RGBA 图到 drop zone,直接按 R/G/B/A 拆 4 槽,完事
- 勾上:拖完图,先弹**复杂编辑窗口**,你做完 PS 风格调整 / 曲线 / 混合 / 缩放 pan,点"应用并关闭"后才拆 4 槽
- 适合"原图差不多但差点意思,想微调下再拆"的场景(比如整张图提一档,或者叠个 mask)

### 缩略图怎么点击放大?

每个槽位右边都有 1 张小缩略图,**鼠标移上去会高亮边框,光标变手型,点一下**就弹大图查看器:

- 滚轮缩放 0.05x - 16x(比复杂编辑窗口范围还宽,适合抠像素细节)
- 右键 pan,双击重置
- 标题栏显示是哪一槽 + 通道名 + 数据范围

不需要先导出来看每个通道实际什么样,改完参数立刻能看效果。

### 底部那条彩色状态条是干嘛的?一直弹东西?

工具里所有操作反馈都走这里,**不会弹模态对话框打断你**:

- 🟢 成功(3 秒自动消失)
- 🟡 警告(5 秒)
- 🔴 错误(8 秒)
- 🔵 提示(3 秒)
- 右侧 × 按钮手动关

执行 `导出贴图`、`保存工程`、`加载工程`、`RGBA 拆分`、`复杂编辑应用` 等等都会在底部有反馈。

---

## 还有问题

- 仓库里有个 `docs/PLAN.md`,里面有早期的设计备忘(给 TA / 开发者看的,普通用户不用翻)
- 实际操作遇到 bug,截图 + 错误信息丢给负责这工具的 TA

### 复杂编辑器代码结构（开发者）

`src/ui/advanced_editor.py` 是稳定兼容入口；具体实现按职责拆分：

- `advanced_editor_dialog.py`：对话框状态、控件和事件编排
- `advanced_editor_components/adjustments.py`：不依赖 Qt 的像素调整管线
- `advanced_editor_components/blend_modes.py`：15 种混合模式
- `advanced_editor_components/mapping.py`：第二图片的拉伸、包含、截取和平铺
- `advanced_editor_components/curves.py`：曲线 LUT 与交互控件
- `advanced_editor_components/preview.py`：缩放、平移和拖放预览控件

算法模块可单独测试；外部代码继续从 `src.ui.advanced_editor` 导入即可。

### 测试

项目有两层测试,都跑在 headless（offscreen Qt）模式:

```bash
# 1) 单元测试(150 个,纯逻辑 + 集成 + 节点图)
py -m unittest discover tests

# 2) 集成 / 行为验证(16 个 verify 脚本,在 examples/ 下)
py examples/verify_all.py            # 跑一个完整的 pack + transcode 流程
py examples/verify_curve.py          # 贝塞尔曲线编辑器
py examples/verify_blend_modes.py    # 15 种混合模式
py examples/verify_ps_adjust.py      # PS 风格调整(亮度/对比/曝光/伽马/曲线/...)
py examples/verify_zoom.py           # 滚轮缩放 + 3 段 splitter
py examples/verify_p0.py             # 5 个 P0 修复
py examples/verify_ui.py             # UI 结构检查
py examples/verify_ui_e2e.py         # UI 端到端行为
py examples/verify_skybox_smoke.py  # Skybox Noise 冒烟(插件加载 / 渲染 / 投影)
# ... 其他见 examples/verify_*.py
```

每个 verify 脚本在结尾打 `[OK]` 就算过;失败会 `raise SystemExit(1)`。所有 verify 默认设了 `QT_QPA_PLATFORM=offscreen`,无显示器也能跑。

**目录结构**：
- `src/core/` — 核心算法(通道映射 / packer / unpacker / 调整管线 / 像素工具 / 变换 / 文件缓存 / 插件接口)
- `src/io/` — 加载 / 保存 / 工作区
- `src/ui/` — 桌面 GUI(主程序)
- `src/ui/plugins/` — 插件发现 / 注册
- `src/ui/skybox_noise/` — Skybox Noise 插件(独立子包)
- `src/cli/` — 命令行
- `tests/` — `unittest` 测试(150 个,含 Skybox 插件 / 节点图测试)
- `examples/` — verify 脚本和测试用图

---

## 更新记录

见 [CHANGELOG.md](CHANGELOG.md)。


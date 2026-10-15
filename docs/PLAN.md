# 贴图通道转换工具 — 机制规划

> 一个面向游戏美术/TA 流水线的工具,核心是 PNG 通道维度的拆/合/换。
> 目标:让"几张灰度图合成一张 RGBA"和"一张 RGBA 拆回几张灰度图"这类工作能批量、自动化、可视化地完成。

---

## 1. 工具定位

把工作流里"通道"这个概念独立出来抽象,做到:

- **Pack** —— N 张单通道图(1 ≤ N ≤ 4)合到一张 RGBA PNG
- **Unpack** —— 一张 RGBA PNG 拆成 N 张单通道灰度图
- **Reorder** —— 一张 RGBA PNG 内部通道重排(例如 R↔B)
- **Drop / Replace** —— 删/换某通道(填 0 / 255 / 1.0 / 来自另一图)
- **Merge** —— 多张 RGBA 跨图融合(后续扩展)

不依赖 UE Editor,作为独立桌面/命令行工具,可在 UE 流程前后使用。

---

## 2. 核心抽象

### 2.1 ChannelSlot(通道槽)

工具里唯一会被用户操作的对象。一个 `ChannelSlot` 持有"该通道当前的内容"。

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_type` | enum | `empty` / `file` / `solid` / `extracted`(从某图提取) |
| `file_path` | path? | 源文件 |
| `channel_in_file` | `R`/`G`/`B`/`A`/`L`(灰度) | 源图里的哪一通道 |
| `solid_value` | 0..255 | 当 source_type=`solid` |
| `color_space` | `sRGB` / `Linear` | 语义标签,提示引擎导入方式;不改写 8bit byte |
| `invert` | bool | 是否取反(255-x) |
| `semantic` | enum | **通道语义标签**:见下表 |
| `display_name` | str | 用户可见名(可改,如 "粗糙度" / "Roughness") |
| `data` | numpy uint8 H×W | 实际像素数据(内存中) |

**Semantics(默认内置)**:

| Tag | 含义 | 默认色彩 |
|---|---|---|
| `empty` | 未使用 | — |
| `roughness` | 粗糙度 | linear |
| `metallic` | 金属度 | linear |
| `ao` | 环境光遮蔽 | linear |
| `height` | 高度图 | linear |
| `cavity` | 凹陷遮蔽 | linear |
| `opacity` | 透明度 | linear |
| `detail_mask` | 细节遮罩 | linear |
| `curvature` | 曲率 | linear |
| `basecolor_r/g/b/a` | 颜色通道 | sRGB |
| `emissive_r/g/b` | 自发光通道 | sRGB |
| `user_*` | 自定义语义 | 由用户自定 |

> 这层语义是**可选但强烈推荐**。格式互转实际由预设 token 映射完成,语义用于 UI 标注和工作区可读性。

### 2.2 ChannelMap(通道映射)

描述"4 个目标槽(R/G/B/A)分别由什么填"。

```python
# 显式语义版
ChannelMap(
    R = ChannelSlot(file="roughness.png", channel_in_file="L", semantic=roughness),
    G = ChannelSlot(file="metallic.png",  channel_in_file="L", semantic=metallic),
    B = ChannelSlot(file="ao.png",         channel_in_file="L", semantic=ao),
    A = ChannelSlot(file="height.png",     channel_in_file="L", semantic=height),
)
```

**关键能力**:`ChannelMap` 不再是死的,可以"换皮" —— 同一份源数据按预设 token 组合,可得到 RMA / ORM / ROM / Unity Mask 等打包格式。

### 2.3 核心数据流

```
[Source(s)] -> Load -> [ChannelSlot 解析] -> [变换:invert/colorspace] -> [Resize/裁切] -> [Pack into R/G/B/A] -> Encode -> [Output PNG]
```

每一步都是纯函数,便于测试和复用。

### 2.4 输出规格(由 ChannelMap 持有,不属于单通道)

```python
class OutputSpec:
    width: int                       # 输出宽
    height: int                      # 输出高
    resize_mode: enum                # fit / fill / stretch / none
    resize_filter: enum              # nearest / bilinear / bicubic / lanczos
    force_pot: bool                  # 强制对齐到 2 的幂
    pot_strategy: enum               # round_up / round_down / nearest
    size_preset: str?               # "1K" / "2K" / "4K" / "8K" 快捷档
```

尺寸档位 → 像素映射:`1K=1024`、`2K=2048`、`4K=4096`、`8K=8192`(方形);也支持 `1024x2048` 这种长方形写明。

> 分辨率是**输出**的属性,不属于任一通道。源图分辨率不一时,统一按 `resize_mode` 处理再打包。

### 2.5 游戏通用颜色空间标签

按 UE5 / Unity / Godot 通用方案,每个通道打标:

| 贴图类型 | 通道颜色空间 | 备注 |
|---|---|---|
| BaseColor / Albedo / Emissive | sRGB | 美术直接看色彩 |
| Normal Map | Linear | 通道专用于法线,通常单独处理(本期不打包 normal) |
| Roughness / Metallic / AO / Height / Cavity | Linear | 数据贴图 |

工具内默认:`roughness/metallic/ao/height/cavity` → linear,`basecolor/emissive` → sRGB。读图时按 sRGB 解码,写图时按 sRGB 编码,中间用 linear 算;通道内取反/合成都在 linear 域做,最后再转回。

### 2.6 格式互转(Format Transcode)

既然每个槽都有 `semantic`,工具就可以做"**同一份语义数据,按目标格式重新打包**"。

工作流:

```
[源图:ORM (R=AO, G=Rough, B=Metal, A=空)]
        ↓ 按 semantic 解析:slot0=ao, slot1=roughness, slot2=metallic, slot3=empty
[中间表示:4 个 ChannelSlot,各自带语义]
        ↓ 套目标格式预设
[目标:ROM (R=Rough, G=AO, B=Metal, A=空)]
```

**这就是用户痛点的解** —— 一张贴图既能在 RMA 工程用,也能在 ORM 工程用,只要切预设,不需要重画。

数据流(更严格版):

```
Read PNG
   ↓ 按 .meta 标记的源格式(若没有则要 UI 选)解析各通道语义
SemanticMap(s0=roughness, s1=metallic, s2=ao, s3=empty)
   ↓ 套目标格式(目标格式决定哪个 semantic 写到 R/G/B/A 哪个位置)
Pack → Write PNG
```

---

## 3. 功能清单(分层)

### 3.1 MVP(必须先做)

| 功能 | 描述 |
|---|---|
| Pack 4→1 | 4 张灰度 → RGBA |
| Pack 3→1 | 3 张灰度 → RGB(+A=255)|
| Pack 2→1 / 1→1 | 兼容 |
| Unpack 1→4 | RGBA → 4 张单通道灰度图 |
| Reorder | 4 通道重排(24 种排列) |
| Drop channel | 把某通道清成 0 或 255 |
| 通道取反 | invert 选项(roughness/AO 经常要反) |
| **通道语义标签** | 每个槽声明"我是 roughness/ao/metallic..." |
| **自定义通道编辑** | UI 上能加/删/改语义、显示名、源映射、invert、颜色空间 |
| **格式互转** | 源格式 → 目标格式,按 semantic 解析与重打包 |
| 颜色空间 | sRGB / Linear 元数据标签(不自动做 gamma 转换) |
| 分辨率控制 | 指定 1K/2K/4K/8K 或自定义尺寸,源图自动 resize |
| POT 对齐 | 输出可选强制对齐到 2 的幂(UE5 老管线仍要求 POT) |
| resize 算法 | nearest/bilinear/bicubic/lanczos 选 |
| ❌ 预设 | **不做** | 工具不内置任何 UE_ORM/UE_RMA 等预设,只做编辑器本身 |

### 3.2 v2(随后加)

- 实时预览窗口
- 批处理(配置驱动,一文件夹 → 一文件夹)
- 通道替换:从源图指定通道替换到目标图
- 预设(用户后续可加,工具不内置)
- EXR / 16bit 支持

### 3.3 v3(按需)

- 跨图融合(Merge):两张 RGBA 按通道混合
- HDR / EXR 支持
- UE Editor 内集成(Editor Utility Widget)

---

## 4. 技术选型建议

| 项 | 推荐 | 理由 |
|---|---|---|
| 语言 | **Python 3.10+** | 图像处理生态成熟,部署简单 |
| 图像 | **Pillow + numpy** | 足够,加 ImageIO 用于 EXR/HDR |
| UI | **PySide6**(v2) | 桌面 UI,拖拽友好;不喜欢可换 Tkinter |
| CLI | **click** 或 **argparse** | 批处理入口 |
| 打包 | **PyInstaller**(可选) | 美术同事无需装 Python |

> 如果团队偏 C#,也可走 .NET + ImageSharp(同一份规格都能落),但 Python 写起来轻。

---

## 5. 项目结构

```
贴图转换/
├── PLAN.md                       # 本文档
├── README.md
├── requirements.txt
├── src/
│   ├── core/
│   │   ├── slot.py               # ChannelSlot 数据类
│   │   ├── map.py                # ChannelMap
│   │   ├── packer.py             # 4 槽 → RGBA
│   │   ├── unpacker.py           # RGBA → 4 槽
│   │   ├── reorder.py            # 通道重排
│   │   ├── colorspace.py         # sRGB ↔ Linear
│   │   └── pipeline.py           # 一站式流程编排
│   ├── io/
│   │   ├── loader.py             # 文件 → numpy
│   │   └── saver.py              # numpy → PNG/EXR
│   ├── cli/
│   │   └── main.py               # 命令行入口
│   ├── ui/                       # MVP(通道编辑核心)
│   │   ├── app.py
│   │   ├── slot_widget.py        # 单个通道槽组件
│   │   ├── channel_grid.py       # 4 槽 × 4 通道网格
│   │   ├── preview_widget.py     # 预览(单通道灰度 + 最终 RGBA)
│   │   └── transcode_panel.py    # 互转面板(源/目标格式选择)
│   └── utils/
│       ├── logger.py
│       └── workspace.py          # 工作区(整套编辑状态)保存/加载
└── tests/
    ├── test_packer.py
    ├── test_unpacker.py
    └── test_reorder.py
```

---

## 6. 命令行设计(CLI 形态参考)

```bash
# Pack:4 张灰度 -> 一张 RGBA(UE5 ORM)
python -m texpipe.cli pack \
    --r ao.png:gray:linear \
    --g roughness.png:gray:linear \
    --b metallic.png:gray:linear \
    --a height.png:gray:linear \
    --out T_Floor_ORM.png \
    --size 2K --pot --resize fit \
    --preset ue_orm

# Pack 简写(直接套预设)
python -m texpipe.cli pack \
    --preset ue_orm \
    --in ao.png --g roughness.png --b metallic.png \
    --out T_Floor_ORM.png --size 2K --pot

# Unpack:一张 RGBA -> 4 张灰度
python -m texpipe.cli unpack T_Floor_ORM.png --out-dir ./unpacked/ --colorspace linear

# Reorder:RGBA -> ABGR
python -m texpipe.cli reorder src.png --map ABGR --out dst.png

# Drop 通道(用 255 填)
python -m texpipe.cli drop src.png --drop A --fill 255 --out dst.png

# Invert(整张图或指定通道)
python -m texpipe.cli invert src.png --channels G --out dst.png
```

UI v2 内部也调同一套 `core/`,CLI 和 UI 共享实现。

---

## 7. 关键设计决策

| # | 决策项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 技术栈 | ✅ Python + Pillow + numpy | 已定 |
| 2 | 颜色空间 | ✅ 元数据标签 | roughness/metallic/ao/height = linear,basecolor/emissive = sRGB |
| 3 | 形态 | ✅ **UI 优先** | 核心痛点是自定义编辑,CLI 降级为批处理补充 |
| 4 | 分辨率控制 | ✅ 加入 MVP | 1K/2K/4K/8K + 自定义 + POT 对齐 + resize 算法 |
| 5 | 通道取反 | ✅ 加入 MVP | invert 选项 |
| 6 | 通道语义化 | ✅ 加入 MVP | 每个槽带 semantic 标签 |
| 7 | 自定义编辑 | ✅ 加入 MVP | UI 上加/删/改语义、显示名、源映射 |
| 8 | 格式互转 | ✅ 加入 MVP | ORM ↔ RMA ↔ ROM ↔ Unity Mask 自动转 |
| 9 | UE 5 内置预设 | ❌ 暂缓 | 工具不做预设假设,用户自己编辑通道;后续按需要再加 |
| 10 | EXR / HDR | ⏸ 暂缓 | MVP 只做 8bit PNG;有需要再上 |
| 11 | UE Editor 集成 | ⏸ 否 | 独立工具,UE 流程外随取随用 |

---

## 8. MVP 实施顺序

1. `slot.py` + `map.py` + `output_spec.py` — 数据类(含 OutputSpec + semantic)
2. `colorspace.py` — sRGB/Linear 转换(游戏通用默认)
3. `resize.py` — POT 对齐 + resize 滤镜
4. `io/loader.py` + `io/saver.py` — 8bit 文件读存(保持通道 byte 不变)
5. `packer.py` / `unpacker.py` — 核心算法(纯函数,先写测试)
6. `reorder.py` / `drop.py` / `invert.py`
7. `transcoder.py` — **格式互转**(按 semantic 解析 + 按目标格式重打包)
8. `cli/main.py` — 命令行(降级,主要给批处理用)
9. `ui/` — 通道编辑 UI(4 槽网格 + 拖拽 + 预览 + 互转面板)
10. 拿几张真贴图(roughness/metallic/ao/height)跑通 Pack / Unpack / Reorder / Transcode 验证

---

## 9. UE5 适配细节

### 9.1 命名约定(工具不强制,但建议)

| 用途 | 命名 | 通道约定 |
|---|---|---|
| BaseColor | `T_<Name>_BC` 或 `_D` | RGB sRGB |
| Normal | `T_<Name>_N` | RGB linear,法线专用 |
| ORM | `T_<Name>_ORM` | R=AO, G=Roughness, B=Metallic,A=Unused |
| Mask | `T_<Name>_Mask` | 自由 4 通道 |
| Height | `T_<Name>_H` | 单通道 linear |

工具内预设直接对得上 UE 资产命名。

### 9.2 分辨率策略

- UE5 流式贴图理论上支持 NPOT,但**实际项目里很多仍强制 POT**(贴图池/Mip 兼容性)。
- 默认提供 `force_pot=True` 选项,按 `pot_strategy` 对齐。
- 输出尺寸档:`512 / 1K / 2K / 4K / 8K`,也支持任意自定义(`1024x2048` 等)。
- 源图尺寸不一时,按 `resize_mode` 处理:`fit`(等比缩放后裁中间)/`fill`(等比缩放后填边)/`stretch`(强制拉伸)/`none`(报错要求手动选)。

### 9.3 颜色空间标签实操

工具 IO 边界处理:

- **读 PNG** —— Pillow 读图不区分颜色空间,工具保持原始 8bit byte;`color_space` 只记录引擎端应如何解释。
- **写 PNG** —— 内存中保持 linear,写时按目标 sRGB 编码回 8bit。

> 对 ORM 类的纯数据贴图,4 个通道都标 `linear`,读存都是 `linear`,8bit 精度对 AO/roughness/metallic 完全够用。

### 9.4 UE 5 已知坑点(写代码时绕开)

- UE 默认导入设置:`Compression Settings = Masks`(不带 alpha)时 A 通道会被丢 —— 工具输出元数据里要写明 A 通道是否有效。
- 8bit 量化:roughness/metallic 烘焙时常用 8bit,但 height map 在大场景里有时 8bit 不够 —— 工具至少要能 8bit 跑通,EXR 留扩展。

### 9.5 通道自定义编辑 — UI 核心交互

> 这部分是工具的"灵魂",核心问题"我这张贴图怎么解释、怎么打包"全部通过这个 UI 解决。

**布局(4×2 网格)**:

```
┌──────────────┬─────┬─────┬─────┬─────┐
│ 槽语义        │  R  │  G  │  B  │  A  │
├──────────────┼─────┼─────┼─────┼─────┤
│ 当前通道      │ ▓▓▓ │ ░░░ │ ███ │ ... │   ← 来源通道缩略图
│ 显示名        │ AO  │Rgh. │Mtl. │ H   │   ← 可改
│ semantic 标签 │ ao  │rough│metal│hgt  │   ← 下拉选
│ invert        │ ☐   │ ☐   │ ☑   │ ☐   │   ← 复选
│ 源文件        │ao.png│rgh.png│...│ ... │   ← 可拖入
└──────────────┴─────┴─────┴─────┴─────┘
```

**核心交互**:

1. **拖入源文件** —— 拖到任意槽,自动按 L 通道填入,缩略图实时更新
2. **改 semantic** —— 每个槽下拉选(roughness/metallic/ao/.../empty/自定义)
3. **改显示名** —— 自由文本(美术中文名也可)
4. **invert** —— 复选,瞬时反映到预览
5. **改源通道** —— 选这个槽从源图 R/G/B/A/L 哪一通道取
6. **改颜色空间标签** —— sRGB / Linear,不改写当前像素
7. **保存/加载当前编辑** —— 整套编辑存为 JSON 工作区(不是预设,是"我这次这么填"的快照)

**两种模式切换**(顶部 tab):

- **编辑模式** —— 4 个槽独立编辑源文件/语义,适合从头配置
- **互转模式** —— 给一张 RGBA 选"我是 ORM / RMA / ROM / 自定义"(源格式),再选目标格式,工具组合源/目标 token 自动重排并预览

**快捷操作**:

- 一键清空某槽
- 一键复制槽到另一槽
- 预览窗口:4 张单通道预览(灰度图,带伪彩色),和最终打包结果
- 顶部"加载 RGBA 一键解包":拿到一张打包图,工具按你选的"源格式"自动按 semantic 填到 4 个槽里,接下来你直接改某槽就行

---

## 10. 预设方案(暂缓,作为设计参考)

> **本期不做任何内置预设**。工具只做通道编辑器,4 个槽默认都是空,你自己拖文件 / 选 semantic / 命名,完全可控。
> 下面这表留着只是当未来要做预设/互转时,可以参考常见命名约定来排优先级。

| 命名 | R | G | B | A | 常见出处 |
|---|---|---|---|---|---|
| `ORM` | AO | Roughness | Metallic | (空) | UE5 默认 |
| `RMA` | Roughness | Metallic | AO | (空) | 部分 UE5 项目 |
| `ROM` | Roughness | AO | Metallic | (空) | 部分 UE5 项目 |
| `ORMH` | AO | Roughness | Metallic | Height | UE5 含 height |
| `ARM` | AO | Roughness | Metallic | (空) | ORM 的常见别名 |
| `Mask_Default` | Mask1 | Mask2 | Mask3 | Mask4 | 通用 |

未来如果做"互转模式"的源/目标选择,直接对表里这几项做下拉就行,不需要做完整预设系统。

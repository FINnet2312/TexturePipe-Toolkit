"""轻量级界面国际化(i18n)。

用法:
    from src.ui.i18n import tr, i18n

    label.setText(tr("导出"))

    class SomeWidget(QWidget):
        def __init__(...):
            ...
            i18n.language_changed.connect(self.retranslate)

        def retranslate(self):
            self.label.setText(tr("导出"))

- 源码字符串以中文为 key,英文放在 ``_EN`` 字典里
- 当前语言持久化在 QSettings(ui/language),下次启动自动恢复
- 切换语言时发射 ``language_changed``,各控件在 retranslate 里重设文本
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Signal

from src.app_info import APP_ID, ORGANIZATION_NAME

LANG_ZH = "zh"
LANG_EN = "en"

LANGUAGES = {
    LANG_ZH: "中文",
    LANG_EN: "English",
}


class _I18N(QObject):
    language_changed = Signal(str)


i18n = _I18N()

_current_lang = LANG_ZH


def init() -> None:
    """启动时调用一次:从 QSettings 恢复上次选择的语言。"""
    global _current_lang
    settings = QSettings(ORGANIZATION_NAME, APP_ID)
    saved = settings.value("ui/language", LANG_ZH)
    if saved in LANGUAGES:
        _current_lang = saved


def language() -> str:
    return _current_lang


def set_language(lang: str) -> None:
    global _current_lang
    if lang not in LANGUAGES or lang == _current_lang:
        return
    _current_lang = lang
    settings = QSettings(ORGANIZATION_NAME, APP_ID)
    settings.setValue("ui/language", lang)
    i18n.language_changed.emit(lang)


def tr(zh: str) -> str:
    """把中文界面文案翻译成当前语言。没有译文时原样返回中文。"""
    if _current_lang == LANG_ZH:
        return zh
    return _EN.get(zh, zh)


# ---------------------------------------------------------------------------
# 英文翻译表(key 必须与源码里的中文完全一致)
# ---------------------------------------------------------------------------
_EN: dict[str, str] = {
    # ---- 主窗口 app.py ----
    "&文件": "&File",
    "&编辑": "&Edit",
    "&帮助": "&Help",
    "语言(&L)": "&Language",
    "贴图通道编辑器": "Texture Channel Editor",
    "主工具栏": "Main Toolbar",
    "编辑模式": "Edit Mode",
    "互转模式": "Convert Mode",
    "加载 RGBA": "Load RGBA",
    "加载 RGBA 并 unpack…": "Load RGBA and unpack…",
    "保存工程": "Save Project",
    "保存工程…": "Save Project…",
    "加载工程": "Open Project",
    "加载工程…": "Open Project…",
    "导出贴图": "Export Map",
    "导出贴图…": "Export Map…",
    "撤销": "Undo",
    "重做": "Redo",
    "退出": "Exit",
    "关于": "About",
    "就绪": "Ready",
    "选择导出路径": "Choose Export Path",
    "已导出: {}": "Exported: {}",
    "导出失败 ({}): {}": "Export failed ({}): {}",
    "没有可撤销的操作": "Nothing to undo",
    "没有可重做的操作": "Nothing to redo",
    "插件「{}」加载失败: {}": "Failed to load plugin \"{}\": {}",
    "插件「{}」缺少依赖 {},已跳过": "Plugin \"{}\" is missing dependency {}, skipped",
    "输出规格: {}×{}, preset={}": "Output spec: {}×{}, preset={}",
    "贴图通道编辑器\n\nMVP:4 槽 R/G/B/A 编辑 + 实时预览 + 格式互转。\ncore 算法见 src/core/,UI 见 src/ui/。":
        "Texture Channel Editor\n\n4-slot R/G/B/A editing + live preview + format conversion.\ncore algorithms in src/core/, UI in src/ui/.",
    # ---- 通道网格 channel_grid.py ----
    "(全空)": "(empty)",
    "4 个槽全空,无数据可导出": "All 4 slots are empty, nothing to export",
    "{}/4 槽有数据": "{}/4 slots have data",
    "✓ 通道 mask: {}    |    拖一张 RGBA 贴图到这里 / 点框体 / 「加载 RGBA…」选图":
        "✓ Channel mask: {}    |    Drop an RGBA map here / click the box / use \"Load RGBA…\"",
    "加载 RGBA → 自动 unpack": "Load RGBA → auto unpack",
    "加载 RGBA 并按源格式 unpack": "Load RGBA and unpack by source format",
    "加载 RGBA…": "Load RGBA…",
    "先编辑": "Edit First",
    "导入前": "before import",
    "导入后先编辑": "Edit After Import",
    "导入图片后,先弹复杂编辑窗口(可做 PS 风格调整 / 混合 / 曲线 / 缩放 pan),\n应用后再按 R/G/B/A 位置拆到 4 槽":
        "After importing an image, open the advanced editor first (PS-style adjustments / blending / curves / zoom & pan),\nthen split into the 4 slots by R/G/B/A when applied",
    "工程": "Project",
    "工程已保存: {}": "Project saved: {}",
    "保存工程失败: {}": "Failed to save project: {}",
    "加载工程失败 ({}): {}": "Failed to open project ({}): {}",
    "选择 RGBA 源图": "Choose RGBA Source Image",
    "选择工程的 project.json 或旧工作区 JSON": "Choose project.json or a legacy workspace JSON",
    "选择或新建工程目录（将在其中创建 project.json）":
        "Choose or create a project directory (project.json will be created inside)",
    "读图失败 ({}): {}": "Failed to read image ({}): {}",
    "通道数 {} 不支持(需要 1/3/4): {}": "Unsupported channel count {} (need 1/3/4): {}",
    "槽 {} 加载失败: {}": "Slot {} failed to load: {}",
    "已导入 {}（{}×{}, {}, {} 格式），": "Imported {} ({}×{}, {}, {} format), ",
    "打开复杂编辑窗口(对 {} 进行预先调整)…": "Opening advanced editor (pre-adjust {})…",
    "已取消预先编辑,放弃本次导入": "Pre-edit cancelled, import aborted",
    "预先编辑完成,继续按 R/G/B/A 拆槽": "Pre-edit done, continuing to split into R/G/B/A slots",
    "预先编辑 - {}  (完成后按 R/G/B/A 拆到 4 槽)":
        "Pre-edit - {}  (split into 4 slots by R/G/B/A when done)",
    "发现自动恢复数据": "Auto-recovery Data Found",
    "检测到比正式保存更新的操作数据，是否恢复？":
        "Unsaved changes newer than the last save were detected. Restore them?",
    "已恢复上次未正式保存的操作数据": "Restored unsaved changes from last session",
    "自动保存失败: {}": "Auto-save failed: {}",
    "源 RGBA 通道(未勾选=不导入,视为空):": "Source RGBA channels (unchecked = not imported, treated as empty):",
    "📥  拖一张 RGBA 贴图到这里,或点框体 / 「加载 RGBA…」选图 — 自动按 R/G/B/A 位置展开到 4 槽":
        "📥  Drop an RGBA map here, or click the box / use \"Load RGBA…\" — it expands into 4 slots by R/G/B/A automatically",
    "新基线": "new baseline",
    "载入 RGBA → 自动 unpack:": "Load RGBA → auto unpack:",
    "{}已加载: {}": "{} loaded: {}",
    "旧工作区": "legacy workspace",
    "用户编辑": "user edit",
    # ---- 槽位 slot_widget.py ----
    "显示名:": "Display Name:",
    "语义:": "Semantic:",
    "源 token:": "Source Token:",
    "颜色空间标签:": "Color Space:",
    "源文件:": "Source File:",
    "导出": "Export",
    "替换": "Replace",
    "清空": "Clear",
    "复杂编辑": "Advanced Edit",
    "打开": "Open",
    "打开独立窗口:PS 风格调整 + 15 种混合模式 + 3 点 LUT + 第二张图":
        "Open a separate window: PS-style adjustments + 15 blend modes + 3-point LUT + second image",
    "把当前通道(已应用 token)导出为单通道灰度 PNG":
        "Export the current channel (token applied) as a single-channel grayscale PNG",
    "用另一个源文件替换本槽(保留 token / invert / semantic / colorspace)":
        "Replace this slot's source file (keeping token / invert / semantic / colorspace)",
    "清空本槽所有数据": "Clear all data in this slot",
    "选择 {} 通道源文件": "Choose source file for channel {}",
    "导出 {} 通道": "Export channel {}",
    "导出 {} 通道失败: {}": "Failed to export channel {}: {}",
    "替换 {} 通道源文件": "Replace source file of channel {}",
    "复杂编辑 - {} 槽": "Advanced Edit - Slot {}",
    "{} 槽为空,先载入源文件再导出": "Slot {} is empty, load a source file first",
    "{} 槽为空,先载入源文件或 token 提取后再编辑":
        "Slot {} is empty, load a source file or extract from a token first",
    "{} 槽原始贴图加载失败: {}": "Failed to load source image for slot {}: {}",
    "{} 槽已应用复杂编辑结果": "Slot {} applied advanced edit result",
    "{} 槽已替换源文件: {}": "Slot {} source file replaced: {}",
    "{} 槽已清空": "Slot {} cleared",
    "{} 槽载入源文件: {}": "Slot {} loaded source file: {}",
    "{} 通道已导出到: {}": "Channel {} exported to: {}",
    "(可填中文/英文)": "(Chinese or English)",
    "(拖入贴图或点浏览)": "(drop an image or browse)",
    "R(取红通道)": "R (red channel)",
    "G(取绿通道)": "G (green channel)",
    "B(取蓝通道)": "B (blue channel)",
    "A(取透明通道)": "A (alpha channel)",
    "INV_R(反相红通道)": "INV_R (inverted red)",
    "INV_G(反相绿通道)": "INV_G (inverted green)",
    "INV_B(反相蓝通道)": "INV_B (inverted blue)",
    "INV_A(反相透明通道)": "INV_A (inverted alpha)",
    "BLACK(全黑 0)": "BLACK (all 0)",
    "WHITE(全白 255)": "WHITE (all 255)",
    "当前版本仅记录语义标签,不会改写通道数值或 PNG gamma。":
        "This version only records the semantic tag; channel values and PNG gamma are not modified.",
    # ---- 输出规格 output_spec_widget.py ----
    "输出规格": "Output Spec",
    "尺寸档位:": "Size Preset:",
    "自定义 (W × H):": "Custom (W × H):",
    "resize 模式:": "Resize Mode:",
    "resize 滤镜:": "Resize Filter:",
    "force_pot (对齐到 2 的幂)": "force_pot (align to power of 2)",
    "POT 策略:": "POT Policy:",
    "导出路径:": "Export Path:",
    "(选择 PNG / TIFF / EXR 输出位置)": "(choose PNG / TIFF / EXR output location)",
    "请先选择导出路径（点右侧「浏览…」）": "Choose an export path first (click \"Browse…\" on the right)",
    "已选择导出路径: {}": "Export path selected: {}",
    "输出规格已更新 → {}×{}": "Output spec updated → {}×{}",
    # ---- 预览 preview_widget.py ----
    "预览": "Preview",
    "查看大图": "View Full Size",
    "查看 - {}": "View - {}",
    "源格式": "Source Format",
    "empty\n(点击查看)": "empty\n(click to view)",
    "点击查看大图(滚轮缩放 / 右键 pan / 双击重置)":
        "Click to view full size (wheel zoom / right-drag pan / double-click reset)",
    "(滚轮缩放 / 右键 pan / 双击重置)": "(wheel zoom / right-drag pan / double-click reset)",
    "💡 点击任意缩略图可看大图(滚轮缩放 / 右键 pan / 双击重置)":
        "💡 Click any thumbnail for full size (wheel zoom / right-drag pan / double-click reset)",
    "缩放: {:.0f}%   尺寸: {}×{}   ": "Zoom: {:.0f}%   Size: {}×{}   ",
    # ---- 互转面板 transcode_panel.py ----
    "源 preset:": "Source Preset:",
    "目标 preset:": "Target Preset:",
    "载入源图…": "Load Source…",
    "导出目标图": "Export Target",
    "导出目标图…": "Export Target…",
    "源 RGBA": "Source RGBA",
    "目标 RGBA": "Target RGBA",
    "载入后显示": "Shown after loading",
    "实时转换结果": "Live conversion result",
    "选择源图": "Choose Source Image",
    "未载入源图。": "No source image loaded.",
    "已载入源图: {} ({}×{}, {})": "Source loaded: {} ({}×{}, {})",
    "未知 preset: {}": "Unknown preset: {}",
    "互转图已导出: {}  ({} → {})": "Converted map exported: {}  ({} → {})",
    "请先在互转模式载入源图(顶部「载入源图…」)":
        "Load a source image in Convert Mode first (\"Load Source…\" at the top)",
    "转换失败: {}": "Conversion failed: {}",
    "转换失败 ({}→{}): {}": "Conversion failed ({}→{}): {}",
    "源: {}  →  目标: {}\n": "Source: {}  →  Target: {}\n",
    "源图: {}\n  尺寸: {}×{}  精度: {}": "Source: {}\n  Size: {}×{}  Depth: {}",
    "  实际映射: {}": "  Actual mapping: {}",
    "  源尺寸: {}×{}\n": "  Source size: {}×{}\n",
    # ---- 复杂编辑器 advanced_editor_dialog.py ----
    "复杂编辑": "Advanced Edit",
    "复杂编辑 - 第二张图（可再嵌套）": "Advanced Edit - Second Image (nestable)",
    "混合（原图 + 第二张图）": "Blend (Original + Second Image)",
    "第二张图（支持拖拽 / 点击 / 浏览 / 编辑）:": "Second image (drop / click / browse / edit):",
    "（空 = 不混合）": "(empty = no blending)",
    "源 RGBA 通道:": "Source RGBA Channels:",
    "尺寸映射:": "Size Mapping:",
    "拉伸/缩放:": "Stretch/Scale:",
    "偏移:": "Offset:",
    "锁定": "Lock",
    "浏览…": "Browse…",
    "✎ 编辑这张": "✎ Edit This",
    "清空": "Clear",
    "混合模式:": "Blend Mode:",
    "选择第二张图": "Choose Second Image",
    "第二张图加载失败: {}": "Failed to load second image: {}",
    "✓ {}（通道:{} / ": "✓ {} (channels: {} / ",
    "✓（已嵌套编辑）": "✓ (nested edit applied)",
    "📥  拖入 / 点击框体 / 用「浏览」选文件": "📥  Drop / click the box / use \"Browse\" to pick a file",
    "调整（PS 风格）": "Adjustments (PS Style)",
    "旋转（逆时针，自动扩展画布）:": "Rotate (CCW, auto-expand canvas):",
    "亮度（-100 ~ +100）:": "Brightness (-100 ~ +100):",
    "对比（0.0 ~ 2.0）:": "Contrast (0.0 ~ 2.0):",
    "曝光（-2.0 ~ +2.0 EV）:": "Exposure (-2.0 ~ +2.0 EV):",
    "阴影（-100 ~ +100）:": "Shadows (-100 ~ +100):",
    "高光（-100 ~ +100）:": "Highlights (-100 ~ +100):",
    "伽马（0.1 ~ 3.0）:": "Gamma (0.1 ~ 3.0):",
    "饱和度（0.0 ~ 2.0；灰度无效）:": "Saturation (0.0 ~ 2.0; no effect on grayscale):",
    "阈值（0-255，-1=关）:": "Threshold (0-255, -1=off):",
    "色调分离（2-256 级，256=关）:": "Posterize (2-256 levels, 256=off):",
    "{} 级": "{} levels",
    "关": "Off",
    "反相（Invert）": "Invert",
    "曲线（贝塞尔控制点）": "Curve (Bezier Control Points)",
    "点曲线附近空白处 = 加点；双击控制点 = 删除":
        "Click near the curve to add a point; double-click a control point to delete",
    "原样": "Original",
    "提亮": "Brighten",
    "压暗": "Darken",
    "高对比": "High Contrast",
    "反转": "Invert",
    "重置曲线": "Reset Curve",
    "原图（应用前）": "Original (Before)",
    "结果（应用后）": "Result (After)",
    "适应窗口": "Fit to Window",
    "重置所有参数": "Reset All Parameters",
    "应用并关闭": "Apply && Close",
    "取消": "Cancel",
    "缩放: 原图 {:.0f}% / 结果 {:.0f}%": "Zoom: original {:.0f}% / result {:.0f}%",
    "（滚轮缩放 / 右键平移 / 双击重置）": "(wheel zoom / right-drag pan / double-click reset)",
    "缩放: 100% / 100%": "Zoom: 100% / 100%",
    # ---- Skybox 主窗口 skybox_noise/main_window.py ----
    "输入": "Input",
    "原图": "Original",
    "原图 {}x{}": "Original {}x{}",
    "📂 打开图像": "📂 Open Image",
    "打开贴图": "Open Image",
    "预览": "Preview",
    "合成预览": "Composite Preview",
    "投影方式:": "Projection:",
    "噪声类型:": "Noise Type:",
    "噪声参数": "Noise Parameters",
    "空间尺度": "Spatial Scale",
    "域扭曲强度": "Domain Warp",
    "合成 / Mask": "Composite / Mask",
    "合成强度": "Composite Strength",
    "Mask 软度": "Mask Softness",
    "Caustics（仅 Caustics 噪声生效）": "Caustics (only for Caustics noise)",
    "细线频率": "Line Frequency",
    "细线权重": "Line Weight",
    "线条锐度": "Line Sharpness",
    "法线扰动": "Normal Perturbation",
    "后处理": "Post-processing",
    "冷色调偏移": "Cool Tint",
    "高光压起点": "Highlight Knee",
    "高光上限": "Highlight Cap",
    "↺ 恢复默认": "↺ Reset Defaults",
    "已恢复默认参数": "Defaults restored",
    "🔄 强制重算": "🔄 Force Recompute",
    "🧩 编辑节点图": "🧩 Edit Node Graph",
    "自定义 (节点图)": "Custom (Node Graph)",
    "💾 保存合成图": "💾 Save Composite",
    "💾 保存法线": "💾 Save Normal",
    "💾 保存 mask": "💾 Save Mask",
    "保存": "Save",
    "保存失败": "Save Failed",
    "加载失败": "Load Failed",
    "无数据": "No Data",
    "请先生成图像": "Generate an image first",
    "已保存: {}": "Saved: {}",
    "已加载: {}  →  投影: {}": "Loaded: {}  →  projection: {}",
    "渲染中 [{}]…": "Rendering [{}]…",
    "渲染完成 {}x{}, {:.2f}s": "Render done {}x{}, {:.2f}s",
    "渲染失败: {}": "Render failed: {}",
    "参数已变 — 400ms 后重算…": "Parameters changed — recomputing in 400ms…",
    "节点图已修改 — 400ms 后重算…": "Node graph changed — recomputing in 400ms…",
    "正在取消旧渲染，随后计算最新参数…": "Cancelling previous render, then computing latest parameters…",
    "正在生成最新的全分辨率结果，完成后自动保存…": "Rendering the latest full-resolution result, auto-saving when done…",
    "{}（已取消待处理的保存请求）": "{} (pending save request cancelled)",
    "当前源图不是 8-bit，请改存 PNG/TIFF/EXR": "Current source is not 8-bit; save as PNG/TIFF/EXR instead",
    "浮点/HDR 结果请保存为 EXR 或 TIFF，PNG 会丢失 HDR 范围":
        "Save float/HDR results as EXR or TIFF; PNG loses the HDR range",
    "图像 (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff *.exr)":
        "Images (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff *.exr)",
    "✓ 加速 25-40x": "✓ 25-40x speedup",
    "✗ (numpy fallback, 慢)": "✗ (numpy fallback, slow)",
    "全分辨率": "Full Resolution",
    # ---- 节点编辑器 node_editor.py ----
    "节点图编辑器 — 自定义噪声": "Node Graph Editor — Custom Noise",
    "📂 加载图": "📂 Load Graph",
    "💾 保存图": "💾 Save Graph",
    "🎯 自动整理": "🎯 Auto Layout",
    "↩ 撤销": "↩ Undo",
    "↪ 重做": "↪ Redo",
    "👁 预览": "👁 Preview",
    "自动预览": "Auto Preview",
    "噪声预览:": "Noise Preview:",
    "噪声预览 {}x{}": "Noise preview {}x{}",
    "节点图预览": "Node Graph Preview",
    "未选中节点": "No Node Selected",
    "未选中节点 (在画布上点选)": "No node selected (click one on the canvas)",
    "浏览…": "Browse…",
    "选择贴图": "Choose Image",
    "节点图 (*.json)": "Node Graph (*.json)",
    "保存节点图": "Save Node Graph",
    "加载节点图": "Load Node Graph",
    "已保存: {}": "Saved: {}",
    "已加载: {}": "Loaded: {}",
    "保存失败: {}": "Save failed: {}",
    "加载失败: {}": "Load failed: {}",
    "已连接 {} → {}": "Connected {} → {}",
    "连接失败: {}": "Connection failed: {}",
    "预览正常 (范围 {:.3f} ~ {:.3f})": "Preview OK (range {:.3f} ~ {:.3f})",
    "预览出错: {}": "Preview error: {}",
    "预览: {}": "Preview: {}",
    "{}\n(无图像)": "{}\n(no image)",
    "{}%  ({}x{})   滚轮缩放 / 右键平移 / 双击复位":
        "{}%  ({}x{})   wheel zoom / right-drag pan / double-click reset",
    # ---- 节点类型 node_types.py ----
    "坐标": "Coordinates",
    "球面坐标源": "Spherical Coordinates",
    "提供球面坐标(投影自动计算)。噪声源未连坐标时默认使用它。":
        "Provides spherical coordinates (computed from the projection). Used by default when a noise source has no coordinate input.",
    "噪声": "Noise",
    "FBM (基础)": "FBM (Basic)",
    "FBM 噪声": "FBM Noise",
    "标准分形 Perlin,通用云团/扰动。": "Standard fractal Perlin, general-purpose clouds/distortion.",
    "Caustics (焦散)": "Caustics",
    "焦散噪声": "Caustics Noise",
    "域扭曲 + 锐化 + 细线栅格,适合水下焦散/能量场。":
        "Domain warp + sharpen + thin-line lattice, good for underwater caustics/energy fields.",
    "Voronoi (细胞)": "Voronoi (Cells)",
    "Voronoi 细胞": "Voronoi Cells",
    "双层 FBM 距离锐化,适合晶格/生物组织。":
        "Two-layer FBM distance sharpening, good for lattices/organic tissue.",
    "Perlin 单频": "Perlin Single-octave",
    "单倍频 Perlin,输出约 [-1,1],适合做低频基底。":
        "Single-octave Perlin, output roughly [-1,1], good as a low-frequency base.",
    "数学": "Math",
    "数学运算": "Math Operation",
    "A 与 B 做数学运算;B 未连接时用「标量」。":
        "Math operation on A and B; uses \"Scalar\" when B is unconnected.",
    "相加 (A+B)": "Add (A+B)",
    "相减 (A-B)": "Subtract (A-B)",
    "相乘 (A*B)": "Multiply (A*B)",
    "相除 (A/B)": "Divide (A/B)",
    "取大 (Max)": "Max",
    "取小 (Min)": "Min",
    "幂 (|A|^B)": "Power (|A|^B)",
    "绝对值": "Absolute",
    "标量(未连 B 时用)": "Scalar (used when B unconnected)",
    "混合": "Blend",
    "PS 风格混合模式,复用主编辑器 15 种模式。":
        "PS-style blend modes, reusing the main editor's 15 modes.",
    "混合模式": "Blend Mode",
    "混合强度": "Blend Strength",
    "变换": "Transform",
    "域扭曲": "Domain Warp",
    "用低频噪声扭曲坐标,再喂给噪声源,产生流动感。":
        "Warps coordinates with low-frequency noise before feeding the source, creating a flowing feel.",
    "扭曲强度": "Warp Strength",
    "扭曲频率": "Warp Frequency",
    "后处理": "Post-processing",
    "亮度/对比度/伽马": "Brightness/Contrast/Gamma",
    "亮度": "Brightness",
    "对比度": "Contrast",
    "伽马": "Gamma",
    "范围重映射": "Range Remap",
    "把噪声值从 [输入下限, 输入上限] 映射到 [输出下限, 输出上限]。":
        "Remaps noise values from [in min, in max] to [out min, out max].",
    "输入下限": "Input Min",
    "输入上限": "Input Max",
    "输出下限": "Output Min",
    "输出上限": "Output Max",
    "源": "Source",
    "导入噪声贴图": "Import Noise Map",
    "导入自己的噪声贴图(灰度/彩色均可),按 UV 平铺采样。":
        "Import your own noise map (grayscale or color), sampled with UV tiling.",
    "贴图文件": "Image File",
    "平铺次数": "Tile Count",
    "平铺循环": "Tile Wrap",
    "取用通道": "Channel",
    "亮度(平均)": "Luminance (average)",
    "R 通道": "R Channel",
    "G 通道": "G Channel",
    "B 通道": "B Channel",
    "输出": "Output",
    "最终噪声": "Final Noise",
    "图上第一个「输出」节点即最终噪声场。":
        "The first \"Output\" node on the graph is the final noise field.",
    "结果": "Result",
    "场": "Field",
    "基底": "Base",
    "叠加": "Overlay",
    "取反": "Invert",
    "运算": "Operation",
    "钳制到输出范围": "Clamp to Output Range",
    "未知节点类型: {}": "Unknown node type: {}",
    # ---- 渲染 worker.py ----
    "准备中…": "Preparing…",
    "UV 网格…": "UV grid…",
    "生成 {} 噪声…": "Generating {} noise…",
    "Mask / 渐变…": "Mask / gradient…",
    "合成…": "Compositing…",
    "法线贴图…": "Normal map…",
    "完成 ({:.2f}s)": "Done ({:.2f}s)",
    # ---- 投影 projections.py / 混合模式 ----
    "标准全景 / 天空球": "Standard panorama / sky sphere",
    # ---- 第二张图尺寸映射 mapping.py ----
    "拉伸铺满": "Stretch to Fill",
    "等比适应（留黑边）": "Fit (Letterbox)",
    "等比截取": "Crop to Fill",
    "平铺": "Tile",
    # ---- 15 种混合模式 blend_modes.py ----
    "正常 (Normal)": "Normal",
    "正片叠底 (Multiply)": "Multiply",
    "滤色 (Screen)": "Screen",
    "叠加 (Overlay)": "Overlay",
    "变暗 (Darken)": "Darken",
    "变亮 (Lighten)": "Lighten",
    "颜色减淡 (Color Dodge)": "Color Dodge",
    "颜色加深 (Color Burn)": "Color Burn",
    "强光 (Hard Light)": "Hard Light",
    "柔光 (Soft Light)": "Soft Light",
    "差值 (Difference)": "Difference",
    "排除 (Exclusion)": "Exclusion",
    "线性加深 (Add / Linear Dodge)": "Add (Linear Dodge)",
    "线性减淡 (Subtract / Linear Burn)": "Subtract (Linear Burn)",
    "划分 (Divide)": "Divide",
    # ---- 复杂编辑器补充 ----
    "复杂编辑只支持灰度/RGB/RGBA，收到 {}":
        "Advanced edit only supports grayscale/RGB/RGBA, got {}",
    "复杂编辑只支持 H×W 或 H×W×3/4，收到 {}":
        "Advanced edit only supports H×W or H×W×3/4, got {}",
    "✓ {}（通道:{} / {}）": "✓ {} (channels: {} / {})",
}

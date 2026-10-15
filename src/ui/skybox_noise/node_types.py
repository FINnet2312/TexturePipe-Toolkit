"""节点类型注册表(Skybox 自定义噪声)。

每种节点:类型 id / 显示名 / 分组 / 输入输出端口 / 参数定义 / 求值函数。
求值函数签名:eval(params: dict, inputs: list[ndarray|None], ctx: dict) -> list[ndarray]
ctx 由渲染管线注入(node_graph.GraphEvaluator 的 ctx 参数):
    - "xyz": HxWx3 球面坐标
    - "uv":  HxWx2 UV 坐标
    - "load_texture": callable(path) -> float32 [0,1] HxWx3
"""
from __future__ import annotations

import numpy as np

from .core import NoiseContext
from .node_graph import PORT_COORD, PORT_FIELD, Port
from src.ui.advanced_editor_components.blend_modes import BLEND_BY_ID, BLEND_MODES


# ---------------------------------------------------------------------------
# 参数定义
# ---------------------------------------------------------------------------
class ParamDef:
    """kind: float(滑杆) | int(整数滑杆) | choice(下拉) | file(路径+浏览) | bool(勾选)"""

    def __init__(self, key, label, default, min_v=None, max_v=None,
                 step=0.01, decimals=3, kind="float", choices=None):
        self.key = key
        self.label = label
        self.default = default
        self.min_v = min_v
        self.max_v = max_v
        self.step = step
        self.decimals = decimals
        self.kind = kind
        # choices: [(value, label), ...]
        self.choices = choices or []


def _F(key, label, default, min_v, max_v, step=0.01, decimals=3):
    return ParamDef(key, label, default, min_v, max_v, step, decimals)


def _I(key, label, default, min_v, max_v):
    return ParamDef(key, label, default, min_v, max_v, 1, 0, kind="int")


def _C(key, label, default, choices):
    return ParamDef(key, label, default, kind="choice", choices=choices)


def _FILE(key, label):
    return ParamDef(key, label, "", kind="file")


def _BOOL(key, label, default=False):
    return ParamDef(key, label, default, kind="bool")


# ---------------------------------------------------------------------------
# 节点定义
# ---------------------------------------------------------------------------
class NodeDef:
    def __init__(self, type_id, label, category, inputs, outputs,
                 params, eval_fn, hint=""):
        self.type_id = type_id
        self.label = label
        self.category = category
        self.inputs = inputs
        self.outputs = outputs
        self.params = params
        self.eval = eval_fn
        self.hint = hint

    def default_params(self) -> dict:
        return {p.key: p.default for p in self.params}


CAT_SOURCE = "源"
CAT_NOISE = "噪声"
CAT_MATH = "数学"
CAT_BLEND = "混合"
CAT_TRANSFORM = "变换"
CAT_POST = "后处理"
CAT_OUTPUT = "输出"

NODE_CATEGORIES = [
    CAT_SOURCE, CAT_NOISE, CAT_MATH, CAT_BLEND, CAT_TRANSFORM, CAT_POST,
    CAT_OUTPUT,
]

_NOISE_PARAMS = [
    _F("scale", "空间尺度", 3.8, 0.5, 20.0),
    _I("octaves", "Octaves", 4, 1, 8),
    _F("persistence", "Persistence", 0.5, 0.1, 1.0),
    _F("lacunarity", "Lacunarity", 2.05, 1.5, 4.0),
    _I("seed", "Seed", 1337, 0, 9999),
    _F("warp_amount", "域扭曲", 0.85, 0.0, 2.0),
    _F("caustic_power", "线条锐度", 1.15, 0.8, 3.0),
    _F("lattice_freq", "细线频率", 9.0, 3.0, 20.0),
    _F("lattice_weight", "细线权重", 0.55, 0.0, 1.0),
]


def _noise_context(ctx: dict, seed: int) -> NoiseContext:
    """每个 GraphEvaluator 持有自己的噪声状态，绝不跨线程共享。"""
    engine = ctx.get("noise_context")
    if not isinstance(engine, NoiseContext):
        engine = NoiseContext(seed)
        ctx["noise_context"] = engine
    return engine


def _noise_eval(noise_type):
    def _eval(params, inputs, ctx):
        coord = inputs[0] if inputs[0] is not None else ctx["xyz"]
        x, y, z = coord[..., 0], coord[..., 1], coord[..., 2]
        p = {
            "noise_scale": params["scale"],
            "octaves": int(params["octaves"]),
            "persistence": params["persistence"],
            "lacunarity": params["lacunarity"],
            "seed": int(params["seed"]),
            "warp_amount": params["warp_amount"],
            "caustic_power": params["caustic_power"],
            "lattice_freq": params["lattice_freq"],
            "lattice_weight": params["lattice_weight"],
        }
        engine = _noise_context(ctx, int(params["seed"]))
        return [engine.gen_noise(noise_type, x, y, z, p)]
    return _eval


def _eval_perlin(params, inputs, ctx):
    coord = inputs[0] if inputs[0] is not None else ctx["xyz"]
    x, y, z = coord[..., 0], coord[..., 1], coord[..., 2]
    s = params["scale"]
    seed = int(params["seed"])
    engine = _noise_context(ctx, seed)
    return [engine.perlin3d(x * s, y * s, z * s, seed=seed)]


_TEXTURE_CHANNELS = [
    (0, "R 通道"), (1, "G 通道"), (2, "B 通道"), (3, "亮度(平均)"),
]


def _eval_texture(params, inputs, ctx):
    H, W = ctx["xyz"].shape[:2]
    path = params.get("path", "")
    if not path:
        return [np.zeros((H, W), dtype=np.float32)]
    tex = ctx["load_texture"](path)  # float32 [0,1] HxWx3
    u = ctx["uv"][..., 0]
    v = ctx["uv"][..., 1]
    scale = max(float(params.get("scale", 1.0)), 1e-4)
    if params.get("tile", True):
        tu = (u * scale) % 1.0
        tv = (v * scale) % 1.0
    else:
        tu = np.clip(u * scale, 0, 1.0)
        tv = np.clip(v * scale, 0, 1.0)
    th, tw = tex.shape[:2]
    xi = np.clip((tu * tw).astype(np.int64), 0, tw - 1)
    yi = np.clip((tv * th).astype(np.int64), 0, th - 1)
    ch = int(params.get("channel", 0))
    if ch == 3:
        field = tex[yi, xi].mean(axis=-1)
    else:
        field = tex[yi, xi, ch]
    field = (field - 0.5) * float(params.get("contrast", 1.0)) \
        + 0.5 + float(params.get("brightness", 0.0))
    return [np.clip(field, 0, 1)]


_MATH_OPS = {
    "add": ("相加 (A+B)", lambda a, b: a + b),
    "subtract": ("相减 (A-B)", lambda a, b: a - b),
    "multiply": ("相乘 (A*B)", lambda a, b: a * b),
    "divide": ("相除 (A/B)", lambda a, b: a / np.maximum(b, 1e-6)),
    "maximum": ("取大 (Max)", np.maximum),
    "minimum": ("取小 (Min)", np.minimum),
    "power": ("幂 (|A|^B)", lambda a, b: np.power(np.abs(a), b)),
    "absolute": ("绝对值", lambda a, b: np.abs(a)),
    "negate": ("取反", lambda a, b: -a),
}


def _eval_math(params, inputs, ctx):
    shape = ctx["xyz"].shape[:2]
    # A 未连接 → 0 场;B 未连接 → 标量(常量)
    a = inputs[0] if inputs[0] is not None else \
        np.zeros(shape, dtype=np.float32)
    if inputs[1] is not None:
        b = inputs[1]
    else:
        b = np.full_like(a, float(params["scalar"]))
    return [_MATH_OPS[params["op"]][1](a, b)]


def _eval_blend(params, inputs, ctx):
    shape = ctx["xyz"].shape[:2]
    base = inputs[0] if inputs[0] is not None else np.zeros(shape, dtype=np.float32)
    blend = inputs[1] if inputs[1] is not None else np.zeros_like(base)
    fn = BLEND_BY_ID.get(params["mode"], BLEND_BY_ID["normal"])
    # 混合函数用 0..255 标度;先 clip 到 [0,1]
    out = fn(np.clip(base, 0, 1) * 255.0, np.clip(blend, 0, 1) * 255.0) / 255.0
    a = float(params["amount"])
    out = base * (1.0 - a) + out * a
    return [np.clip(out, 0, 1)]


def _eval_warp(params, inputs, ctx):
    coord = inputs[0] if inputs[0] is not None else ctx["xyz"]
    x, y, z = coord[..., 0], coord[..., 1], coord[..., 2]
    s = float(params["scale"])
    octaves = int(params["octaves"])
    pers = float(params["persistence"])
    lac = float(params["lacunarity"])
    seed = int(params["seed"])
    amt = float(params["amount"])
    engine = _noise_context(ctx, seed)
    wx = engine.fbm3d(
        x * s + 31.7, y * s + 31.7, z * s + 31.7,
        octaves, pers, lac, seed=seed,
    ) * amt
    wy = engine.fbm3d(
        x * s + 91.3, y * s + 91.3, z * s + 91.3,
        octaves, pers, lac, seed=seed,
    ) * amt
    wz = engine.fbm3d(
        x * s + 157.1, y * s + 157.1, z * s + 157.1,
        octaves, pers, lac, seed=seed,
    ) * amt
    return [np.stack([x + wx, y + wy, z + wz], axis=-1)]


def _eval_adjust(params, inputs, ctx):
    shape = ctx["xyz"].shape[:2]
    f = inputs[0] if inputs[0] is not None else np.zeros(shape, dtype=np.float32)
    f = (f - 0.5) * float(params["contrast"]) + 0.5 + float(params["brightness"])
    f = np.clip(f, 0, 1) ** float(params["gamma"])
    return [f]


def _eval_remap(params, inputs, ctx):
    shape = ctx["xyz"].shape[:2]
    f = inputs[0] if inputs[0] is not None else np.zeros(shape, dtype=np.float32)
    lo, hi = float(params["in_lo"]), float(params["in_hi"])
    denom = max(hi - lo, 1e-6)
    out_lo, out_hi = float(params["out_lo"]), float(params["out_hi"])
    out = (f - lo) / denom * (out_hi - out_lo) + out_lo
    if params["clamp"]:
        out = np.clip(out, min(out_lo, out_hi), max(out_lo, out_hi))
    return [out]


def _eval_output(params, inputs, ctx):
    shape = ctx["xyz"].shape[:2]
    f = inputs[0] if inputs[0] is not None else np.zeros(shape, dtype=np.float32)
    return [f]


def _eval_coord(params, inputs, ctx):
    return [ctx["xyz"]]


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
def _build_registry() -> dict[str, NodeDef]:
    reg: dict[str, NodeDef] = {}

    reg["coord_source"] = NodeDef(
        "coord_source", "球面坐标源", CAT_SOURCE,
        inputs=[], outputs=[Port("xyz", PORT_COORD)],
        params=[], eval_fn=_eval_coord,
        hint="提供球面坐标(投影自动计算)。噪声源未连坐标时默认使用它。",
    )
    reg["noise_fbm"] = NodeDef(
        "noise_fbm", "FBM 噪声", CAT_NOISE,
        inputs=[Port("坐标", PORT_COORD)], outputs=[Port("场", PORT_FIELD)],
        params=_NOISE_PARAMS, eval_fn=_noise_eval("FBM (基础)"),
        hint="标准分形 Perlin,通用云团/扰动。",
    )
    reg["noise_caustics"] = NodeDef(
        "noise_caustics", "焦散噪声", CAT_NOISE,
        inputs=[Port("坐标", PORT_COORD)], outputs=[Port("场", PORT_FIELD)],
        params=_NOISE_PARAMS, eval_fn=_noise_eval("Caustics (焦散)"),
        hint="域扭曲 + 锐化 + 细线栅格,适合水下焦散/能量场。",
    )
    reg["noise_voronoi"] = NodeDef(
        "noise_voronoi", "Voronoi 细胞", CAT_NOISE,
        inputs=[Port("坐标", PORT_COORD)], outputs=[Port("场", PORT_FIELD)],
        params=_NOISE_PARAMS, eval_fn=_noise_eval("Voronoi (细胞)"),
        hint="双层 FBM 距离锐化,适合晶格/生物组织。",
    )
    reg["noise_perlin"] = NodeDef(
        "noise_perlin", "Perlin 单频", CAT_NOISE,
        inputs=[Port("坐标", PORT_COORD)], outputs=[Port("场", PORT_FIELD)],
        params=[
            _F("scale", "空间尺度", 3.8, 0.5, 20.0),
            _I("seed", "Seed", 1337, 0, 9999),
        ],
        eval_fn=_eval_perlin,
        hint="单倍频 Perlin,输出约 [-1,1],适合做低频基底。",
    )
    reg["noise_texture"] = NodeDef(
        "noise_texture", "导入噪声贴图", CAT_NOISE,
        inputs=[], outputs=[Port("场", PORT_FIELD)],
        params=[
            _FILE("path", "贴图文件"),
            _C("channel", "取用通道", 0, _TEXTURE_CHANNELS),
            _F("scale", "平铺次数", 1.0, 0.1, 10.0),
            _BOOL("tile", "平铺循环", True),
            _F("brightness", "亮度", 0.0, -0.5, 0.5),
            _F("contrast", "对比度", 1.0, 0.2, 3.0),
        ],
        eval_fn=_eval_texture,
        hint="导入自己的噪声贴图(灰度/彩色均可),按 UV 平铺采样。",
    )
    reg["math"] = NodeDef(
        "math", "数学运算", CAT_MATH,
        inputs=[Port("A", PORT_FIELD), Port("B", PORT_FIELD)],
        outputs=[Port("结果", PORT_FIELD)],
        params=[
            _C("op", "运算", "add", list(_MATH_OPS.items())),
            _F("scalar", "标量(未连 B 时用)", 0.5, -2.0, 2.0),
        ],
        eval_fn=_eval_math,
        hint="A 与 B 做数学运算;B 未连接时用「标量」。",
    )
    blend_choices = [(mid, label) for mid, label, _fn in BLEND_MODES]
    reg["blend"] = NodeDef(
        "blend", "混合", CAT_BLEND,
        inputs=[Port("基底", PORT_FIELD), Port("叠加", PORT_FIELD)],
        outputs=[Port("结果", PORT_FIELD)],
        params=[
            _C("mode", "混合模式", "overlay", blend_choices),
            _F("amount", "混合强度", 1.0, 0.0, 1.0),
        ],
        eval_fn=_eval_blend,
        hint="PS 风格混合模式,复用主编辑器 15 种模式。",
    )
    reg["domain_warp"] = NodeDef(
        "domain_warp", "域扭曲", CAT_TRANSFORM,
        inputs=[Port("坐标", PORT_COORD)], outputs=[Port("坐标", PORT_COORD)],
        params=[
            _F("amount", "扭曲强度", 0.3, 0.0, 1.5),
            _F("scale", "扭曲频率", 1.0, 0.1, 6.0),
            _I("octaves", "Octaves", 3, 1, 6),
            _F("persistence", "Persistence", 0.5, 0.1, 1.0),
            _F("lacunarity", "Lacunarity", 2.0, 1.5, 4.0),
            _I("seed", "Seed", 1337, 0, 9999),
        ],
        eval_fn=_eval_warp,
        hint="用低频噪声扭曲坐标,再喂给噪声源,产生流动感。",
    )
    reg["adjust"] = NodeDef(
        "adjust", "亮度/对比度/伽马", CAT_POST,
        inputs=[Port("场", PORT_FIELD)], outputs=[Port("结果", PORT_FIELD)],
        params=[
            _F("brightness", "亮度", 0.0, -0.5, 0.5),
            _F("contrast", "对比度", 1.0, 0.2, 3.0),
            _F("gamma", "伽马", 1.0, 0.2, 3.0),
        ],
        eval_fn=_eval_adjust,
    )
    reg["remap"] = NodeDef(
        "remap", "范围重映射", CAT_POST,
        inputs=[Port("场", PORT_FIELD)], outputs=[Port("结果", PORT_FIELD)],
        params=[
            _F("in_lo", "输入下限", -1.0, -5.0, 5.0),
            _F("in_hi", "输入上限", 1.0, -5.0, 5.0),
            _F("out_lo", "输出下限", 0.0, -5.0, 5.0),
            _F("out_hi", "输出上限", 1.0, -5.0, 5.0),
            _BOOL("clamp", "钳制到输出范围", True),
        ],
        eval_fn=_eval_remap,
        hint="把噪声值从 [输入下限, 输入上限] 映射到 [输出下限, 输出上限]。",
    )
    reg["output"] = NodeDef(
        "output", "输出", CAT_OUTPUT,
        inputs=[Port("最终噪声", PORT_FIELD)], outputs=[],
        params=[], eval_fn=_eval_output,
        hint="图上第一个「输出」节点即最终噪声场。",
    )
    return reg


NODE_REGISTRY = _build_registry()

# 各分组内节点(按注册顺序)
NODES_BY_CATEGORY: dict[str, list[str]] = {c: [] for c in NODE_CATEGORIES}
for tid, nd in NODE_REGISTRY.items():
    NODES_BY_CATEGORY.setdefault(nd.category, []).append(tid)


def get_node_def(type_id: str) -> NodeDef:
    if type_id not in NODE_REGISTRY:
        raise KeyError(f"未知节点类型: {type_id}")
    return NODE_REGISTRY[type_id]


def default_graph() -> "object":
    """新建一个默认节点图:球面坐标源 → FBM → 输出。"""
    from .node_graph import NodeGraph
    g = NodeGraph()
    src = g.add_node("coord_source", pos=(40, 120),
                     params=get_node_def("coord_source").default_params())
    fbm = g.add_node("noise_fbm", pos=(300, 100),
                     params=get_node_def("noise_fbm").default_params())
    out = g.add_node("output", pos=(600, 120),
                     params=get_node_def("output").default_params())
    g.connect(src.id, 0, fbm.id, 0, NODE_REGISTRY)
    g.connect(fbm.id, 0, out.id, 0, NODE_REGISTRY)
    return g


__all__ = [
    "NODE_REGISTRY", "NODES_BY_CATEGORY", "NODE_CATEGORIES",
    "NodeDef", "ParamDef", "get_node_def", "default_graph",
]

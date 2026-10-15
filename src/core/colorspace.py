"""
ColorSpace — sRGB ↔ Linear 转换。

8bit PNG 在游戏通用方案下:
- BaseColor / Emissive 等 albedo 类用 sRGB
- Roughness / Metallic / AO / Height / Cavity 等数据贴图用 Linear

IO 边界按通道声明的颜色空间处理:
- 读:8bit uint8 → linear float
- 算:在 linear 域做 invert / pack
- 写:linear float → 8bit uint8(按目标 colorspace 编码)
"""
from __future__ import annotations

import numpy as np

from .pixels import from_normalized, normalized_float
from .slot import ColorSpace

_EPS = 1e-8


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """sRGB → Linear（支持 uint8、uint16 与 float 输入）。"""
    x = normalized_float(x)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Linear → sRGB(返回 float32 in [0,1])。"""
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * (np.maximum(x, _EPS) ** (1.0 / 2.4)) - 0.055)


def to_linear(x_u8: np.ndarray, src: ColorSpace) -> np.ndarray:
    """整数/浮点像素 → linear float32。"""
    f = normalized_float(x_u8)
    if src is ColorSpace.SRGB:
        f = srgb_to_linear(f)
    return f


def from_linear(f: np.ndarray, dst: ColorSpace, dtype=np.uint8) -> np.ndarray:
    """linear float32 → 指定位深；默认保持旧 API 的 uint8 输出。"""
    if dst is ColorSpace.SRGB:
        f = linear_to_srgb(f)
    return from_normalized(f, dtype)

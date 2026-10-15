"""PS 风格混合模式。

函数使用 0..255 浮点标度，以保持旧编辑器公式和结果兼容。
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np


def blend_normal(_base, blend):
    return blend


def blend_multiply(base, blend):
    return base.astype(np.float32) * blend.astype(np.float32) / 255.0


def blend_screen(base, blend):
    return 255.0 - (
        (255.0 - base.astype(np.float32))
        * (255.0 - blend.astype(np.float32))
        / 255.0
    )


def blend_overlay(base, blend):
    base_f = base.astype(np.float32)
    blend_f = blend.astype(np.float32)
    return np.where(
        base_f <= 128.0,
        2.0 * base_f * blend_f / 255.0,
        255.0 - 2.0 * (255.0 - base_f) * (255.0 - blend_f) / 255.0,
    )


def blend_darken(base, blend):
    return np.minimum(base, blend).astype(np.float32)


def blend_lighten(base, blend):
    return np.maximum(base, blend).astype(np.float32)


def blend_color_dodge(base, blend):
    base_f = base.astype(np.float32)
    blend_f = blend.astype(np.float32)
    return np.where(
        blend >= 255,
        255.0,
        np.minimum(255.0, base_f * 255.0 / np.maximum(1.0, 255.0 - blend_f)),
    )


def blend_color_burn(base, blend):
    base_f = base.astype(np.float32)
    blend_f = blend.astype(np.float32)
    return np.where(
        blend <= 0,
        0.0,
        255.0 - np.minimum(
            255.0,
            (255.0 - base_f) * 255.0 / np.maximum(1.0, blend_f),
        ),
    )


def blend_hard_light(base, blend):
    base_f = base.astype(np.float32)
    blend_f = blend.astype(np.float32)
    return np.where(
        blend_f <= 128.0,
        2.0 * base_f * blend_f / 255.0,
        255.0 - 2.0 * (255.0 - base_f) * (255.0 - blend_f) / 255.0,
    )


def blend_soft_light(base, blend):
    blend_f = blend.astype(np.float32) / 255.0
    base_f = base.astype(np.float32) / 255.0
    out = np.where(
        blend_f <= 0.5,
        base_f + (2.0 * blend_f - 1.0) * (base_f - base_f * base_f),
        base_f + (2.0 * blend_f - 1.0)
        * (np.sqrt(np.maximum(0.0, base_f)) - base_f),
    )
    return out * 255.0


def blend_difference(base, blend):
    return np.abs(base.astype(np.float32) - blend.astype(np.float32))


def blend_exclusion(base, blend):
    base_f = base.astype(np.float32)
    blend_f = blend.astype(np.float32)
    return base_f + blend_f - 2.0 * base_f * blend_f / 255.0


def blend_add(base, blend):
    return base.astype(np.float32) + blend.astype(np.float32)


def blend_subtract(base, blend):
    return base.astype(np.float32) - blend.astype(np.float32)


def blend_divide(base, blend):
    base_f = base.astype(np.float32)
    blend_f = blend.astype(np.float32)
    return np.where(
        blend <= 0,
        255.0,
        np.minimum(255.0, base_f * 255.0 / np.maximum(1.0, blend_f)),
    )


BLEND_MODES: list[tuple[str, str, Callable]] = [
    ("normal", "正常 (Normal)", blend_normal),
    ("multiply", "正片叠底 (Multiply)", blend_multiply),
    ("screen", "滤色 (Screen)", blend_screen),
    ("overlay", "叠加 (Overlay)", blend_overlay),
    ("darken", "变暗 (Darken)", blend_darken),
    ("lighten", "变亮 (Lighten)", blend_lighten),
    ("color_dodge", "颜色减淡 (Color Dodge)", blend_color_dodge),
    ("color_burn", "颜色加深 (Color Burn)", blend_color_burn),
    ("hard_light", "强光 (Hard Light)", blend_hard_light),
    ("soft_light", "柔光 (Soft Light)", blend_soft_light),
    ("difference", "差值 (Difference)", blend_difference),
    ("exclusion", "排除 (Exclusion)", blend_exclusion),
    ("add", "线性加深 (Add / Linear Dodge)", blend_add),
    ("subtract", "线性减淡 (Subtract / Linear Burn)", blend_subtract),
    ("divide", "划分 (Divide)", blend_divide),
]
BLEND_BY_ID: dict[str, Callable] = {
    mode_id: function for mode_id, _label, function in BLEND_MODES
}


__all__ = ["BLEND_MODES", "BLEND_BY_ID", "blend_normal"]

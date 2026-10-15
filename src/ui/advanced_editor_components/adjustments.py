"""复杂编辑器的纯像素调整管线。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.core.pixels import from_normalized, normalized_float

from .blend_modes import BLEND_BY_ID, blend_normal


@dataclass(frozen=True)
class AdjustmentSettings:
    """一次预览/应用所需的全部可序列化调整参数。"""

    brightness: int = 0
    contrast: float = 1.0
    exposure: float = 0.0
    shadows: int = 0
    highlights: int = 0
    gamma: float = 1.0
    saturation: float = 1.0
    threshold: int = -1
    posterize: int = 256
    invert: bool = False
    blend_id: str = "normal"

    def is_default(self) -> bool:
        return (
            self.brightness == 0
            and self.contrast == 1.0
            and self.exposure == 0.0
            and self.shadows == 0
            and self.highlights == 0
            and self.gamma == 1.0
            and self.saturation == 1.0
            and self.threshold < 0
            and self.posterize >= 256
            and not self.invert
        )


def apply_saturation_rgb(rgb_float: np.ndarray, factor: float) -> np.ndarray:
    """对归一化 RGB 调饱和度；0 为灰度，1 为不变。"""
    if factor == 1.0:
        return rgb_float
    red = rgb_float[..., 0]
    green = rgb_float[..., 1]
    blue = rgb_float[..., 2]
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return luminance[..., None] + (rgb_float - luminance[..., None]) * factor


def apply_curve_lut(values: np.ndarray, curve_lut: np.ndarray) -> np.ndarray:
    """把 0..255 LUT 应用到归一化浮点数组。"""
    lut = np.asarray(curve_lut, dtype=np.float32) / 255.0
    return np.interp(
        np.clip(values, 0.0, 1.0),
        np.linspace(0.0, 1.0, len(lut), dtype=np.float32),
        lut,
    ).astype(np.float32)


def compute_adjustments(
    base: np.ndarray,
    settings: AdjustmentSettings,
    *,
    curve_lut: Optional[np.ndarray] = None,
    second_data: Optional[np.ndarray] = None,
) -> np.ndarray:
    """计算调整结果，并恢复 ``base`` 的 dtype。

    无调整时直接复制母版，因此浮点 EXR 的负值和大于 1 的 HDR 值不会
    因为打开编辑器而被裁切。执行色调/混合调整后按数据贴图范围裁到 0..1。
    """
    if settings.is_default() and curve_lut is None and second_data is None:
        return base.copy()

    result = normalized_float(base)
    if settings.exposure != 0.0:
        result = result * (2.0 ** settings.exposure)
    if settings.brightness != 0:
        result = result + settings.brightness / 255.0
    if settings.contrast != 1.0:
        result = (result - 0.5) * settings.contrast + 0.5

    if settings.shadows != 0 or settings.highlights != 0:
        if result.ndim == 2:
            luminance = np.clip(result, 0, 1)
        else:
            luminance = np.clip(
                0.299 * result[..., 0]
                + 0.587 * result[..., 1]
                + 0.114 * result[..., 2],
                0,
                1,
            )
        shadow_mask = 1.0 - luminance
        highlight_mask = luminance
        shadow_amount = (settings.shadows / 100.0) * (100.0 / 255.0)
        highlight_amount = (settings.highlights / 100.0) * (100.0 / 255.0)
        if result.ndim == 2:
            result = result + shadow_amount * shadow_mask
            result = result - highlight_amount * highlight_mask
        else:
            result = result + shadow_amount * shadow_mask[..., None]
            result = result - highlight_amount * highlight_mask[..., None]

    if settings.gamma != 1.0:
        result = np.power(np.clip(result, 0, 1), settings.gamma)
    if result.ndim == 3 and abs(settings.saturation - 1.0) > 1e-6:
        result = apply_saturation_rgb(result, settings.saturation)
    if settings.threshold >= 0:
        result = np.where(result > settings.threshold / 255.0, 1.0, 0.0)
    if 2 <= settings.posterize < 256:
        levels = settings.posterize
        result = np.round(np.clip(result, 0, 1) * (levels - 1)) / (levels - 1)
    if settings.invert:
        result = 1.0 - result
    if curve_lut is not None:
        result = apply_curve_lut(result, curve_lut)

    if second_data is not None:
        blend_function = BLEND_BY_ID.get(settings.blend_id, blend_normal)
        second = normalized_float(second_data)
        if result.ndim == 3 and second.ndim == 2:
            second = second[..., None]
        result = blend_function(result * 255.0, second * 255.0) / 255.0

    return from_normalized(np.clip(result, 0.0, 1.0), base.dtype)


__all__ = [
    "AdjustmentSettings",
    "apply_curve_lut",
    "apply_saturation_rgb",
    "compute_adjustments",
]

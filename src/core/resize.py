"""
resize — 源图与目标尺寸不一致时的处理。

支持:
- ResizeMode: fit / fill / stretch / none
- ResizeFilter: nearest / bilinear / bicubic / lanczos
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from .output_spec import ResizeFilter, ResizeMode
from .pixels import validate_pixel_array


# ---------------------------------------------------------------------------
# PIL 滤镜映射
# ---------------------------------------------------------------------------
_FILTER_MAP = {
    ResizeFilter.NEAREST: Image.Resampling.NEAREST,
    ResizeFilter.BILINEAR: Image.Resampling.BILINEAR,
    ResizeFilter.BICUBIC: Image.Resampling.BICUBIC,
    ResizeFilter.LANCZOS: Image.Resampling.LANCZOS,
}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def resize_to(arr: np.ndarray, target_h: int, target_w: int,
              mode: ResizeMode = ResizeMode.FIT,
              flt: ResizeFilter = ResizeFilter.LANCZOS) -> np.ndarray:
    """把 H×W 灰度/单通道数组 resize 到 (target_h, target_w)。

    Args:
        arr: 输入(H×W,uint8 / uint16 / float)
        target_h, target_w: 目标尺寸
        mode: 源与目标尺寸不一致时的处理
        flt: resize 滤镜

    Returns:
        resize 后的数组，dtype 与输入一致
    """
    if arr.ndim != 2:
        raise ValueError(f"resize_to expects 2D array, got shape {arr.shape}")
    validate_pixel_array(arr)

    h, w = arr.shape
    if (h, w) == (target_h, target_w):
        return arr.copy()

    pil_filter = _FILTER_MAP[flt]

    if mode is ResizeMode.STRETCH:
        return _resize_pil(arr, (target_h, target_w), pil_filter)

    if mode is ResizeMode.NONE:
        raise ValueError(
            f"源图尺寸 {w}x{h} 与目标 {target_w}x{target_h} 不一致,"
            f"且 resize_mode=NONE。请选 fit/fill/stretch。"
        )

    # fit / fill:等比缩放,fit 覆盖(可能裁),fill 包含(可能留白)
    scale_w = target_w / w
    scale_h = target_h / h
    if mode is ResizeMode.FIT:
        # 覆盖:scale 取较大,缩放后裁中间
        scale = max(scale_w, scale_h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = _resize_pil(arr, (new_h, new_w), pil_filter)
        return _crop_center(resized, target_h, target_w)

    # FILL:包含:scale 取较小,缩放后居中留白
    scale = min(scale_w, scale_h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = _resize_pil(arr, (new_h, new_w), pil_filter)
    return _pad_center(resized, target_h, target_w)


# ---------------------------------------------------------------------------
# 内部
# ---------------------------------------------------------------------------
def _resize_pil(arr: np.ndarray, size: tuple[int, int], pil_filter) -> np.ndarray:
    original_dtype = arr.dtype
    img = Image.fromarray(arr.astype(np.float32), mode="F")
    out = img.resize((size[1], size[0]), resample=pil_filter)
    values = np.asarray(out, dtype=np.float32)
    if original_dtype.kind == "u":
        limit = np.iinfo(original_dtype).max
        return np.rint(np.clip(values, 0, limit)).astype(original_dtype)
    return values.astype(original_dtype)


def _crop_center(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    h, w = arr.shape
    if (h, w) == (target_h, target_w):
        return arr
    top = max(0, (h - target_h) // 2)
    left = max(0, (w - target_w) // 2)
    return arr[top:top + target_h, left:left + target_w]


def _pad_center(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    h, w = arr.shape
    if (h, w) == (target_h, target_w):
        return arr
    out = np.zeros((target_h, target_w), dtype=arr.dtype)
    top = max(0, (target_h - h) // 2)
    left = max(0, (target_w - w) // 2)
    out[top:top + h, left:left + w] = arr
    return out

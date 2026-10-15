"""第二张图片到编辑画布的尺寸映射。"""
from __future__ import annotations

import numpy as np

from src.core.output_spec import ResizeFilter, ResizeMode
from src.core.resize import resize_to


SECOND_IMAGE_MAPPINGS: tuple[tuple[str, str], ...] = (
    ("stretch", "拉伸铺满"),
    ("contain", "等比适应（留黑边）"),
    ("crop", "等比截取"),
    ("tile", "平铺"),
)


def map_second_to_canvas(
    source: np.ndarray,
    target_h: int,
    target_w: int,
    mode: str = "stretch",
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: int = 0,
    offset_y: int = 0,
) -> np.ndarray:
    """将第二张灰度图映射到主图画布。

    ``crop`` 以等比覆盖为 100% 基准，X/Y 可继续独立缩放并从中心偏移；
    ``tile`` 以源图原始尺寸为 100% 基准，偏移控制平铺起点。
    所有变换都直接从母版生成，避免累计重采样。
    """
    if source.ndim != 2:
        raise ValueError(f"第二张图映射只接受二维灰度数组，收到 {source.shape}")
    if target_h <= 0 or target_w <= 0:
        raise ValueError(f"目标尺寸必须为正数，收到 {target_w}x{target_h}")
    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("X/Y 缩放必须大于 0")

    if mode == "stretch":
        return resize_to(
            source, target_h, target_w,
            ResizeMode.STRETCH, ResizeFilter.LANCZOS,
        )
    if mode == "contain":
        return resize_to(
            source, target_h, target_w,
            ResizeMode.FILL, ResizeFilter.LANCZOS,
        )

    source_h, source_w = source.shape
    if mode == "crop":
        cover_scale = max(target_w / source_w, target_h / source_h)
        mapped_w = max(1, int(round(source_w * cover_scale * scale_x)))
        mapped_h = max(1, int(round(source_h * cover_scale * scale_y)))
    elif mode == "tile":
        mapped_w = max(1, int(round(source_w * scale_x)))
        mapped_h = max(1, int(round(source_h * scale_y)))
    else:
        raise ValueError(f"未知的第二张图映射方式: {mode}")

    mapped = resize_to(
        source, mapped_h, mapped_w,
        ResizeMode.STRETCH, ResizeFilter.LANCZOS,
    )
    if mode == "tile":
        xs = np.mod(np.arange(target_w, dtype=np.int64) - int(offset_x), mapped_w)
        ys = np.mod(np.arange(target_h, dtype=np.int64) - int(offset_y), mapped_h)
        return mapped[np.ix_(ys, xs)].copy()

    left = (target_w - mapped_w) // 2 + int(offset_x)
    top = (target_h - mapped_h) // 2 + int(offset_y)
    dst_left = max(0, left)
    dst_top = max(0, top)
    dst_right = min(target_w, left + mapped_w)
    dst_bottom = min(target_h, top + mapped_h)
    out = np.zeros((target_h, target_w), dtype=source.dtype)
    if dst_right <= dst_left or dst_bottom <= dst_top:
        return out
    src_left = dst_left - left
    src_top = dst_top - top
    copy_w = dst_right - dst_left
    copy_h = dst_bottom - dst_top
    out[dst_top:dst_bottom, dst_left:dst_right] = mapped[
        src_top:src_top + copy_h,
        src_left:src_left + copy_w,
    ]
    return out


# 兼容旧测试和脚本中的私有名字。
_map_second_to_canvas = map_second_to_canvas


__all__ = ["SECOND_IMAGE_MAPPINGS", "map_second_to_canvas"]

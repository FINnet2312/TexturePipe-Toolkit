"""合成:把噪声叠到原图上,生成 composite / mask / normal。"""
from __future__ import annotations

import numpy as np

from .core import gen_noise
from .projections import uv_to_xyz
from src.core.resize import resize_to


def preview_size(height: int, width: int, scale: float) -> tuple[int, int]:
    """按源宽高比计算代理尺寸，短图也至少保留一条 64px 的长边。"""
    longest_source = max(height, width)
    effective_scale = max(float(scale), 64.0 / longest_source)
    target_w = max(1, int(round(width * effective_scale)))
    target_h = max(1, int(round(height * effective_scale)))
    return target_h, target_w


def resize_preview(source: np.ndarray, height: int, width: int) -> np.ndarray:
    """使用公共高精度 resize，同时支持灰度和 HWC。"""
    if source.ndim == 2:
        return resize_to(source, height, width)
    return np.stack(
        [resize_to(source[..., index], height, width)
         for index in range(source.shape[-1])],
        axis=-1,
    )


def compose(src, caustic, mask, slope_mod, p: dict):
    """把噪声场 caustic 按 mask 叠到原图 src 上。

    整数贴图通常落在 [0, 1]；浮点/HDR 允许保留到 ``highlight_max``。
    预览组件会自行显示裁切，写 EXR/TIFF 时则保留这部分高光数据。
    """
    base_mod = mask * p["intensity"] * (caustic * 1.4 - 0.3) * slope_mod
    mult = 1.0 + base_mod
    mult = mult[:, :, None]

    tint = np.zeros_like(src)
    tint[..., 0] = -p["tint_blue"]
    tint[..., 2] = +p["tint_blue"]
    tint = tint * (caustic * mask)[:, :, None]

    out = src * mult + tint
    K = p["highlight_knee"]
    M = p["highlight_max"]
    if M > K:
        over = out > K
        # 限幅避免 exp 溢出
        excess = np.clip(out - K, 0, 50.0)
        out = np.where(
            over,
            K + (M - K) * (1.0 - np.exp(-excess / (M - K))),
            out,
        )
    return np.clip(out, 0, max(1.0, float(M)))


def soft_knee(x, K, M):
    """柔压高光(K 是 knee 起点, M 是上限)。"""
    if M <= K:
        return np.clip(x, 0, 1)
    over = x > K
    return np.where(
        over,
        K + (M - K) * (1.0 - np.exp(-(x - K) / (M - K))),
        x,
    )


def render(src, projection: str, noise_type: str, p: dict, scale: float = 1.0,
           noise_field=None):
    """主渲染:返回 (composite, mask_gray, normal, caustic, mask, sH, sW)。

    noise_field: 可选,外部传入的 HxW 噪声场(节点图自定义噪声);
    为 None 时走内部 gen_noise。
    """
    H, W = src.shape[:2]
    if scale < 1.0:
        sH, sW = preview_size(H, W, scale)
        src_small = resize_preview(src, sH, sW)
    else:
        sH, sW = H, W
        src_small = src

    u = np.linspace(0, 1, sW, endpoint=False)
    v = np.linspace(0, 1, sH, endpoint=False)
    U, V = np.meshgrid(u, v)
    sx, sy, sz = uv_to_xyz(projection, U, V)

    caustic = noise_field if noise_field is not None \
        else gen_noise(noise_type, sx, sy, sz, p)

    # 垂直 mask
    t = np.clip(
        (V - p["mask_top"]) / max(p["mask_bottom"] - p["mask_top"], 1e-6),
        0, 1,
    )
    mask = (1.0 - t) ** p["mask_softness"]

    grad_y = np.gradient(caustic, axis=0)
    grad_x = np.gradient(caustic, axis=1)
    slope_mod = 1.0 - p["normal_strength"] * (np.abs(grad_x) + np.abs(grad_y)) * 6.0
    slope_mod = np.clip(slope_mod, 0.6, 1.0)

    composite = compose(src_small, caustic, mask, slope_mod, p)
    mask_gray = np.clip(caustic * mask, 0, 1)

    # 法线贴图
    nx = np.clip(-grad_x * 6.0, -50.0, 50.0)
    ny = np.clip(-grad_y * 6.0, -50.0, 50.0)
    nz = np.ones_like(nx)
    L = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-8
    nx /= L; ny /= L; nz /= L
    normal = np.stack(
        [nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5],
        axis=-1,
    )

    return (composite, mask_gray, np.clip(normal, 0, 1),
            caustic, mask, sH, sW)

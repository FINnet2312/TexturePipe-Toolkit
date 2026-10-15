"""投影工具:UV 坐标 → 3D 球面坐标。

支持:
    - equirectangular: 标准全景(2:1 宽高比)
    - cubemap-cross:   4x3 十字布局
    - cylindrical:     圆柱侧壁展开
"""
from __future__ import annotations

import numpy as np


PROJ_EQUI = "equirectangular"
PROJ_CUBE_CROSS = "cubemap-cross (4x3)"
PROJ_CYL = "cylindrical"

ALL_PROJECTIONS = [PROJ_EQUI, PROJ_CUBE_CROSS, PROJ_CYL]


def uv_to_xyz(projection: str, u, v):
    """u, v in [0, 1]; 返回 (x, y, z) 球面坐标, 同 shape。"""
    if projection == PROJ_EQUI:
        theta = (u - 0.5) * 2.0 * np.pi
        phi = (v - 0.5) * np.pi
        x = np.cos(phi) * np.sin(theta)
        y = np.sin(phi)
        z = np.cos(phi) * np.cos(theta)
        return x, y, z
    elif projection == PROJ_CUBE_CROSS:
        # 4x3 cross layout:
        #   +Y
        # +X -Z +Z -X
        #   -Y
        # 每个 cell 内 a/b 均为 [-1, 1]，b 随图片坐标向下增大。
        col = np.floor(np.asarray(u) * 4.0).astype(np.int64)
        row = np.floor(np.asarray(v) * 3.0).astype(np.int64)
        col = np.clip(col, 0, 3)
        row = np.clip(row, 0, 2)
        a = (np.asarray(u) * 4.0 - col) * 2.0 - 1.0
        b = (np.asarray(v) * 3.0 - row) * 2.0 - 1.0

        # 非十字区域使用 +Z 单位向量。实际图像这些区域通常为空，但保持
        # 有限单位坐标可避免噪声求值出现 NaN。
        x = np.zeros_like(a, dtype=np.float64)
        y = np.zeros_like(a, dtype=np.float64)
        z = np.ones_like(a, dtype=np.float64)

        def assign(mask, xv, yv, zv):
            x[mask] = np.broadcast_to(xv, x.shape)[mask]
            y[mask] = np.broadcast_to(yv, y.shape)[mask]
            z[mask] = np.broadcast_to(zv, z.shape)[mask]

        assign((row == 0) & (col == 1), a, 1.0, b)       # +Y
        assign((row == 1) & (col == 0), 1.0, -b, -a)     # +X
        assign((row == 1) & (col == 1), -a, -b, -1.0)    # -Z
        assign((row == 1) & (col == 2), a, -b, 1.0)      # +Z
        assign((row == 1) & (col == 3), -1.0, -b, a)     # -X
        assign((row == 2) & (col == 1), a, -1.0, -b)     # -Y

        length = np.sqrt(x * x + y * y + z * z)
        return x / length, y / length, z / length
    elif projection == PROJ_CYL:
        theta = (u - 0.5) * 2.0 * np.pi
        x = np.sin(theta)
        y = v - 0.5
        z = np.cos(theta)
        return x, y, z
    else:
        return uv_to_xyz(PROJ_EQUI, u, v)


def detect_projection(width: int, height: int) -> str:
    """根据宽高比猜测投影方式。"""
    ratio = width / height
    if 1.9 < ratio < 2.1:
        return PROJ_EQUI
    if 1.25 < ratio < 1.45:  # 4:3 cross
        return PROJ_CUBE_CROSS
    return PROJ_CYL

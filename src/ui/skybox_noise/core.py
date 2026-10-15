"""噪声核心:3D Perlin / FBM / 各种风格化噪声。

优先用 Numba JIT(parallel=True 走 OpenMP 多核),缺了回退到 numpy。
所有输出在 [-1, 1] 范围(Perlin)或 [0, 1] 范围(经 1 - |x| 锐化后的)。
"""
from __future__ import annotations

import numpy as np

# Numba (optional, fallback to numpy if missing)
try:
    from numba import njit, prange
    NUMBA_OK = True
except ImportError:  # pragma: no cover - exercised only without numba
    NUMBA_OK = False


# ============================================================
# 1. Perlin 3D 基础
# ============================================================

_PERM = np.random.RandomState(1337).randint(0, 256, 512, dtype=np.int64)
_P = np.empty(512, dtype=np.int64)
_P[:256] = _PERM[:256]
_P[256:] = _PERM[:256]
_CURRENT_SEED = 1337

_GRAD3 = np.array([
    [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
    [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
    [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
], dtype=np.float64)


def _reset_perm(seed: int) -> None:
    global _PERM, _P, _CURRENT_SEED
    _PERM = np.random.RandomState(seed).randint(0, 256, 512, dtype=np.int64)
    _P[:256] = _PERM[:256]
    _P[256:] = _PERM[:256]
    _CURRENT_SEED = seed


def _fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def _grad_dot(h, x, y, z):
    g = _GRAD3[h & 11]
    return g[..., 0] * x + g[..., 1] * y + g[..., 2] * z


# ---------- Numba 加速核心 ----------
if NUMBA_OK:
    @njit(cache=True, parallel=True, fastmath=True, boundscheck=False)
    def _perlin3d_nb(x, y, z, P, grad):
        n = x.size
        H, W = x.shape
        # 用 zeros 不用 empty,见 _fbm3d_nb 注释
        out = np.zeros((H, W), dtype=np.float64)
        for idx in prange(n):
            i = idx // W
            j = idx % W
            xv = x[i, j]; yv = y[i, j]; zv = z[i, j]
            xi0 = int(np.floor(xv)); yi0 = int(np.floor(yv)); zi0 = int(np.floor(zv))
            xi = xi0 & 255; yi = yi0 & 255; zi = zi0 & 255
            xf = xv - xi0; yf = yv - yi0; zf = zv - zi0
            u = xf*xf*xf*(xf*(xf*6.0-15.0)+10.0)
            v_ = yf*yf*yf*(yf*(yf*6.0-15.0)+10.0)
            w_ = zf*zf*zf*(zf*(zf*6.0-15.0)+10.0)
            Pxi = P[xi]; Pxi1 = P[(xi0+1) & 255]
            A = Pxi + yi; B = Pxi1 + yi
            AA = P[A & 255] + zi
            AB = P[(A+1) & 255] + zi
            BA = P[B & 255] + zi
            BB = P[(B+1) & 255] + zi
            h = P[AA & 255]
            n000 = grad[h&11, 0]*xf + grad[h&11, 1]*yf + grad[h&11, 2]*zf
            h = P[BA & 255]
            n100 = grad[h&11, 0]*(xf-1) + grad[h&11, 1]*yf + grad[h&11, 2]*zf
            h = P[AB & 255]
            n010 = grad[h&11, 0]*xf + grad[h&11, 1]*(yf-1) + grad[h&11, 2]*zf
            h = P[BB & 255]
            n110 = grad[h&11, 0]*(xf-1) + grad[h&11, 1]*(yf-1) + grad[h&11, 2]*zf
            h = P[(AA+1) & 255]
            n001 = grad[h&11, 0]*xf + grad[h&11, 1]*yf + grad[h&11, 2]*(zf-1)
            h = P[(BA+1) & 255]
            n101 = grad[h&11, 0]*(xf-1) + grad[h&11, 1]*yf + grad[h&11, 2]*(zf-1)
            h = P[(AB+1) & 255]
            n011 = grad[h&11, 0]*xf + grad[h&11, 1]*(yf-1) + grad[h&11, 2]*(zf-1)
            h = P[(BB+1) & 255]
            n111 = grad[h&11, 0]*(xf-1) + grad[h&11, 1]*(yf-1) + grad[h&11, 2]*(zf-1)
            x1 = n000 + u*(n100-n000)
            x2 = n010 + u*(n110-n010)
            x3 = n001 + u*(n101-n001)
            x4 = n011 + u*(n111-n011)
            y1 = x1 + v_*(x2-x1)
            y2 = x3 + v_*(x4-x3)
            out[i, j] = y1 + w_*(y2-y1)
        return out

    @njit(cache=True, parallel=True, fastmath=True, boundscheck=False)
    def _fbm3d_nb(x, y, z, P, grad, octaves, persistence, lacunarity):
        H, W = x.shape
        # 用 zeros 而不是 empty:numba parallel 下 empty 的初值是未定义垃圾,
        # 第一轮 octave 的累加会带进未初始化位,导致输出溢出。
        out = np.zeros((H, W), dtype=np.float64)
        norm = 0.0
        amp = 1.0
        for k in range(octaves):
            norm += amp
            amp *= persistence
        amp = 1.0; freq = 1.0
        for k in range(octaves):
            out += amp * _perlin3d_nb(x*freq, y*freq, z*freq, P, grad)
            amp *= persistence
            freq *= lacunarity
        return out / norm


def perlin3d(x, y, z, seed=1337, context=None):
    """线程安全的 3D Perlin；显式 seed，不依赖模块最近一次调用。"""
    engine = context or NoiseContext(int(seed))
    return engine.perlin3d(x, y, z, seed=int(seed))


def fbm3d(x, y, z, octaves=4, persistence=0.5, lacunarity=2.05,
          seed=0, context=None):
    """线程安全的 FBM（分形布朗运动）。"""
    engine = context or NoiseContext(int(seed))
    return engine.fbm3d(
        x, y, z, octaves, persistence, lacunarity, seed=int(seed),
    )


def _perlin3d_np(x, y, z, P, grad):
    """纯 numpy fallback(慢但能跑)"""
    xi0 = np.floor(x).astype(np.int64)
    yi0 = np.floor(y).astype(np.int64)
    zi0 = np.floor(z).astype(np.int64)
    xi = xi0 & 255; yi = yi0 & 255; zi = zi0 & 255
    xf = x - xi0.astype(np.float64)
    yf = y - yi0.astype(np.float64)
    zf = z - zi0.astype(np.float64)
    u = _fade(xf); v = _fade(yf); w = _fade(zf)
    Pxi = P[xi]; Pxi1 = P[(xi0 + 1) & 255]
    A = Pxi + yi; B = Pxi1 + yi
    AA = P[A & 255] + zi; AB = P[(A + 1) & 255] + zi
    BA = P[B & 255] + zi; BB = P[(B + 1) & 255] + zi

    def gd(h, dx, dy, dz):
        g = grad[h & 11]
        return g[..., 0] * dx + g[..., 1] * dy + g[..., 2] * dz

    n000 = gd(P[AA & 255], xf, yf, zf)
    n100 = gd(P[BA & 255], xf - 1, yf, zf)
    n010 = gd(P[AB & 255], xf, yf - 1, zf)
    n110 = gd(P[BB & 255], xf - 1, yf - 1, zf)
    n001 = gd(P[(AA + 1) & 255], xf, yf, zf - 1)
    n101 = gd(P[(BA + 1) & 255], xf - 1, yf, zf - 1)
    n011 = gd(P[(AB + 1) & 255], xf, yf - 1, zf - 1)
    n111 = gd(P[(BB + 1) & 255], xf - 1, yf - 1, zf - 1)
    x1 = n000 + u * (n100 - n000); x2 = n010 + u * (n110 - n010)
    x3 = n001 + u * (n101 - n001); x4 = n011 + u * (n111 - n011)
    y1 = x1 + v * (x2 - x1); y2 = x3 + v * (x4 - x3)
    return y1 + w * (y2 - y1)


class NoiseContext:
    """一次预览/渲染私有的 permutation 状态。

    数组原地更新，Numba 编译函数仍可跨上下文复用，但不同线程不会共享或
    改写 permutation。
    """

    def __init__(self, seed: int = 1337):
        self.P = np.empty(512, dtype=np.int64)
        self.seed: int | None = None
        self.reseed(seed)

    def reseed(self, seed: int) -> None:
        seed = int(seed)
        if seed == self.seed:
            return
        perm = np.random.RandomState(seed).randint(
            0, 256, 512, dtype=np.int64,
        )
        self.P[:256] = perm[:256]
        self.P[256:] = perm[:256]
        self.seed = seed

    def perlin3d(self, x, y, z, seed: int | None = None):
        if seed is not None:
            self.reseed(seed)
        if NUMBA_OK:
            return _perlin3d_nb(
                np.ascontiguousarray(x, dtype=np.float64),
                np.ascontiguousarray(y, dtype=np.float64),
                np.ascontiguousarray(z, dtype=np.float64),
                self.P, _GRAD3,
            )
        return _perlin3d_np(x, y, z, self.P, _GRAD3)

    def fbm3d(self, x, y, z, octaves=4, persistence=0.5,
              lacunarity=2.05, seed: int | None = None):
        if seed is not None:
            self.reseed(seed)
        if NUMBA_OK:
            return _fbm3d_nb(
                np.ascontiguousarray(x, dtype=np.float64),
                np.ascontiguousarray(y, dtype=np.float64),
                np.ascontiguousarray(z, dtype=np.float64),
                self.P, _GRAD3, int(octaves), float(persistence),
                float(lacunarity),
            )
        amp, freq, total, norm = 1.0, 1.0, 0.0, 0.0
        for _ in range(int(octaves)):
            total += amp * self.perlin3d(
                x * freq, y * freq, z * freq,
            )
            norm += amp
            amp *= persistence
            freq *= lacunarity
        return total / norm

    def gen_noise(self, noise_type: str, x, y, z, p: dict):
        scale = p["noise_scale"]
        octaves = int(p["octaves"])
        persistence = p["persistence"]
        lacunarity = p["lacunarity"]
        seed = int(p["seed"])
        self.reseed(seed)

        if noise_type == NOISE_FBM:
            return self.fbm3d(
                x * scale, y * scale, z * scale,
                octaves, persistence, lacunarity,
            )

        if noise_type == NOISE_CAUSTICS:
            warp = p["warp_amount"]
            wx = self.fbm3d(
                x * 1.2, y * 1.2, z * 1.2, 3, 0.5, 2.0,
            ) * warp
            wy = self.fbm3d(
                x * 1.2 + 11.3, y * 1.2 + 11.3, z * 1.2 + 11.3,
                3, 0.5, 2.0,
            ) * warp
            px = x + wx; py = y + wy; pz = z + wx * 0.5
            n1 = self.fbm3d(
                px * scale, py * scale, pz * scale,
                octaves, persistence, lacunarity,
            )
            n2 = self.fbm3d(
                px * scale * 2.13 + 17.3,
                py * scale * 2.13 + 17.3,
                pz * scale * 2.13 + 17.3,
                max(1, octaves - 1), persistence, lacunarity,
            )
            soft = np.clip(1.0 - np.abs(n1 + 0.3 * n2), 0, 1) \
                ** p["caustic_power"]
            lwx = self.fbm3d(
                px * 0.9, py * 0.9, pz * 0.9, 3, 0.5, 2.0,
            ) * 0.7
            lwy = self.fbm3d(
                px * 0.9 + 7.7, py * 0.9 + 7.7,
                pz * 0.9 + 7.7, 3, 0.5, 2.0,
            ) * 0.7
            ax = (px + lwx) * p["lattice_freq"]
            ay = (py + lwy) * p["lattice_freq"]
            az = (pz + (lwx - lwy) * 0.5) * p["lattice_freq"]
            lattice = (
                np.sin(ax) * np.sin(ay * 0.93)
                + np.sin(ay) * np.sin(az * 1.07)
                + np.sin(az) * np.sin(ax * 0.97)
            ) / 3.0
            fine = np.clip(1.0 - np.abs(lattice), 0, 1) ** 1.05
            return (
                (1.0 - p["lattice_weight"]) * soft
                + p["lattice_weight"] * fine
            )

        if noise_type == NOISE_VORONOI:
            n1 = self.fbm3d(
                x * scale, y * scale, z * scale,
                octaves, persistence, lacunarity,
            )
            n2 = self.fbm3d(
                x * scale * 1.7 + 5.5,
                y * scale * 1.7 + 5.5,
                z * scale * 1.7 + 5.5,
                max(2, octaves - 1), persistence, lacunarity,
            )
            d = np.sqrt(n1 * n1 + n2 * n2)
            return 1.0 - np.clip(d * 0.8, 0, 1)

        return np.zeros_like(x)


# ============================================================
# 2. 风格化噪声
# ============================================================

NOISE_FBM = "FBM (基础)"
NOISE_CAUSTICS = "Caustics (焦散)"
NOISE_VORONOI = "Voronoi (细胞)"

ALL_NOISE = [NOISE_FBM, NOISE_CAUSTICS, NOISE_VORONOI]


def gen_noise(noise_type: str, x, y, z, p: dict, context=None):
    """按噪声类型生成风格化噪声场，不修改模块全局状态。"""
    engine = context or NoiseContext(int(p["seed"]))
    return engine.gen_noise(noise_type, x, y, z, p)

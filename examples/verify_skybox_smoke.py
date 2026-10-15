"""Skybox 插件 smoke test — 离线跑,不进 GUI 事件循环。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# CI 等环境的控制台可能是 cp1252 等非 UTF-8 编码,直接打印中文会
# UnicodeEncodeError。统一把标准输出切到 UTF-8(失败字符兜底替换,不中断)。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

# 1) Plugin 接口
from src.core.plugin import Plugin
from src.core.plugin_manager import PluginManager
print('Plugin/PluginManager OK')

# 2) Discover
from src.ui.plugins import discover
pm = discover()
print(f'发现 {len(pm.all())} 个插件:')
for p in pm.all():
    ok, miss = p.is_available()
    print(f'  {p.id}: {p.name} (depends={p.requires}, available={ok}{f", missing={miss}" if not ok else ""})')
assert any(p.id == "skybox_noise" for p in pm.all()), "未发现 Skybox 插件"

# 3) 加载 skybox 子包
from src.ui.skybox_noise.plugin import PLUGIN
print(f'skybox plugin: {PLUGIN.id} / {PLUGIN.name}')
available, missing = PLUGIN.is_available()
assert available, f"Skybox 插件依赖不可用: {missing}"

# 4) noise 生成
from src.ui.skybox_noise.core import fbm3d, NUMBA_OK
import numpy as np
xyz = np.random.RandomState(0).rand(64, 64, 3)
xyz = xyz / np.linalg.norm(xyz, axis=-1, keepdims=True)
x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
out = fbm3d(x, y, z, octaves=3, persistence=0.5, lacunarity=2.0, seed=42)
assert out.shape == (64, 64) and np.isfinite(out).all()
print(f'fbm3d 64x64 OK, numba={NUMBA_OK}, mean={out.mean():.4f}, range=[{out.min():.3f}, {out.max():.3f}]')

# 5) test render
from src.ui.skybox_noise.compose import render
from src.ui.skybox_noise.projections import PROJ_EQUI, PROJ_CYL, PROJ_CUBE_CROSS
src = np.full((64, 128, 3), 0.5, dtype=np.float32)
p = {
    'noise_scale': 3.0, 'octaves': 3, 'persistence': 0.5, 'lacunarity': 2.0,
    'seed': 0, 'intensity': 0.5, 'mask_top': 0.2, 'mask_bottom': 0.6,
    'mask_softness': 1.0, 'caustic_power': 1.0, 'warp_amount': 0.5,
    'lattice_freq': 8.0, 'lattice_weight': 0.5, 'normal_strength': 0.1,
    'tint_blue': 0.05, 'highlight_knee': 0.85, 'highlight_max': 1.0,
}
fields = {}
for proj in [PROJ_EQUI, PROJ_CUBE_CROSS, PROJ_CYL]:
    c, mg, nrm, cau, msk, h, w = render(src, proj, 'FBM (基础)', p, scale=0.4)
    assert c.shape == (h, w, 3)
    assert mg.shape == cau.shape == msk.shape == (h, w)
    assert nrm.shape == (h, w, 3)
    assert all(np.isfinite(value).all() for value in (c, mg, nrm, cau, msk))
    fields[proj] = cau
    print(f'  render({proj}): composite {c.shape}, mask {mg.shape}, normal {nrm.shape}')

assert not np.array_equal(
    fields[PROJ_EQUI], fields[PROJ_CUBE_CROSS],
), "Cubemap 投影仍与 equirectangular 完全相同"

print('ALL SMOKE OK')

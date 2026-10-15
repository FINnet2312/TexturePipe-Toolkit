"""生成 4 张测试灰度图(roughness / metallic / ao / height),用于验证 core/CLI。"""
from pathlib import Path
import numpy as np
from PIL import Image

OUT = Path(__file__).parent / "test_input"
OUT.mkdir(exist_ok=True)

H, W = 256, 256
x = np.linspace(0, 255, W, dtype=np.float32)
y = np.linspace(0, 255, H, dtype=np.float32)
xv, yv = np.meshgrid(x, y)  # 都 (H, W)

# 1. roughness: 横向渐变(左黑右白)
rough = xv.astype(np.uint8)
Image.fromarray(rough, mode="L").save(OUT / "roughness.png")

# 2. metallic: 上半白,下半黑(简单分块)
met = np.where(yv < 128, 255, 0).astype(np.uint8)
Image.fromarray(met, mode="L").save(OUT / "metallic.png")

# 3. ao: 中心亮,边缘暗(径向)
cx, cy = W / 2, H / 2
d = np.sqrt((xv - cx) ** 2 + (yv - cy) ** 2)
ao = np.clip(255 - d / d.max() * 255, 0, 255).astype(np.uint8)
Image.fromarray(ao, mode="L").save(OUT / "ao.png")

# 4. height: 横向带状(中段高)
height = np.clip(255 - np.abs(yv - 128) * 4, 0, 255).astype(np.uint8)
Image.fromarray(height, mode="L").save(OUT / "height.png")

print(f"生成 4 张测试贴图在 {OUT}")
for f in sorted(OUT.iterdir()):
    arr = np.asarray(Image.open(f))
    print(f"  {f.name}: shape={arr.shape}, mean={arr.mean():.1f}")

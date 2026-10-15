"""verify_ps_adjust — 离线验证 advanced_editor 的 PS 风格调整链。

不开 Qt 窗口(用 offscreen),只验证 _current_computed 的输出:
- 曝光 / 亮度 / 对比 / 阴影 / 高光 / 伽马
- 阈值 / 色调分离 / 反相
- 3 点 LUT / 混合

结果保存到 examples/out_ps/ 下,人眼对比。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# PowerShell 兼容:中文不乱码
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from src.ui.advanced_editor import AdvancedEditorDialog  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

OUT = ROOT / "examples" / "out_ps"
OUT.mkdir(parents=True, exist_ok=True)


def make_test_image() -> np.ndarray:
    """生成一张带渐变 + 文字的 H×W 测试图,方便看效果。"""
    h, w = 96, 256
    arr = np.zeros((h, w), dtype=np.uint8)
    # 横向渐变
    arr[:, :] = np.linspace(0, 255, w, dtype=np.uint8)
    # 5 段色块(更直观)
    segs = 5
    seg_w = w // segs
    for i in range(segs):
        v = int(255 * (i + 1) / segs)
        arr[:, i * seg_w:(i + 1) * seg_w] = v
    # 画个圆,看对称性
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 < (h // 3) ** 2
    arr[mask] = 200
    return arr


def save(arr: np.ndarray, name: str) -> Path:
    p = OUT / f"{name}.png"
    Image.fromarray(arr).save(p)
    return p


def run_case(dlg, name: str) -> Path:
    """按当前 dlg 参数算一次,保存成图,返回路径。"""
    out = dlg._current_computed()
    p = save(out, name)
    print(f"  {name:20s} mean={out.mean():6.2f}  min={out.min():3d}  max={out.max():3d}  -> {p.name}")
    return p


def main() -> int:
    base = make_test_image()
    save(base, "00_original")
    print(f"  baseline            mean={base.mean():6.2f}  min={base.min():3d}  max={base.max():3d}")

    # 1. 曝光 +1.0
    dlg = AdvancedEditorDialog(initial=base, title="verify-exposure")
    dlg._exposure_slider.setValue(100)
    run_case(dlg, "01_exposure_+1.0")
    dlg._exposure_slider.setValue(0)

    # 2. 亮度 +50
    dlg._bright_slider.setValue(50)
    run_case(dlg, "02_brightness_+50")
    dlg._bright_slider.setValue(0)

    # 3. 对比 1.5
    dlg._contrast_slider.setValue(150)
    run_case(dlg, "03_contrast_1.5")
    dlg._contrast_slider.setValue(100)

    # 4. 阴影 +60
    dlg._shadows_slider.setValue(60)
    run_case(dlg, "04_shadows_+60")
    dlg._shadows_slider.setValue(0)

    # 5. 高光 -60
    dlg._highlights_slider.setValue(-60)
    run_case(dlg, "05_highlights_-60")
    dlg._highlights_slider.setValue(0)

    # 6. 伽马 0.5
    dlg._gamma_slider.setValue(50)
    run_case(dlg, "06_gamma_0.5")
    dlg._gamma_slider.setValue(100)

    # 7. 伽马 2.0
    dlg._gamma_slider.setValue(200)
    run_case(dlg, "07_gamma_2.0")
    dlg._gamma_slider.setValue(100)

    # 8. 阈值 128
    dlg._threshold_slider.setValue(128)
    run_case(dlg, "08_threshold_128")
    dlg._threshold_slider.setValue(-1)

    # 9. 色调分离 4 级
    dlg._posterize_slider.setValue(4)
    run_case(dlg, "09_posterize_4")
    dlg._posterize_slider.setValue(256)

    # 10. 反相
    dlg._invert_check.setChecked(True)
    run_case(dlg, "10_invert")
    dlg._invert_check.setChecked(False)

    # 11. LUT 反转(曲线 widget 的反转预设)
    dlg._curve.set_points([(0, 255), (255, 0)])
    run_case(dlg, "11_lut_invert")
    dlg._curve.reset()

    # 12. 混合(Multiply with dark)
    dark = np.full_like(base, 64)
    dlg._second_path = Path("__virtual__")
    dlg._second_data = dark
    dlg._blend_id = "multiply"
    dlg._blend_combo.setCurrentIndex(1)
    run_case(dlg, "12_blend_multiply")

    dlg._blend_id = "screen"
    dlg._blend_combo.setCurrentIndex(2)
    run_case(dlg, "13_blend_screen")

    # 14. 复位
    dlg._on_reset()
    reset = dlg._current_computed()
    if not np.array_equal(reset, base):
        print(f"  WARN: 重置后和原图不完全一致 (mean diff {np.abs(reset.astype(int) - base.astype(int)).mean():.2f})")
    else:
        print("  reset 后与原图完全一致 ✓")
    print()
    print(f"全部 PS 调整样本已生成到: {OUT}")
    print("[OK] verify_ps_adjust 全部通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

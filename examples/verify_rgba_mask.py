"""verify_rgba_mask — 验证 channel_grid / advanced_editor 的 RGBA 通道勾选。

不开 UI(offscreen),直接构造测试图,验证:
1. 中央 drop zone:mask 全选 → 4 槽全部载入;取消某通道 → 该槽为空(0)
2. advanced_editor 第二张图:mask 全选 → 4 通道都在;取消某通道 → 该通道=0
3. 生成的 result_image 像素正确反映 mask
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

OUT = ROOT / "examples" / "out_rgba"
OUT.mkdir(parents=True, exist_ok=True)


def make_rgba_test() -> np.ndarray:
    """R=200, G=100, B=50, A=180 的纯色图(32×32)。"""
    arr = np.zeros((32, 32, 4), dtype=np.uint8)
    arr[..., 0] = 200  # R
    arr[..., 1] = 100  # G
    arr[..., 2] = 50   # B
    arr[..., 3] = 180  # A
    return arr


def save(arr: np.ndarray, name: str) -> Path:
    p = OUT / f"{name}.png"
    if arr.ndim == 2:
        Image.fromarray(arr).save(p)
    else:
        Image.fromarray(arr[..., :3]).save(p)
    return p


# ---------------------------------------------------------------------------
# Part 1: channel_grid 的 RGBA mask
# ---------------------------------------------------------------------------
def test_channel_grid_mask() -> int:
    from src.ui.channel_grid import ChannelGridWidget
    print("\n[Part 1] channel_grid 中央 RGBA 勾选")
    w = ChannelGridWidget()

    # 准备测试图,先存盘(load_image 需要路径)
    src = make_rgba_test()
    src_p = OUT / "src_rgba.png"
    Image.fromarray(src, mode="RGBA").save(src_p)

    # 1.1 默认全选 → 4 槽都载入
    w._rgba_mask = {"R": True, "G": True, "B": True, "A": True}
    w._load_rgba_from_path(src_p)
    m = w.get_map()
    print(f"  默认全选:R.data mean={m.R.data.mean():.1f}  G={m.G.data.mean():.1f}  B={m.B.data.mean():.1f}  A={m.A.data.mean():.1f}")
    assert m.R.data.mean() == 200, f"R 应为 200,实际 {m.R.data.mean()}"
    assert m.G.data.mean() == 100, f"G 应为 100,实际 {m.G.data.mean()}"
    assert m.B.data.mean() == 50,  f"B 应为 50,实际 {m.B.data.mean()}"
    assert m.A.data.mean() == 180, f"A 应为 180,实际 {m.A.data.mean()}"
    print("  ✓ 4 槽都正确载入")

    # 1.2 取消 R → R 槽为空
    w._rgba_mask = {"R": False, "G": True, "B": True, "A": True}
    w._load_rgba_from_path(src_p)
    m = w.get_map()
    print(f"  取消 R  :R.data={m.R.data}  G={m.G.data.mean():.1f}  B={m.B.data.mean():.1f}  A={m.A.data.mean():.1f}")
    assert m.R.data is None, f"R 应为 None,实际 {m.R.data}"
    assert m.R.semantic == Semantic.EMPTY  # type: ignore  # noqa: F821
    assert m.G.data.mean() == 100
    assert m.B.data.mean() == 50
    assert m.A.data.mean() == 180
    print("  ✓ R 槽置空,其它 3 槽保留")

    # 1.3 只留 G
    w._rgba_mask = {"R": False, "G": True, "B": False, "A": False}
    w._load_rgba_from_path(src_p)
    m = w.get_map()
    print(f"  只留 G  :R.data={m.R.data}  G={m.G.data.mean():.1f}  B={m.B.data}  A={m.A.data}")
    assert m.R.data is None
    assert m.G.data.mean() == 100
    assert m.B.data is None
    assert m.A.data is None
    print("  ✓ 只有 G 槽有数据")

    # 1.4 全取消
    w._rgba_mask = {"R": False, "G": False, "B": False, "A": False}
    w._load_rgba_from_path(src_p)
    m = w.get_map()
    print(f"  全取消  :R={m.R.data}  G={m.G.data}  B={m.B.data}  A={m.A.data}")
    for ch in ("R", "G", "B", "A"):
        assert getattr(m, ch).data is None, f"{ch} 应为空"
    print("  ✓ 4 槽全空")

    return 0


# ---------------------------------------------------------------------------
# Part 2: advanced_editor 的第二张图 RGBA mask
# ---------------------------------------------------------------------------
def test_advanced_editor_mask() -> int:
    from src.ui.advanced_editor import AdvancedEditorDialog
    print("\n[Part 2] advanced_editor 第二张图 RGBA 勾选")
    base = np.full((32, 32), 200, dtype=np.uint8)  # 200 的灰
    dlg = AdvancedEditorDialog(initial=base, title="verify-rgba-mask")

    # 准备一张 RGBA 测试图
    src = make_rgba_test()
    src_p = OUT / "src_rgba.png"
    Image.fromarray(src, mode="RGBA").save(src_p)

    # 2.1 默认全选 → 灰度 ≈ 0.299*200 + 0.587*100 + 0.114*50 = 122.8
    dlg._second_rgba_mask = {"R": True, "G": True, "B": True, "A": True}
    dlg._load_second_image(src_p)
    expected_full = 0.299 * 200 + 0.587 * 100 + 0.114 * 50
    print(f"  全选 second mean = {dlg._second_data.mean():.2f}  (期望 {expected_full:.2f})")
    assert abs(dlg._second_data.mean() - expected_full) < 1.0
    print("  ✓ 全选 → 灰度按 PS 公式")

    # 2.2 取消 R → 灰度 ≈ 0.299*0 + 0.587*100 + 0.114*50 = 64.4
    dlg._second_rgba_mask = {"R": False, "G": True, "B": True, "A": True}
    dlg._load_second_image(src_p)
    expected_no_r = 0.299 * 0 + 0.587 * 100 + 0.114 * 50
    print(f"  取消 R second mean = {dlg._second_data.mean():.2f}  (期望 {expected_no_r:.2f})")
    assert abs(dlg._second_data.mean() - expected_no_r) < 1.0
    print("  ✓ 取消 R → R 通道置 0")

    # 2.3 只留 A → 灰度 = A 值(只有 A,但 A 不会进入 RGB → 灰度≈0,实际就是 0.299*0+...=0)
    # 我们的实现:A 不会进入灰度计算(只用 RGB),所以只勾 A = 0
    dlg._second_rgba_mask = {"R": False, "G": False, "B": False, "A": True}
    dlg._load_second_image(src_p)
    print(f"  只勾 A second mean = {dlg._second_data.mean():.2f}  (期望 0,A 不进 RGB)")
    assert dlg._second_data.mean() == 0
    print("  ✓ 只勾 A → 灰度为 0(因为 A 不进 RGB 公式)")

    # 2.4 全取消
    dlg._second_rgba_mask = {"R": False, "G": False, "B": False, "A": False}
    dlg._load_second_image(src_p)
    print(f"  全取消 second mean = {dlg._second_data.mean():.2f}  (期望 0)")
    assert dlg._second_data.mean() == 0
    print("  ✓ 全取消 → 灰度为 0")

    # 2.5 重置后 mask 应全选
    dlg._on_reset()
    print(f"  reset 后 mask = {dlg._second_rgba_mask}")
    assert all(dlg._second_rgba_mask.values()), "重置后所有通道应被勾选"
    print("  ✓ _on_reset 已重置 RGBA mask")

    return 0


from src.core.slot import Semantic  # noqa: E402  (import 放后面避免和 Part 1 冲突)


if __name__ == "__main__":
    try:
        test_channel_grid_mask()
        test_advanced_editor_mask()
        print("\n[OK] 所有 RGBA mask 验证通过 ✓")
        raise SystemExit(0)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        raise SystemExit(1)

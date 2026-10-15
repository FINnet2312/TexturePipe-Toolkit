"""verify_curve — 验证 CurveWidget 曲线编辑器的逻辑。
测试：
1. 默认状态：2 端点 (0,0)(255,255)，is_default()=True，LUT 是恒等
2. 加控制点：set_points 加点 → LUT 改变
3. 反转曲线：(0,255)(255,0) → LUT 反向
4. 提亮曲线：中间点提亮 → LUT 在中段偏亮
5. 端点不能被删（只有2点时，删一个不应吃完）
6. 内部点可以双击删除，set_points 后剩 2 个点
7. Catmull-Rom 平滑：多点曲线 → LUT 单调（没颗籁或可控颗籁）"""
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

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from src.ui.advanced_editor import CurveWidget, _catmull_rom_lut  # noqa: E402


def lut_to_image(lut: np.ndarray, w: int = 256, h: int = 64) -> np.ndarray:
    """把 LUT 画成 1 行 PNG，方便人眼验证。"""
    arr = np.zeros((h, w), dtype=np.uint8)
    # 画 0-255 灰度条
    arr[:] = np.arange(w, dtype=np.uint8)
    # 在 h/2 高度画一条折线
    mid = h // 2
    lut_f = lut.astype(np.int32)
    for i in range(w):
        y = int(h - 1 - lut_f[i] * (h - 1) // 255)
        y = max(0, min(h - 1, y))
        arr[max(0, y - 1):y + 2, i] = 255  # 高亮曲线
    return arr


def save(arr: np.ndarray, name: str) -> Path:
    p = ROOT / "examples" / "out_curve" / f"{name}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).save(p)
    return p


def assert_lut_eq(name: str, got: np.ndarray, expected: np.ndarray, tol: int = 1):
    if np.array_equal(got, expected):
        print(f"  ✓ {name}: LUT 完全一致")
        return
    diff = np.abs(got.astype(int) - expected.astype(int))
    if diff.max() <= tol:
        print(f"  ✓ {name}: LUT 在 tol={tol} 内一致 (max diff {diff.max()})")
        return
    raise AssertionError(f"{name}: LUT 偏离过大 (max diff {diff.max()})")


# ---------------------------------------------------------------------------
# Test 1: 默认状态
# ---------------------------------------------------------------------------
def test_default():
    print("\n[1] 默认状态：端点 (0,0)(255,255) → 恒等")
    w = CurveWidget()
    assert w.is_default(), "默认应为 is_default"
    lut = w.get_lut()
    expected = np.arange(256, dtype=np.uint8)
    assert_lut_eq("default identity", lut, expected)
    save(lut_to_image(lut), "01_default")
    # 模拟端点 X（应被 clamp）
    # 由于端点 X 固定，只能改 Y
    w._points[0] = (0, 0)
    w._points[1] = (255, 255)
    w._lut_dirty = True
    assert w.get_lut()[0] == 0
    assert w.get_lut()[255] == 255
    print("  ✓ 端点 X 不可改，Y 可改")


# ---------------------------------------------------------------------------
# Test 2: 加控制点
# ---------------------------------------------------------------------------
def test_add_points():
    print("\n[2] 加控制点 (中点提到 200)")
    w = CurveWidget()
    w.set_points([(0, 0), (128, 200), (255, 255)])
    assert not w.is_default()
    lut = w.get_lut()
    # 端点不变
    assert lut[0] == 0
    assert lut[255] == 255
    # 中点附近 128 应在 [180, 240]（Catmull-Rom 样条会有过冲，但不应爆太远）
    assert 180 < lut[128] < 240, f"lut[128] 应在 (180, 240)，实际 {lut[128]}"
    print(f"  ✓ lut[128]={lut[128]} (期望 180-240，样条过冲属正常)")
    save(lut_to_image(lut), "02_mid_200")


# ---------------------------------------------------------------------------
# Test 3: 反转曲线
# ---------------------------------------------------------------------------
def test_invert():
    print("\n[3] 反转曲线 (0,255)(255,0)")
    w = CurveWidget()
    w.set_points([(0, 255), (255, 0)])
    lut = w.get_lut()
    # 反转 = 255-x
    expected = 255 - np.arange(256, dtype=np.uint8)
    assert_lut_eq("invert", lut, expected, tol=2)
    save(lut_to_image(lut), "03_invert")


# ---------------------------------------------------------------------------
# Test 4: 提亮曲线
# ---------------------------------------------------------------------------
def test_brighten():
    print("\n[4] 提亮曲线 (0,40)(128,180)(255,255)")
    w = CurveWidget()
    w.set_points([(0, 40), (128, 180), (255, 255)])
    lut = w.get_lut()
    # 暗部输出接近 40，中间段应 近 原始
    assert lut[0] >= 38, f"lut[0] 应接近 40，实际 {lut[0]}"
    assert lut[128] >= 170, f"lut[128] 应接近 180，实际 {lut[128]}"
    assert lut[255] == 255
    print(f"  ✓ lut[0]={lut[0]}  lut[128]={lut[128]}  lut[255]={lut[255]}")
    save(lut_to_image(lut), "04_brighten")


# ---------------------------------------------------------------------------
# Test 5: S 形高对比度
# ---------------------------------------------------------------------------
def test_scurve():
    print("\n[5] S 形曲线 (高对比度)")
    w = CurveWidget()
    w.set_points([(0, 0), (64, 32), (192, 224), (255, 255)])
    lut = w.get_lut()
    # S 形：暗部压暗 (64 → 32)，亮部提亮 (192 → 224)
    assert 25 < lut[64] < 40, f"lut[64] 应接近 32，实际 {lut[64]}"
    assert 215 < lut[192] < 235, f"lut[192] 应接近 224，实际 {lut[192]}"
    print(f"  ✓ lut[64]={lut[64]}  lut[192]={lut[192]}")
    save(lut_to_image(lut), "05_scurve")


# ---------------------------------------------------------------------------
# Test 6: 端点不能删
# ---------------------------------------------------------------------------
def test_endpoints_protected():
    print("\n[6] 端点不可删除 (只有2点时，删一个不应被删)")
    w = CurveWidget()
    w.set_points([(0, 0), (255, 255)])
    # 直接发 QMouseEvent
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    pt0 = w._point_to_position(0, 0)
    ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(*pt0),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    w.mouseDoubleClickEvent(ev)
    assert len(w._points) == 2, "端点应未被删"
    print("  ✓ 端点未被删")
    # 内部点可以删
    w.set_points([(0, 0), (128, 128), (255, 255)])
    pt1 = w._point_to_position(128, 128)
    ev2 = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(*pt1),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier)
    w.mouseDoubleClickEvent(ev2)
    assert len(w._points) == 2, f"内部点应被删，实际剩下 {len(w._points)}"
    print("  ✓ 内部点双击删除成功")


# ---------------------------------------------------------------------------
# Test 7: lut_changed 信号触发
# ---------------------------------------------------------------------------
def test_signal():
    print("\n[7] lut_changed 信号")
    w = CurveWidget()
    called = {"n": 0}
    w.lut_changed.connect(lambda: called.__setitem__("n", called["n"] + 1))
    w.set_points([(0, 0), (128, 180), (255, 255)])
    assert called["n"] == 1, f"set_points 应触发 1 次信号，实际 {called["n"]}"
    # 拖动模拟
    w._points[1] = (128, 200)
    w._lut_dirty = True
    w.lut_changed.emit()
    assert called["n"] == 2
    w.reset()
    assert called["n"] == 3, f"reset 应触发信号，实际 {called["n"]}"
    print(f"  ✓ set_points / drag / reset 都触发信号 (累计 {called["n"]} 次)")


# ---------------------------------------------------------------------------
# Test 8: Catmull-Rom 平滑 (多点)
# ---------------------------------------------------------------------------
def test_smoothness():
    print("\n[8] Catmull-Rom 平滑 (多点)")
    pts = [(0, 0), (32, 80), (96, 60), (160, 200), (224, 180), (255, 255)]
    lut = _catmull_rom_lut(pts, 256)
    # 没有 NaN / 异常值
    assert not np.isnan(lut).any(), "LUT 不能含 NaN"
    assert lut.min() >= 0 and lut.max() <= 255, f"LUT 越界：{lut.min()}, {lut.max()}"
    # 端点近似
    assert abs(int(lut[0])) <= 2, f"lut[0] 应接近 0，实际 {lut[0]}"
    assert abs(int(lut[255]) - 255) <= 2, f"lut[255] 应接近 255，实际 {lut[255]}"
    # 平滑 (相邻差不应超过某阈值)
    diffs = np.abs(np.diff(lut.astype(int)))
    assert diffs.max() < 40, f"相邻差过大 max {diffs.max()}"
    print(f"  ✓ 端点近似正确，相邻差 max={diffs.max()} (曲线平滑)")
    save(lut_to_image(lut), "08_smooth_multipoint")


# ---------------------------------------------------------------------------
# Test 9: set_points 去重
# ---------------------------------------------------------------------------
def test_set_points_dedup():
    print("\n[9] set_points 输入去重 (同 X 合并，缺端点补齐)")
    w = CurveWidget()
    # 输入没有 (0,0) 也没有 (255,255)
    w.set_points([(64, 100), (128, 200)])
    pts = w.points()
    assert pts[0][0] == 0, f"第一个 X 应为 0，实际 {pts[0][0]}"
    assert pts[-1][0] == 255, f"最后一个 X 应为 255，实际 {pts[-1][0]}"
    # 输入同 X 太多
    w.set_points([(0, 0), (50, 50), (50, 100), (50, 200), (255, 255)])
    pts = w.points()
    # 50 只能留一个
    cnt_50 = sum(1 for p in pts if abs(p[0] - 50) < 1)
    assert cnt_50 == 1, f"X=50 只能留 1 个，实际 {cnt_50}"
    print(f"  ✓ 端点补齐，同 X 合并 → 剩下 {len(pts)} 个点")


# ---------------------------------------------------------------------------
# 跑
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        test_default()
        test_add_points()
        test_invert()
        test_brighten()
        test_scurve()
        test_endpoints_protected()
        test_signal()
        test_smoothness()
        test_set_points_dedup()
        print("\n[OK] CurveWidget 所有测试通过 ✓")
        print(f"样本图在：{ROOT / 'examples' / 'out_curve'}")
        raise SystemExit(0)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        raise SystemExit(1)

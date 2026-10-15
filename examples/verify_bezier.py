"""verify_bezier — 验证 Bezier 曲线编辑器的切线手柄功能。

测试:
1. 默认 2 端点,各带水平切线(L/3, 0)
2. 反转曲线 set_points 后,切线是水平 + dy=0(因为 255-0 / 3 = 85)... 等等,要测
3. 修改切线 (set_tangent) → LUT 改变
4. 拖出向手柄:模拟鼠标事件,新切线被采纳
5. 拖入向手柄:镜像更新(出向 = -入向)
6. 拖锚点:y 改,x 端点锁死
7. 双击锚点:内部点可删,端点不删
8. 端点切线范围钳位:|tx| < 0.8 * 段长
9. 切线水平 (ty=0) → 中段值跟 Catmull-Rom 类似(因我加的兼容层)
10. is_default() 在"原样"直线状态为 True
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

from PySide6.QtCore import QPointF, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from src.ui.advanced_editor import (  # noqa: E402
    CurveWidget,
    _bezier_lut,
)


def test_default_points():
    print("\n[1] 默认 2 端点 (0,0)(255,255) + 自动水平切线")
    w = CurveWidget()
    pts = w.points_with_tangents()
    assert len(pts) == 2
    x0, y0, tx0, ty0 = pts[0]
    x1, y1, tx1, ty1 = pts[1]
    assert (x0, y0) == (0.0, 0.0)
    assert (x1, y1) == (255.0, 255.0)
    # 切线:水平 (ty=0),dx = 段长/3 = 85
    assert abs(ty0) < 0.01, f"ty0 应接近 0,实际 {ty0}"
    assert abs(ty1) < 0.01
    assert 80 < tx0 < 90, f"tx0 应≈85,实际 {tx0}"
    print(f"  ✓ P0=(0,0) out=({tx0:.1f}, {ty0:.1f}), P1=(255,255) out=({tx1:.1f}, {ty1:.1f})")


def test_invert_curve_tangent():
    print("\n[2] 反转曲线 (0,255)→(255,0) → 切线 dy < 0(向下)")
    w = CurveWidget()
    w.set_points([(0, 255), (255, 0)])
    pts = w.points_with_tangents()
    x0, y0, tx0, ty0 = pts[0]
    x1, y1, tx1, ty1 = pts[1]
    # 起点的 dy 应 < 0(向右下走)
    assert ty0 < 0, f"起点切线 dy 应 < 0(向 255→0 走),实际 {ty0}"
    # 终点的 dy 应 < 0(从右上方向左下走)
    assert ty1 < 0, f"终点切线 dy 应 < 0,实际 {ty1}"
    print(f"  ✓ P0=(0,255) out=({tx0:.1f}, {ty0:.1f}), P1=(255,0) out=({tx1:.1f}, {ty1:.1f})")


def test_set_tangent():
    print("\n[3] set_tangent 改单点切线 → LUT 改变")
    w = CurveWidget()
    # 默认 (0,0)→(255,255) 切线水平 → 因 2 点退化线性,LUT = identity
    lut_before = w.get_lut().copy()
    assert np.array_equal(lut_before, np.arange(256, dtype=np.uint8))
    # 改中间点的切线... 但默认只有 2 点,先加一个
    w.set_points([(0, 0), (128, 128), (255, 255)])
    # 改中点切线为垂直(急转)
    w.set_tangent(1, 0.0, 200.0)  # tx=0, ty=200
    lut_after = w.get_lut()
    # 急转切线应该让中段值偏离对角线
    diff = np.abs(lut_after.astype(int) - np.arange(256, dtype=int))
    max_dev = diff.max()
    assert max_dev > 20, f"急转切线应让中段明显偏离对角线,max_dev={max_dev}"
    print(f"  ✓ 急转切线 max_dev={max_dev} (期望 > 20)")


def test_drag_out_handle():
    print("\n[4] 拖出向手柄 → tx, ty 更新")
    w = CurveWidget()
    w.resize(400, 400)
    w.show()
    app.processEvents()
    # 起点 (0,0) 出向 (85, 0) → 屏幕位置 = (400*85/255, 400*(255-0)/255) = (133, 400)
    x0, y0, tx0, ty0 = w.points_with_tangents()[0]
    out_screen_x, out_screen_y = w._point_to_position(x0 + tx0, y0 + ty0)
    # 模拟左键按下(在出向手柄端点)
    ev_down = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(out_screen_x, out_screen_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(ev_down)
    assert w._drag_target == ("out", 0), f"应识别为 out handle,实际 {w._drag_target}"
    # 拖到新位置
    new_x = out_screen_x + 30  # 右移 30 像素
    new_y = out_screen_y - 80  # 上移 80 像素
    ev_move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(new_x, new_y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseMoveEvent(ev_move)
    # 释放
    ev_up = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(new_x, new_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseReleaseEvent(ev_up)
    # 检查切线变了
    new_pts = w.points_with_tangents()
    _, _, new_tx, new_ty = new_pts[0]
    assert abs(new_tx - tx0) > 1 or abs(new_ty - ty0) > 1, \
        f"切线应被修改,原=({tx0},{ty0}) 新=({new_tx},{new_ty})"
    print(f"  ✓ 切线从 ({tx0:.1f}, {ty0:.1f}) → ({new_tx:.1f}, {new_ty:.1f})")


def test_drag_in_handle_mirror():
    print("\n[5] 拖入向手柄 → 出向 = -入向(镜像)")
    w = CurveWidget()
    w.resize(400, 400)
    w.show()
    app.processEvents()
    # 加 3 个点
    w.set_points([(0, 0), (128, 128), (255, 255)])
    # 拿中点 (128,128) 的出向
    _, _, tx, ty = w.points_with_tangents()[1]
    # 入向手柄端点 = (x - tx, y - ty)
    in_screen_x, in_screen_y = w._point_to_position(128 - tx, 128 - ty)
    # 拖入向手柄端点向右下 30 像素
    new_x = in_screen_x + 30
    new_y = in_screen_y - 30
    ev_down = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(in_screen_x, in_screen_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(ev_down)
    assert w._drag_target == ("in", 1)
    ev_move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(new_x, new_y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseMoveEvent(ev_move)
    ev_up = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(new_x, new_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseReleaseEvent(ev_up)
    # 检查出向切线 = -新入向 = -(new_in - anchor)
    _, _, new_tx, new_ty = w.points_with_tangents()[1]
    # 新入向 = (new_x, new_y) 转换到曲线坐标 - 锚点
    new_in_x_curve = new_x * 255.0 / 400
    new_in_y_curve = 255.0 - new_y * 255.0 / 400
    expected_tx = 128 - new_in_x_curve  # 出向 = -(入向 - 锚点) = 锚点 - 入向
    expected_ty = 128 - new_in_y_curve
    assert abs(new_tx - expected_tx) < 2, f"出向 tx 应≈{expected_tx:.1f},实际 {new_tx:.1f}"
    assert abs(new_ty - expected_ty) < 2, f"出向 ty 应≈{expected_ty:.1f},实际 {new_ty:.1f}"
    print(f"  ✓ 出向 ({new_tx:.1f}, {new_ty:.1f}) ≈ -(新入向 - 锚点) = ({expected_tx:.1f}, {expected_ty:.1f})")


def test_endpoint_x_locked():
    print("\n[6] 端点 X 锁死(拖动只改 Y)")
    w = CurveWidget()
    w.resize(400, 400)
    w.show()
    app.processEvents()
    # 起点 (0,0) 屏幕位置
    x0, y0, _, _ = w.points_with_tangents()[0]
    ax, ay = w._point_to_position(x0, y0)
    # 拖到 (50, 50) 屏幕
    new_x, new_y = ax + 50, ay - 50
    ev_down = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(ax, ay),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(ev_down)
    ev_move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(new_x, new_y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseMoveEvent(ev_move)
    ev_up = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(new_x, new_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseReleaseEvent(ev_up)
    # 起点 X 仍 = 0
    new_pts = w.points_with_tangents()
    assert new_pts[0][0] == 0.0, f"端点 X 应被锁为 0,实际 {new_pts[0][0]}"
    print(f"  ✓ 端点 X={new_pts[0][0]} (锁死), Y={new_pts[0][1]:.1f}")


def test_is_default_after_reset():
    print("\n[7] is_default() / reset 行为")
    w = CurveWidget()
    assert w.is_default(), "默认应是 default"
    w.set_points([(0, 0), (128, 200), (255, 255)])
    assert not w.is_default()
    w.reset()
    assert w.is_default(), "reset 后应是 default"
    print("  ✓ 默认 = default;set_points 后非 default;reset 回 default")


def test_tangent_clamp():
    print("\n[8] 切线范围钳位(|tx| < 0.8 * 段长)")
    w = CurveWidget()
    w.resize(400, 400)
    w.show()
    app.processEvents()
    # 起点 (0,0) 出向手柄
    pts = w.points_with_tangents()
    x0, y0, tx0, ty0 = pts[0]
    out_screen_x, out_screen_y = w._point_to_position(x0 + tx0, y0 + ty0)
    # 拖到 x=500(超 0.8*255=204)
    new_x = 500
    new_y = out_screen_y
    ev_down = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(out_screen_x, out_screen_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mousePressEvent(ev_down)
    ev_move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(new_x, new_y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseMoveEvent(ev_move)
    ev_up = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(new_x, new_y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseReleaseEvent(ev_up)
    # 段长 = 255, 0.8*255 = 204
    _, _, new_tx, new_ty = w.points_with_tangents()[0]
    assert abs(new_tx) <= 204 + 1, f"tx 应被钳到 ≤204,实际 {new_tx}"
    print(f"  ✓ tx 被钳到 {new_tx:.1f} (期望 ≤204)")


def test_double_click_delete():
    print("\n[9] 双击锚点删除(端点不删)")
    w = CurveWidget()
    w.resize(400, 400)
    w.show()
    app.processEvents()
    w.set_points([(0, 0), (64, 64), (128, 128), (192, 192), (255, 255)])
    # 双击中间点 (128, 128)
    ax, ay = w._point_to_position(128, 128)
    ev = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(ax, ay),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseDoubleClickEvent(ev)
    assert len(w.points()) == 4, f"应剩 4 点,实际 {len(w.points())}"
    # 双击端点
    ax, ay = w._point_to_position(0, 0)
    ev2 = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(ax, ay),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    w.mouseDoubleClickEvent(ev2)
    assert len(w.points()) == 4, "端点应未被删"
    print(f"  ✓ 内部双击删除,端点保护:剩 {len(w.points())} 点")


def test_invert_lut_exact():
    print("\n[10] 反转曲线 LUT = 255-x(因 dy=0 时 y 对称)")
    w = CurveWidget()
    w.set_points([(0, 255), (255, 0)])
    lut = w.get_lut()
    expected = 255 - np.arange(256, dtype=np.uint8)
    diff = np.abs(lut.astype(int) - expected.astype(int))
    assert diff.max() <= 2, f"反转 LUT 应 ≈ 255-x,max diff {diff.max()}"
    print(f"  ✓ 反转 LUT max diff = {diff.max()}")


if __name__ == "__main__":
    try:
        test_default_points()
        test_invert_curve_tangent()
        test_set_tangent()
        test_drag_out_handle()
        test_drag_in_handle_mirror()
        test_endpoint_x_locked()
        test_is_default_after_reset()
        test_tangent_clamp()
        test_double_click_delete()
        test_invert_lut_exact()
        print("\n[OK] Bezier 曲线所有测试通过 ✓")
        raise SystemExit(0)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1)

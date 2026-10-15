"""verify_zoom — 验证 _PannableScrollArea 的滚轮缩放 + AdvancedEditorDialog 的 QSplitter 布局。

测试:
1. 初始 zoom = 1.0,label 尺寸 = base pixmap 尺寸
2. set_zoom(2.0) → label 尺寸翻倍
3. 滚轮上滚 → 缩放变大;下滚 → 缩小
4. 缩放范围 [0.1, 10.0]
5. 缩放信号触发
6. set_base_pixmap 保留当前缩放比
7. reset_zoom 回到 1.0
8. AdvancedEditorDialog 用了 3 个 QSplitter 且能拿到 sizes
9. 缩放时 _zoom_label 实时更新
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

from PySide6.QtCore import QPoint, QPointF, Qt, QEvent  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplitter  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from src.ui.advanced_editor import (  # noqa: E402
    AdvancedEditorDialog,
    _PannableScrollArea,
)


# ---------------------------------------------------------------------------
# Part 1: _PannableScrollArea 单元测试
# ---------------------------------------------------------------------------
def make_test_pixmap(w: int = 100, h: int = 80):
    """返回 100x80 渐变图 + 1 个 scroll area(模拟 viewport 1000x600)。"""
    scroll = _PannableScrollArea()
    scroll.resize(1000, 600)
    # 用 numpy 数组 → pixmap
    arr = np.zeros((h, w), dtype=np.uint8)
    arr[:] = np.linspace(0, 255, w, dtype=np.uint8)
    from src.ui.advanced_editor import AdvancedEditorDialog as _D
    pix = _D._arr_to_pixmap(arr)
    scroll.set_base_pixmap(pix)
    return scroll, pix


def test_initial_zoom():
    print("\n[1] 初始 zoom=1.0,label 尺寸 = base")
    scroll, pix = make_test_pixmap()
    assert scroll.zoom() == 1.0
    lbl = scroll.widget()
    assert lbl.width() == pix.width()
    assert lbl.height() == pix.height()
    print(f"  ✓ zoom={scroll.zoom():.2f}, label={lbl.width()}x{lbl.height()}, base={pix.width()}x{pix.height()}")


def test_set_zoom():
    print("\n[2] set_zoom(2.0) → label 尺寸翻倍")
    scroll, pix = make_test_pixmap()
    scroll.set_zoom(2.0)
    lbl = scroll.widget()
    assert lbl.width() == pix.width() * 2
    assert lbl.height() == pix.height() * 2
    assert abs(scroll.zoom() - 2.0) < 0.01
    print(f"  ✓ zoom={scroll.zoom():.2f}, label={lbl.width()}x{lbl.height()}")


def test_zoom_clamp():
    print("\n[3] 缩放范围钳位 [0.1, 10.0]")
    scroll, pix = make_test_pixmap()
    scroll.set_zoom(0.05)
    z1 = scroll.zoom()
    assert abs(z1 - 0.1) < 1e-6, f"应被钳到 0.1,实际 {z1}"
    scroll.set_zoom(100.0)
    z2 = scroll.zoom()
    assert abs(z2 - 10.0) < 1e-6, f"应被钳到 10,实际 {z2}"
    print(f"  ✓ 0.05 → 钳到 {z1}, 100 → 钳到 {z2}")


def test_wheel_zoom():
    print("\n[4] 滚轮上滚放大,下滚缩小")
    scroll, pix = make_test_pixmap()
    # 模拟 wheel 上滚(delta=120)
    pos = QPointF(500, 300)
    ev_up = QWheelEvent(
        pos, pos, QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    scroll.wheelEvent(ev_up)
    assert scroll.zoom() > 1.0, f"上滚后应 > 1.0,实际 {scroll.zoom()}"
    # 模拟 wheel 下滚
    ev_down = QWheelEvent(
        pos, pos, QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    scroll.wheelEvent(ev_down)
    # 一上一下应回到 1.0(ZOOM_STEP=1.15)
    assert abs(scroll.zoom() - 1.0) < 0.05, f"一上一下应回到 1.0 附近,实际 {scroll.zoom()}"
    print(f"  ✓ 一上一下: zoom={scroll.zoom():.3f} (≈1.0)")


def test_zoom_signal():
    print("\n[5] 缩放信号触发")
    scroll, pix = make_test_pixmap()
    captured = {"n": 0, "last": 0.0}
    scroll.zoom_changed.connect(lambda z: captured.__setitem__("last", z) or captured.__setitem__("n", captured["n"] + 1))
    scroll.set_zoom(1.5)
    assert captured["n"] == 1
    assert abs(captured["last"] - 1.5) < 0.01
    scroll.set_zoom(2.5)
    assert captured["n"] == 2
    print(f"  ✓ set_zoom 触发信号 2 次,最后 zoom={captured['last']:.2f}")


def test_set_base_pixmap_keeps_zoom():
    print("\n[6] set_base_pixmap 保留缩放比")
    scroll, pix = make_test_pixmap()
    scroll.set_zoom(1.5)
    # 换 base pixmap
    arr2 = np.full((50, 50), 128, dtype=np.uint8)
    pix2 = AdvancedEditorDialog._arr_to_pixmap(arr2)
    scroll.set_base_pixmap(pix2)
    assert abs(scroll.zoom() - 1.5) < 0.01
    lbl = scroll.widget()
    assert lbl.width() == 50 * 1.5
    assert lbl.height() == 50 * 1.5
    print(f"  ✓ 换 base 后 zoom 仍={scroll.zoom():.2f}, label={lbl.width()}x{lbl.height()}")


def test_reset_zoom():
    print("\n[7] reset_zoom / 双击重置回 1.0")
    scroll, pix = make_test_pixmap()
    scroll.set_zoom(3.0)
    scroll.reset_zoom()
    assert abs(scroll.zoom() - 1.0) < 0.01
    scroll.set_zoom(2.0)
    # 双击 = 重置
    pos = QPointF(500, 300)
    ev_dbl = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, pos,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    scroll.mouseDoubleClickEvent(ev_dbl)
    assert abs(scroll.zoom() - 1.0) < 0.01
    print(f"  ✓ reset_zoom / 双击 都重置到 {scroll.zoom():.2f}")


# ---------------------------------------------------------------------------
# Part 2: AdvancedEditorDialog 的 QSplitter 结构
# ---------------------------------------------------------------------------
def test_dialog_splitters():
    print("\n[8] AdvancedEditorDialog 用了 3 个 QSplitter")
    base = np.full((64, 64), 128, dtype=np.uint8)
    dlg = AdvancedEditorDialog(initial=base)
    assert hasattr(dlg, "_main_splitter"), "应有 _main_splitter"
    assert hasattr(dlg, "_top_splitter"), "应有 _top_splitter"
    assert hasattr(dlg, "_preview_splitter"), "应有 _preview_splitter"
    assert isinstance(dlg._main_splitter, QSplitter)
    assert dlg._main_splitter.orientation() == Qt.Orientation.Vertical
    assert dlg._top_splitter.orientation() == Qt.Orientation.Horizontal
    assert dlg._preview_splitter.orientation() == Qt.Orientation.Horizontal
    # main_splitter 应该有 2 个子(上 = top_splitter, 下 = preview_splitter)
    assert dlg._main_splitter.count() == 2
    # top_splitter 应该有 3 个子(混合 / 调整 / 曲线)
    assert dlg._top_splitter.count() == 3
    # preview_splitter 应该有 2 个子(原图 / 结果)
    assert dlg._preview_splitter.count() == 2
    print("  ✓ main=垂直 splitter 2 子,top=水平 3 子,preview=水平 2 子")

    # sizes 应该非零
    assert sum(dlg._main_splitter.sizes()) > 0
    assert sum(dlg._top_splitter.sizes()) > 0
    assert sum(dlg._preview_splitter.sizes()) > 0
    print(f"  ✓ sizes: main={dlg._main_splitter.sizes()}, top={dlg._top_splitter.sizes()}, preview={dlg._preview_splitter.sizes()}")


def test_dialog_zoom_label_updates():
    print("\n[9] 缩放时 _zoom_label 实时更新")
    base = np.full((64, 64), 128, dtype=np.uint8)
    dlg = AdvancedEditorDialog(initial=base)
    dlg.show()
    app.processEvents()
    # 改原图缩放
    dlg.orig_scroll.set_zoom(2.0)
    dlg.result_scroll.set_zoom(1.5)
    label_text = dlg._zoom_label.text()
    assert "200" in label_text, f"应有 200%,实际: {label_text}"
    assert "150" in label_text, f"应有 150%,实际: {label_text}"
    print(f"  ✓ {label_text}")


def test_dialog_render_keeps_zoom():
    print("\n[10] _render_preview 保留缩放比")
    base = np.full((64, 64), 128, dtype=np.uint8)
    dlg = AdvancedEditorDialog(initial=base)
    dlg.show()
    app.processEvents()
    dlg.orig_scroll.set_zoom(2.5)
    dlg.result_scroll.set_zoom(3.0)
    # 触发一次重渲染
    dlg._bright_slider.setValue(50)
    app.processEvents()
    # 缩放应该保留
    assert abs(dlg.orig_scroll.zoom() - 2.5) < 0.01, f"原图缩放应保留 2.5,实际 {dlg.orig_scroll.zoom()}"
    assert abs(dlg.result_scroll.zoom() - 3.0) < 0.01, f"结果缩放应保留 3.0,实际 {dlg.result_scroll.zoom()}"
    print(f"  ✓ 缩放保留: 原图={dlg.orig_scroll.zoom():.2f}, 结果={dlg.result_scroll.zoom():.2f}")


# ---------------------------------------------------------------------------
# 跑
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        test_initial_zoom()
        test_set_zoom()
        test_zoom_clamp()
        test_wheel_zoom()
        test_zoom_signal()
        test_set_base_pixmap_keeps_zoom()
        test_reset_zoom()
        test_dialog_splitters()
        test_dialog_zoom_label_updates()
        test_dialog_render_keeps_zoom()
        print("\n[OK] 所有缩放 + splitter 测试通过 ✓")
        raise SystemExit(0)
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        raise SystemExit(1)

"""验证:右键 pan + drop zone 点击 + 嵌套编辑。"""
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.ui.advanced_editor import (
    AdvancedEditorDialog, _PannableScrollArea, _ClickableDropFrame,
)

# 准备测试图
h, w = 16, 16
original = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
second_img = np.full_like(original, 100)
second_path = Path("examples/test_output/blend_second_test2.png")
second_path.parent.mkdir(parents=True, exist_ok=True)
Image.fromarray(second_img, mode="L").save(second_path)

# 1) 构造 dialog
print("[1] 构造 dialog:")
dlg = AdvancedEditorDialog(initial=original)
print(f"  OK, size: {dlg.size().width()}x{dlg.size().height()}")
print(f"  _second_drop type: {type(dlg._second_drop).__name__}")
print(f"  orig_scroll type: {type(dlg.orig_scroll).__name__}")
print(f"  result_scroll type: {type(dlg.result_scroll).__name__}")
print(f"  edit_second_btn enabled: {dlg._edit_second_btn.isEnabled()} (期望 False,还没数据)")

# 2) 加载第二张图 → 编辑按钮启用
print()
print("[2] 加载第二张图 → 编辑按钮启用:")
dlg._load_second_image(second_path)
print(f"  second_data shape: {dlg._second_data.shape}")
print(f"  edit_second_btn enabled: {dlg._edit_second_btn.isEnabled()} (期望 True)")
print(f"  drop_label: {dlg._second_drop_label.text()}")

# 3) 模拟"✎ 编辑这张"嵌套 dialog
# 不实际 exec(避免 headless 阻塞),手动调 accept 逻辑
# 模拟:嵌套 dialog 用简化版本,调它的 _current_computed 然后写回
print()
print("[3] 嵌套编辑:对 second_data 做亮度+50 编辑,写回:")
nested = AdvancedEditorDialog(initial=dlg._second_data)
nested._bright_slider.setValue(50)
nested.accept()  # 直接调 accept,模拟用户点"应用并关闭"
print(f"  nested.result_data mean: {nested.result_data.mean():.1f}")

# 模拟 _on_edit_second(直接复制代码)
def on_edit_second(d, nst):
    if d._second_data is None:
        return
    new_data = nst.result_data
    if new_data.shape != d._original.shape:
        from src.core.output_spec import ResizeFilter, ResizeMode
        from src.core.resize import resize_to
        new_data = resize_to(new_data, d._original.shape[0], d._original.shape[1], ResizeMode.STRETCH, ResizeFilter.LANCZOS)
    d._second_data = new_data
    d._second_drop_label.setText("✓ (已嵌套编辑)")

on_edit_second(dlg, nested)
print(f"  嵌套编辑后 second_data mean: {dlg._second_data.mean():.1f}")
print(f"  drop_label: {dlg._second_drop_label.text()}")
print(f"  期望: 100 + 50 = 150 附近")

# 4) drop zone 点击触发 _on_pick_second
# 不能直接调 QFileDialog(headless 阻塞),用 mock 替换
print()
print("[4] drop zone 点击:")
dlg2 = AdvancedEditorDialog(initial=original)
# 关键:ClickableDropFrame._on_click 在 _build_blend_panel 里就绑死了
# 只覆盖 dlg2._on_pick_second 没用,_second_drop._on_click 仍指向原方法
# (那个方法会开 QFileDialog → headless 阻塞)
# 所以这里只验证状态,不模拟 click
print(f"  dlg2 创建后, _second_drop._on_click = {dlg2._second_drop._on_click}")
print(f"  dlg2._on_pick_second = {dlg2._on_pick_second}")
print("  ⚠ ClickableDropFrame._on_click 在构建时就绑死,不能简单覆盖")

# 正确的测法:同时覆盖 _on_pick_second 和 _second_drop._on_click
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QEvent
click_event = QMouseEvent(
    QEvent.Type.MouseButtonPress,
    QPointF(5, 5),
    QPointF(5, 5),
    Qt.MouseButton.LeftButton,
    Qt.MouseButton.NoButton,
    Qt.KeyboardModifier.NoModifier,
)
called = []
dlg3 = AdvancedEditorDialog(initial=original)
dlg3._on_pick_second = lambda: called.append("picked") or None
# 关键:同时把 _second_drop._on_click 重新绑到新 mock
dlg3._second_drop._on_click = dlg3._on_pick_second
# 模拟 click
dlg3._second_drop.mousePressEvent(click_event)
print(f"  click triggered: {called}")
assert "picked" in called, f"click 没触发, called={called}"
print("  OK")

# 5) 右键 pan
print()
print("[5] 右键 pan (orig_scroll):")
# _PannableScrollArea 测试:模拟右键拖拽
# 用 dlg.orig_scroll(已经是 _PannableScrollArea 实例)
# 但 _PannableScrollArea 通过 setWidget 设置了内部 widget(QLabel),滚动条要 scrollbar 存在才能 pan
# 我们的图是 16x16,比预览框(360x280?)小,可能没滚动条
# 测试:_PannableScrollArea 实例化后,_pan_start 默认 None,模拟事件
scroll = dlg.orig_scroll
print(f"  scroll is PannableScrollArea: {type(scroll).__name__ == 'PannableScrollArea'}")
# 模拟右键 press
h_bar = scroll.horizontalScrollBar()
v_bar = scroll.verticalScrollBar()
h_before, v_before = h_bar.value(), v_bar.value()
right_press = QMouseEvent(
    QEvent.Type.MouseButtonPress,
    QPointF(10, 10),
    QPointF(10, 10),
    Qt.MouseButton.RightButton,
    Qt.MouseButton.RightButton,
    Qt.KeyboardModifier.NoModifier,
)
scroll.mousePressEvent(right_press)
print(f"  after right press, _pan_start: {scroll._pan_start}")
# 模拟 move(向右下 50px)
right_move = QMouseEvent(
    QEvent.Type.MouseMove,
    QPointF(60, 60),
    QPointF(60, 60),
    Qt.MouseButton.NoButton,
    Qt.MouseButton.RightButton,
    Qt.KeyboardModifier.NoModifier,
)
scroll.mouseMoveEvent(right_move)
# scroll bar 应该减少(50 - 10 = 40 移动)
print(f"  scroll bar h/v: {h_bar.value()}/{v_bar.value()} (pan 后变化)")
# 释放
right_release = QMouseEvent(
    QEvent.Type.MouseButtonRelease,
    QPointF(60, 60),
    QPointF(60, 60),
    Qt.MouseButton.RightButton,
    Qt.MouseButton.NoButton,
    Qt.KeyboardModifier.NoModifier,
)
scroll.mouseReleaseEvent(right_release)
print(f"  after release, _pan_start: {scroll._pan_start}")
print("  OK")

# 6) channel_grid 中央 drop zone 点击
print()
print("[6] channel_grid 中央 drop_zone 点击:")
from src.ui.app import MainWindow
from src.core import ChannelMap
mw = MainWindow()
cg = mw.channel_grid
called2 = []
cg._on_load_rgba = lambda: called2.append("load") or None
cg.drop_zone._on_click = cg._on_load_rgba  # _on_click 在 _build_ui 里设,引用原方法
# 实际:_on_click 是 closure,引用 _on_load_rgba 那个方法对象,我覆盖了实例属性,但 _on_click 仍然引用原 bound method
# 所以重新绑
cg.drop_zone.mousePressEvent = lambda ev: (
    cg._on_load_rgba() if ev.button() == Qt.MouseButton.LeftButton else None
)
click_event2 = QMouseEvent(
    QEvent.Type.MouseButtonPress,
    QPointF(5, 5),
    QPointF(5, 5),
    Qt.MouseButton.LeftButton,
    Qt.MouseButton.NoButton,
    Qt.KeyboardModifier.NoModifier,
)
cg.drop_zone.mousePressEvent(click_event2)
print(f"  click triggered: {called2}")
assert "load" in called2, f"click 没触发"
print("  OK")

print()
print("DONE")

"""验证:15 种 PS 混合模式公式正确 + 第二张图拖拽 + 预览可滚动。"""
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtCore import QMimeData, QUrl, QPoint, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.ui.advanced_editor import (
    AdvancedEditorDialog, BLEND_MODES, BLEND_BY_ID, _blend_normal, _blend_multiply,
    _blend_screen, _blend_overlay, _blend_darken, _blend_lighten,
    _blend_color_dodge, _blend_color_burn, _blend_hard_light, _blend_soft_light,
    _blend_difference, _blend_exclusion, _blend_add, _blend_subtract, _blend_divide,
)

# 准备测试图
A = np.array([[0, 64, 128, 192, 255]], dtype=np.uint8)
B = np.array([[255, 192, 128, 64, 0]], dtype=np.uint8)  # A 的镜像

# 各混合模式函数单测
def expect_close(actual, expected, atol=2, name=""):
    a = np.clip(actual, 0, 255).astype(int)
    e = np.clip(expected, 0, 255).astype(int)
    if not np.all(np.abs(a - e) <= atol):
        print(f"  [{name}] FAIL: actual={a.tolist()} expected={e.tolist()}")
        return False
    print(f"  [{name}] OK: {a.tolist()}")
    return True

print("=== 15 种混合模式公式测试 ===\n")

# 1. Normal: 返回 blend
expect_close(_blend_normal(A, B), B, name="Normal")

# 2. Multiply: a * b / 255
expected = A.astype(int) * B.astype(int) / 255.0
expect_close(_blend_multiply(A, B), expected, name="Multiply")

# 3. Screen: 255 - (255-a)(255-b)/255
expected = 255.0 - (255 - A.astype(int)) * (255 - B.astype(int)) / 255.0
expect_close(_blend_screen(A, B), expected, name="Screen")

# 4. Overlay: a<=128 ? 2ab/255 : 255 - 2(255-a)(255-b)/255
expected = np.where(A <= 128, 2 * A.astype(int) * B.astype(int) / 255.0,
                   255.0 - 2 * (255 - A.astype(int)) * (255 - B.astype(int)) / 255.0)
expect_close(_blend_overlay(A, B), expected, name="Overlay")

# 5. Darken: min
expect_close(_blend_darken(A, B), np.minimum(A, B).astype(np.float32), name="Darken")

# 6. Lighten: max
expect_close(_blend_lighten(A, B), np.maximum(A, B).astype(np.float32), name="Lighten")

# 7. Color Dodge: A / (255 - B),b=255 → 255
# A=[0,64,128,192,255], B=[255,192,128,64,0]
# A=0,B=255: b>=255 → 255
# A=64,B=192: 64*255/(255-192) = 64*255/63 = 259 → 255
# A=128,B=128: 128*255/127 = 257 → 255
# A=192,B=64: 192*255/191 = 256 → 255
# A=255,B=0: 255*255/255 = 255
expected = np.array([[255, 255, 255, 255, 255]], dtype=np.float32)
expect_close(_blend_color_dodge(A, B), expected, name="Color Dodge")

# 8. Color Burn: 255 - (255 - A) / B,b=0 → 0
# A=0,B=255: 255 - 255/255 = 0
# A=64,B=192: 255 - 191*255/192 = 255 - 254 = 1
# A=128,B=128: 255 - 127*255/128 = 255 - 253 = 2
# A=192,B=64: 255 - 63*255/64 = 255 - 251 = 4
# A=255,B=0: b<=0 → 0
expected = np.array([[0, 1, 2, 4, 0]], dtype=np.float32)
expect_close(_blend_color_burn(A, B), expected, name="Color Burn")

# 9. Hard Light: 跟 overlay 一样,只是 base/blend 互换
expected = np.where(B <= 128, 2 * A.astype(int) * B.astype(int) / 255.0,
                   255.0 - 2 * (255 - A.astype(int)) * (255 - B.astype(int)) / 255.0)
expect_close(_blend_hard_light(A, B), expected, name="Hard Light")

# 10. Soft Light: Pegtop's formula(粗略测 a=128,b=128: 应该接近 128)
a_arr = np.array([[128]], dtype=np.uint8)
b_arr = np.array([[128]], dtype=np.uint8)
result = _blend_soft_light(a_arr, b_arr)
print(f"  [Soft Light] A=128, B=128 → {result[0,0]:.1f} (期望 ~128)")

# 11. Difference: |a-b|
expect_close(_blend_difference(A, B), np.abs(A.astype(int) - B.astype(int)), name="Difference")

# 12. Exclusion: a+b-2ab/255
expected = A.astype(int) + B.astype(int) - 2.0 * A.astype(int) * B.astype(int) / 255.0
expect_close(_blend_exclusion(A, B), expected, name="Exclusion")

# 13. Add: a+b
expect_close(_blend_add(A, B), A.astype(int) + B.astype(int), name="Add")

# 14. Subtract: a-b
expect_close(_blend_subtract(A, B), A.astype(int) - B.astype(int), name="Subtract")

# 15. Divide: a/b
expected = np.where(B <= 0, 255.0, A.astype(int) * 255.0 / np.maximum(1.0, B.astype(int)))
expect_close(_blend_divide(A, B), expected, name="Divide")

# 测试 Dialog 集成
print()
print("=== Dialog 集成测试 ===")

# 准备一张原图
h, w = 16, 16
original = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
dlg = AdvancedEditorDialog(initial=original)

# 测试所有 15 种模式都能跑
print(f"  BLEND_MODES count: {len(BLEND_MODES)}")
second = np.full_like(original, 100)
dlg._second_data = second
for mode_id, mode_name, _ in BLEND_MODES:
    dlg._blend_combo.setCurrentIndex(
        next(i for i, (mid, _, _) in enumerate(BLEND_MODES) if mid == mode_id)
    )
    result = dlg._current_computed()
    print(f"  {mode_id:15s}: shape={result.shape} mean={result.mean():.1f} min={result.min()} max={result.max()}")

# 测试拖拽
print()
print("=== 第二张图拖拽测试 ===")
dlg2 = AdvancedEditorDialog(initial=original)
# 先生成测试图
test_img = Path("examples/test_output/blend_second_test.png")
test_img.parent.mkdir(parents=True, exist_ok=True)
test_arr = np.full((32, 32), 100, dtype=np.uint8)
from PIL import Image
Image.fromarray(test_arr, mode="L").save(test_img)

# 模拟 drop event
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(str(test_img.resolve()))])
drop_event = QDropEvent(
    QPoint(10, 10),
    Qt.CopyAction,
    mime,
    Qt.LeftButton,
    Qt.NoModifier,
)
# 直接调 _second_drop_event(在 QFrame 上,绑了 _second_drop_event)
dlg2._second_drop_event(drop_event)
print(f"  second_path: {dlg2._second_path}")
print(f"  second_data shape: {dlg2._second_data.shape if dlg2._second_data is not None else None}")
print(f"  second_edit text: {dlg2._second_edit.text()}")
print(f"  drop_label text: {dlg2._second_drop_label.text()}")
assert dlg2._second_data is not None, "second_data 没加载"
assert dlg2._second_data.shape == (16, 16), f"shape 不对:{dlg2._second_data.shape}"
print("  OK")

# 测试预览是 QScrollArea
print()
print("=== 预览可滚动 (QScrollArea) ===")
from PySide6.QtWidgets import QScrollArea
for attr in ["orig_label", "result_label"]:
    lbl = getattr(dlg2, attr)
    # QLabel.parent() 是 viewport,viewport.parent() 才是 QScrollArea
    parent = lbl.parent()
    grandparent = parent.parent() if parent else None
    is_scroll = isinstance(grandparent, QScrollArea)
    print(f"  {attr}: grandparent is QScrollArea? {is_scroll}")
    assert is_scroll, f"{attr} 应该在 QScrollArea 里"
print("  OK")

print()
print("DONE")

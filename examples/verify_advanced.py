"""验证 AdvancedEditorDialog 的核心算法。"""
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.ui.advanced_editor import AdvancedEditorDialog

# 准备一张原图(简单梯度 0-255)
h, w = 16, 16
original = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
print(f"原图: shape={original.shape}, mean={original.mean():.1f}, min={original.min()}, max={original.max()}")

# 1) 测试亮度
print()
print("[1] 亮度 +50:")
dlg = AdvancedEditorDialog(initial=original)
dlg._bright_slider.setValue(50)
result = dlg._current_computed()
expected = np.clip(original.astype(int) + 50, 0, 255).astype(np.uint8)
print(f"  result mean: {result.mean():.1f} (期望 {expected.mean():.1f})")
assert np.array_equal(result, expected), "亮度 +50 错"
print("  OK")

# 2) 测试对比度
print()
print("[2] 对比度 1.5 (围绕 128):")
dlg2 = AdvancedEditorDialog(initial=original)
dlg2._contrast_slider.setValue(150)
result = dlg2._current_computed()
expected = np.clip((original.astype(float) - 128) * 1.5 + 128, 0, 255).astype(np.uint8)
print(f"  result[0,0] = {result[0,0]} (期望 {expected[0,0]})")
# 对比度用 float normalize,int8 round 后 max diff 可能为 1,用 atol=1 容差
assert np.allclose(result, expected, atol=1), f"对比度 1.5 错 (max diff={np.abs(result.astype(int) - expected.astype(int)).max()})"
print("  OK")

# 3) 测试伽马
print()
print("[3] 伽马 0.5:")
dlg3 = AdvancedEditorDialog(initial=original)
dlg3._gamma_slider.setValue(50)
result = dlg3._current_computed()
expected = np.clip(255 * np.power(original.astype(float) / 255, 0.5), 0, 255).astype(np.uint8)
print(f"  result[0,8] = {result[0,8]} (期望 {expected[0,8]})")
print(f"  result mean: {result.mean():.1f} (期望 {expected.mean():.1f})")
assert np.allclose(result, expected, atol=1), "伽马 0.5 错"
print("  OK")

# 4) 测试曲线 LUT(等价老版 (low=50, mid=180, high=255))
print()
print("[4] 曲线 LUT 提亮 (0,50)(180,180)(255,255):")
dlg4 = AdvancedEditorDialog(initial=original)
dlg4._curve.set_points([(0, 50), (180, 180), (255, 255)])
result = dlg4._current_computed()
# 用新曲线 LUT 算 expected
from src.ui.advanced_editor import _catmull_rom_lut
lut = _catmull_rom_lut([(0, 50), (180, 180), (255, 255)], 256)
expected = np.clip(lut, 0, 255).astype(np.uint8)[original]
print(f"  result[0,0] = {result[0,0]} (期望 {expected[0,0]})")
print(f"  result[0,8] = {result[0,8]} (期望 {expected[0,8]})")
print(f"  result[0,15] = {result[0,15]} (期望 {expected[0,15]})")
assert np.array_equal(result, expected), "3 点 LUT 错"
print("  OK")

# 5) 测试算术
print()
print("[5] 算术:add 第二张图 = 全 50:")
second = np.full_like(original, 50)
dlg5 = AdvancedEditorDialog(initial=original)
dlg5._second_data = second
dlg5._blend_combo.setCurrentIndex(dlg5._blend_combo.findData("add"))
result = dlg5._current_computed()
expected = np.clip(original.astype(int) + second.astype(int), 0, 255).astype(np.uint8)
print(f"  result[0,0] = {result[0,0]} (期望 {expected[0,0]})")
assert np.array_equal(result, expected), "add 错"
print("  OK")

print()
print("[6] 算术:sub 第二张图 = 全 50:")
dlg6 = AdvancedEditorDialog(initial=original)
dlg6._second_data = second
dlg6._blend_combo.setCurrentIndex(dlg6._blend_combo.findData("subtract"))
result = dlg6._current_computed()
expected = np.clip(original.astype(int) - second.astype(int), 0, 255).astype(np.uint8)
print(f"  result[0,0] = {result[0,0]} (期望 {expected[0,0]})")
assert np.array_equal(result, expected), "sub 错"
print("  OK")

print()
print("[7] 算术:mul 第二张图 = 全 50% (128):")
second = np.full_like(original, 128)  # 50% 灰度
dlg7 = AdvancedEditorDialog(initial=original)
dlg7._second_data = second
dlg7._blend_combo.setCurrentIndex(dlg7._blend_combo.findData("multiply"))
result = dlg7._current_computed()
# Multiply: a * b / 255
expected = np.clip(original.astype(float) * second.astype(float) / 255.0, 0, 255).astype(np.uint8)
print(f"  result[0,0] = {result[0,0]} (期望 {expected[0,0]})")
# 实现用 float32,测试用 float64,int8 cast 后可能有 1 的差
assert np.allclose(result, expected, atol=1), f"mul 错 (max diff={np.abs(result.astype(int) - expected.astype(int)).max()})"
print("  OK")

# 8) 组合:亮度 +50 + 提亮曲线
print()
print("[8] 组合:亮度 +30 + 提亮曲线(0,50)(180,180)(255,255):")
dlg8 = AdvancedEditorDialog(initial=original)
dlg8._bright_slider.setValue(30)
dlg8._curve.set_points([(0, 50), (180, 180), (255, 255)])
result = dlg8._current_computed()
# 预期:先亮度+30,再曲线 LUT
step1 = np.clip(original.astype(int) + 30, 0, 255).astype(np.uint8)
lut = _catmull_rom_lut([(0, 50), (180, 180), (255, 255)], 256)
expected = np.clip(lut, 0, 255).astype(np.uint8)[step1]
print(f"  result[0,0] = {result[0,0]} (期望 {expected[0,0]})")
print(f"  result[0,8] = {result[0,8]} (期望 {expected[0,8]})")
assert np.array_equal(result, expected), "组合错"
print("  OK")

# 9) 接受后 result_data 正确
print()
print("[9] accept 后 result_data 写入:")
dlg9 = AdvancedEditorDialog(initial=original)
dlg9._bright_slider.setValue(50)
dlg9.accept()
assert dlg9.result_data is not None
print(f"  result_data shape: {dlg9.result_data.shape}")
print(f"  result_data mean: {dlg9.result_data.mean():.1f} (期望 {(original.astype(int) + 50).mean():.1f})")
print("  OK")

print()
print("DONE — 全部通过")

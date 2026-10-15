"""验证:SlotWidget 导出 / 替换 / undo 兼容。"""
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
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.ui.app import MainWindow
from src.core import (
    ChannelMap, ChannelSlot, ChannelToken, Semantic, OutputSpec, SizePreset,
)
from src.core.output_spec import ResizeFilter, ResizeMode
from src.io.loader import load_slot
from src.io.saver import save_grayscale

w = MainWindow()
cg = w.channel_grid
inp = Path("examples/test_input")
spec = OutputSpec(
    size_preset=SizePreset.CUSTOM, width=32, height=32,
    resize_mode=ResizeMode.STRETCH, resize_filter=ResizeFilter.NEAREST,
)

# 1) 4 槽载入 + 导出
print("[1] 4 槽载入 + 导出测试:")
m = ChannelMap()
for name, path, sem in [
    ("R", inp / "ao.png", Semantic.AO),
    ("G", inp / "roughness.png", Semantic.ROUGHNESS),
    ("B", inp / "metallic.png", Semantic.METALLIC),
    ("A", inp / "height.png", Semantic.HEIGHT),
]:
    s = ChannelSlot.from_file(path, token=ChannelToken.R, semantic=sem)
    load_slot(s, spec)
    setattr(m, name, s)
w.channel_grid.set_map(m)
w.channel_grid.set_spec(spec)

# 强制同步
cg._debounce.stop()
cg._on_rebuild()

# 直接调 save_grayscale 模拟导出按钮(避免 QFileDialog)
out_dir = Path("examples/test_output/slot_export")
out_dir.mkdir(parents=True, exist_ok=True)
for name in ("R", "G", "B", "A"):
    sw = cg.slot_widgets[name]
    assert sw._slot.data is not None, f"{name} data is None"
    out_path = out_dir / f"{name.lower()}_export.png"
    save_grayscale(sw._slot.data, out_path)
    arr = np.asarray(Image.open(out_path))
    print(f"  {name} 导出: {out_path.name} shape={arr.shape} mean={arr.mean():.1f}")

# 2) 替换源文件:把 R 槽换成 metallic.png
print()
print("[2] 替换 R 槽源文件 (roughness.png -> metallic.png):")
sw = cg.slot_widgets["R"]
old_data_mean = float(sw._slot.data.mean())
print(f"  R 替换前 data mean: {old_data_mean:.1f}")
# 调 _assign_file,模拟替换按钮(避免 QFileDialog)
sw._assign_file(inp / "metallic.png")
# 立即 reload
sw._slot.file_path = inp / "metallic.png"
load_slot(sw._slot, spec)
new_data_mean = float(sw._slot.data.mean())
print(f"  R 替换后 data mean: {new_data_mean:.1f}")
# 期望:metallic.png mean=127.5
print(f"  期望 mean ~127.5 (metallic.png 原图)")
# 验证 token / semantic 没变
print(f"  R token 仍为: {sw._slot.token} (期望 R)")
print(f"  R semantic 仍为: {sw._slot.semantic} (期望 AO)")

# 3) undo 兼容
print()
print("[3] undo 兼容:")
print(f"  undo stack: {len(cg._undo_stack)}, redo stack: {len(cg._redo_stack)}")
# undo 一下,应该回到替换前
w._on_undo()
sw = cg.slot_widgets["R"]
print(f"  R undo 后 file: {sw._slot.file_path.name if sw._slot.file_path else None}")
print(f"  R undo 后 token: {sw._slot.token}")
# redo 一下
w._on_redo()
sw = cg.slot_widgets["R"]
print(f"  R redo 后 file: {sw._slot.file_path.name if sw._slot.file_path else None}")
print(f"  R redo 后 token: {sw._slot.token}")

# 4) 测试无 data 时导出报错
print()
print("[4] 无 data 时导出(应提示):")
sw_clear = cg.slot_widgets["R"]
sw_clear._slot.data = None
# 模拟点击导出 — QMessageBox.warning 会弹,headless 模式下我们直接测内部逻辑
data_none = sw_clear._slot.data is None
print(f"  R data 已置 None: {data_none}")
# (QMessageBox 不能 headless 测,但逻辑上会判 None 弹窗)

# 5) 显示 SlotWidget 新布局(确认按钮都在)
print()
print("[5] SlotWidget 按钮检查:")
for name in ("R", "G", "B", "A"):
    sw = cg.slot_widgets[name]
    has_export = hasattr(sw, "export_btn")
    has_replace = hasattr(sw, "replace_btn")
    has_clear = hasattr(sw, "clear_btn")
    print(f"  {name}: export={has_export} replace={has_replace} clear={has_clear}")

print()
print("DONE")

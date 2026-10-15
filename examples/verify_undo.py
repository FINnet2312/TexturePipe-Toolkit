"""验证 undo/redo 行为。"""
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.ui.app import MainWindow
from src.core import (
    ChannelMap, ChannelSlot, ChannelToken, Semantic, OutputSpec, SizePreset,
)
from src.core.output_spec import ResizeFilter, ResizeMode
from src.io.loader import load_slot
import numpy as np
from PIL import Image

w = MainWindow()
cg = w.channel_grid
inp = Path("examples/test_input")
spec = OutputSpec(
    size_preset=SizePreset.CUSTOM, width=64, height=64,
    resize_mode=ResizeMode.STRETCH, resize_filter=ResizeFilter.NEAREST,
)

# Step 1: 初始状态
print("[1] 初始:")
print(f"  undo stack: {len(cg._undo_stack)}, redo stack: {len(cg._redo_stack)}")
print(f"  can_undo={cg.can_undo()}, can_redo={cg.can_redo()}")
print(f"  R slot token: {cg.slot_widgets['R']._slot.token}")
print(f"  undo_action enabled: {w.undo_action.isEnabled()}, redo_action enabled: {w.redo_action.isEnabled()}")

# Step 2: 编辑 R 槽 token R → INV_R
print()
print("[2] 编辑 R token: R -> INV_R")
sw = cg.slot_widgets["R"]
# 找到 INV_R 的 index
idx = sw.token_combo.findData(ChannelToken.INV_R)
sw.token_combo.setCurrentIndex(idx)
# 立即 debounce
cg._debounce.stop()
cg._on_rebuild()
print(f"  R slot token: {cg.slot_widgets['R']._slot.token}")
print(f"  undo stack: {len(cg._undo_stack)}, redo stack: {len(cg._redo_stack)}")
print(f"  can_undo={cg.can_undo()}, can_redo={cg.can_redo()}")
print(f"  undo_action enabled: {w.undo_action.isEnabled()}")

# Step 3: 编辑 G 槽 token G → INV_G
print()
print("[3] 编辑 G token: G -> INV_G")
sw = cg.slot_widgets["G"]
idx = sw.token_combo.findData(ChannelToken.INV_G)
sw.token_combo.setCurrentIndex(idx)
cg._debounce.stop()
cg._on_rebuild()
print(f"  G slot token: {cg.slot_widgets['G']._slot.token}")
print(f"  undo stack: {len(cg._undo_stack)}")

# Step 4: undo → 应该回到 G=R 状态
print()
print("[4] undo (回到 G=R):")
w._on_undo()
print(f"  R token: {cg.slot_widgets['R']._slot.token} (期望 INV_R)")
print(f"  G token: {cg.slot_widgets['G']._slot.token} (期望 G)")
print(f"  undo stack: {len(cg._undo_stack)}, redo stack: {len(cg._redo_stack)}")
print(f"  R token_combo current: {cg.slot_widgets['R'].token_combo.currentText()}")
print(f"  G token_combo current: {cg.slot_widgets['G'].token_combo.currentText()}")

# Step 5: 再 undo → 回到 R=R 状态
print()
print("[5] undo (回到 R=R 初始):")
w._on_undo()
print(f"  R slot._slot.token: {cg.slot_widgets['R']._slot.token} (期望 R)")
print(f"  G slot._slot.token: {cg.slot_widgets['G']._slot.token} (期望 G)")
print(f"  R token_combo current: {cg.slot_widgets['R'].token_combo.currentText()}")
print(f"  G token_combo current: {cg.slot_widgets['G'].token_combo.currentText()}")
m = cg.get_map()
print(f"  _map.R.token: {m.R.token} (期望 R)")
print(f"  _map.G.token: {m.G.token} (期望 G)")
print(f"  undo stack: {len(cg._undo_stack)}, redo stack: {len(cg._redo_stack)}")

# Step 6: 再 undo → 栈空
print()
print("[6] undo (栈空):")
result = w._on_undo()
print(f"  _on_undo returned: {result} (期望 False)")
print(f"  can_undo={cg.can_undo()} (期望 False)")
print(f"  can_redo={cg.can_redo()} (期望 True)")

# Step 7: redo → 回到 R=INV_R
print()
print("[7] redo (回到 R=INV_R):")
w.redo_action.trigger()
print(f"  R token: {cg.slot_widgets['R']._slot.token} (期望 INV_R)")
print(f"  G token: {cg.slot_widgets['G']._slot.token} (期望 G)")

# Step 8: redo → 回到 G=INV_G
print()
print("[8] redo (回到 G=INV_G):")
w.redo_action.trigger()
print(f"  R token: {cg.slot_widgets['R']._slot.token} (期望 INV_R)")
print(f"  G token: {cg.slot_widgets['G']._slot.token} (期望 INV_G)")
print(f"  can_undo={cg.can_undo()} (期望 True)")
print(f"  can_redo={cg.can_redo()} (期望 False)")

# Step 9: 新编辑 → redo_stack 应清空
print()
print("[9] 新编辑 (R token → BLACK) → redo_stack 应清空:")
sw = cg.slot_widgets["R"]
idx = sw.token_combo.findData(ChannelToken.BLACK)
sw.token_combo.setCurrentIndex(idx)
cg._debounce.stop()
cg._on_rebuild()
print(f"  R token: {cg.slot_widgets['R']._slot.token} (期望 BLACK)")
print(f"  can_redo={cg.can_redo()} (期望 False)")

# Step 10: undo 上限(FIFO)
print()
print("[10] 栈上限测试 (FIFO):")
cg._undo_stack.clear()
cg._redo_stack.clear()
cg._max_undo = 5
for i in range(10):
    sw = cg.slot_widgets["R"]
    tokens = [ChannelToken.R, ChannelToken.G, ChannelToken.B, ChannelToken.A,
              ChannelToken.INV_R, ChannelToken.INV_G, ChannelToken.BLACK, ChannelToken.WHITE,
              ChannelToken.R, ChannelToken.G]
    idx = sw.token_combo.findData(tokens[i])
    sw.token_combo.setCurrentIndex(idx)
    cg._debounce.stop()
    cg._on_rebuild()
print(f"  10 次编辑后 undo stack: {len(cg._undo_stack)} (期望 5,即 max_undo 上限)")

print()
print("DONE")

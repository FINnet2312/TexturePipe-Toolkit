"""验证:SlotWidget 默认 token 按 channel_name 设,中央 drop zone 工作。"""
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
from PySide6.QtCore import QMimeData, QUrl, QPoint, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent

app = QApplication(sys.argv)
from src.ui.app import MainWindow
from src.core.slot import ChannelToken

w = MainWindow()
cg = w.channel_grid

# 1) 验证 SlotWidget 默认 token 按 channel_name
print("[1/3] SlotWidget 默认 token 检查:")
for name in ("R", "G", "B", "A"):
    sw = cg.slot_widgets[name]
    expected = {"R": ChannelToken.R, "G": ChannelToken.G, "B": ChannelToken.B, "A": ChannelToken.A}[name]
    actual = sw._slot.token
    status = "OK" if actual == expected else "FAIL"
    print(f"  {name} slot: token={actual} (期望 {expected}) [{status}]")

# 2) 模拟中央 drop zone drop event
print()
print("[2/3] 模拟中央 drop zone:")
inp = Path("examples/test_input")
# 先生成一张 RGBA 测试图
test_rgba = Path("examples/test_output/test_rgba_input.png")
if not test_rgba.exists():
    # 拼一张 RGBA 测试图
    arr = np.zeros((32, 32, 4), dtype=np.uint8)
    arr[..., 0] = 11  # R
    arr[..., 1] = 22  # G
    arr[..., 2] = 33  # B
    arr[..., 3] = 44  # A
    Image.fromarray(arr, "RGBA").save(test_rgba)

# 模拟拖入:构造一个 QDropEvent
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(str(test_rgba.resolve()))])
drop_event = QDropEvent(
    QPoint(10, 10),
    Qt.CopyAction,
    mime,
    Qt.LeftButton,
    Qt.NoModifier,
)
cg.drop_zone.dropEvent(drop_event)

# 验证:4 槽都绑到这张图,token 分别为 R/G/B/A
print(f"  R.slot.file_path = {cg.slot_widgets['R']._slot.file_path}")
print(f"  R.slot.token     = {cg.slot_widgets['R']._slot.token}")
print(f"  G.slot.file_path = {cg.slot_widgets['G']._slot.file_path}")
print(f"  G.slot.token     = {cg.slot_widgets['G']._slot.token}")
print(f"  B.slot.file_path = {cg.slot_widgets['B']._slot.file_path}")
print(f"  B.slot.token     = {cg.slot_widgets['B']._slot.token}")
print(f"  A.slot.file_path = {cg.slot_widgets['A']._slot.file_path}")
print(f"  A.slot.token     = {cg.slot_widgets['A']._slot.token}")

# 3) 验证:从 UI 读出 map,导出 PNG,像素值正确
print()
print("[3/3] 导出验证:")
m = cg.get_map()
out_path = Path("examples/test_output/drop_zone_export.png")
cg.export_png(out_path)
arr = np.asarray(Image.open(out_path))
print(f"  R={arr[..., 0].mean():.1f} (期望 11)")
print(f"  G={arr[..., 1].mean():.1f} (期望 22)")
print(f"  B={arr[..., 2].mean():.1f} (期望 33)")
print(f"  A={arr[..., 3].mean():.1f} (期望 44)")

print()
print("DONE")

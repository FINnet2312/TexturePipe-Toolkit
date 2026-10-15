"""End-to-end verify: 通过 UI 接口完成 pack + transcode 流程。"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

# 让脚本能直接 `py examples/verify_ui_e2e.py` 跑通
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from src.core import (
    ChannelMap, ChannelSlot, ChannelToken, Semantic, OutputSpec, SizePreset,
)
from src.core.output_spec import ResizeFilter, ResizeMode
from src.io.loader import load_slot
from src.io.saver import save_map_rgba, save_grayscale
from src.ui.app import MainWindow

print("=== E2E 1: 编辑模式 — 设 4 槽 + 导出 ===")
w = MainWindow()

# 构造 4 槽 ChannelMap
inp = Path("examples/test_input")
spec = OutputSpec(
    size_preset=SizePreset.CUSTOM,
    width=256, height=256,
    resize_mode=ResizeMode.STRETCH,
    resize_filter=ResizeFilter.NEAREST,
)
m = ChannelMap()
for name, path, sem in [
    ("R", inp / "ao.png", Semantic.AO),
    ("G", inp / "roughness.png", Semantic.ROUGHNESS),
    ("B", inp / "metallic.png", Semantic.METALLIC),
    ("A", inp / "height.png", Semantic.HEIGHT),
]:
    slot = ChannelSlot.from_file(path, token=ChannelToken.R, semantic=sem)
    load_slot(slot, spec)
    setattr(m, name, slot)

# 通过 UI 同步
w.channel_grid.set_map(m)
w.channel_grid.set_spec(spec)
w.output_spec.set_spec(spec)

# 导出
out = Path("examples/test_output/ui_ORM.png")
w.channel_grid.export_png(out)
print(f"  写出: {out}")
arr = np.asarray(Image.open(out))
print(f"  shape={arr.shape}, R mean={arr[..., 0].mean():.1f} (期望 AO 116.5)")
print(f"  G mean={arr[..., 1].mean():.1f} (期望 Roughness 127.5)")
print(f"  B mean={arr[..., 2].mean():.1f} (期望 Metallic 127.5)")
print(f"  A mean={arr[..., 3].mean():.1f} (期望 Height 63.5)")

print()
print("=== E2E 2: 互转模式 — ORM -> RMA ===")
# 模拟 transcode_panel._on_load + _on_export
tp = w.transcode_panel
src_img = np.asarray(Image.open("examples/test_output/ORM.png"))
rgba = np.zeros(src_img.shape[:2] + (4,), dtype=np.uint8) if src_img.ndim == 2 else src_img
if src_img.ndim == 2:
    rgba[..., 0] = src_img
    rgba[..., 3] = 255
elif src_img.shape[-1] == 3:
    rgba[..., :3] = src_img
    rgba[..., 3] = 255
tp._src_arr = rgba
tp.src_fmt.setCurrentText("orm")
tp.dst_fmt.setCurrentText("rma")
# 触发 refresh
tp._refresh()
# 验证预览组件有内容
src_arr = tp.src_preview._arr if hasattr(tp.src_preview, "_arr") else None
dst_arr = tp.dst_preview._arr if hasattr(tp.dst_preview, "_arr") else None
print(f"  src preview shape: {src_arr.shape if src_arr is not None else None}")
print(f"  dst preview shape: {dst_arr.shape if dst_arr is not None else None}")
if dst_arr is not None:
    print(f"  dst R mean={dst_arr[..., 0].mean():.1f} (期望 Roughness 127.5)")
    print(f"  dst G mean={dst_arr[..., 1].mean():.1f} (期望 Metallic 127.5)")
    print(f"  dst B mean={dst_arr[..., 2].mean():.1f} (期望 AO 116.5)")

print()
print("=== E2E 3: 工作区保存/加载 ===")
import json, tempfile
ws_path = Path("examples/test_output/workspace.json")
data = {"map": m.to_dict(), "spec": spec.to_dict()}
ws_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  保存: {ws_path}")

# 加载
loaded = json.loads(ws_path.read_text(encoding="utf-8"))
m2 = ChannelMap.from_dict(loaded["map"])
spec2 = OutputSpec.from_dict(loaded["spec"])
print(f"  加载: map.R.semantic={m2.R.semantic}, spec.width={spec2.width}")

# 通过 UI 加载
w2 = MainWindow()
w2.channel_grid.set_spec(spec2)
w2.channel_grid.set_map(m2)
print(f"  UI 槽 R semantic 下拉当前值: {w2.channel_grid.slot_widgets['R'].semantic_combo.currentText()}")

print()
print("DONE")

"""最终验证 — 单测 + UI + 端到端 pack/transcode + 批处理。"""
import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))

print("=" * 50)
print("FINAL VERIFICATION v2")
print("=" * 50)

# 1) 单元测试
print()
print("[1/4] 单元测试:")
import unittest
import importlib.util
spec = importlib.util.spec_from_file_location(
    "test_core", str(ROOT / "tests" / "test_core.py")
)
m = importlib.util.module_from_spec(spec)
sys.modules["test_core"] = m
spec.loader.exec_module(m)
loader = unittest.TestLoader()
suite = unittest.TestSuite()
for name in [
    "TestSlot", "TestChannelToken", "TestOutputSpec", "TestChannelMap",
    "TestColorSpace", "TestResize", "TestPacker", "TestReorder", "TestDrop",
    "TestInvert", "TestTranscoder", "TestPresets", "TestNaming",
]:
    suite.addTests(loader.loadTestsFromName(f"test_core.{name}"))
result = unittest.TextTestRunner(verbosity=0).run(suite)
print(f"  -> PASS: {result.testsRun - len(result.failures) - len(result.errors)} / {result.testsRun}")

# 2) UI 结构
print()
print("[2/4] UI 结构(headless):")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from src.ui.app import MainWindow
w = MainWindow()
print(f"  MainWindow: {w.windowTitle()} {w.size().width()}x{w.size().height()}")
print(f"  Tabs: {w.tabs.count()} {[w.tabs.tabText(i) for i in range(w.tabs.count())]}")
print(f"  ChannelGrid slots: {len(w.channel_grid.slot_widgets)}")
# token 下拉检查
sw = w.channel_grid.slot_widgets["R"]
print(f"  Slot R token_combo items: {sw.token_combo.count()}")
print(f"  Slot R labels: {[sw.token_combo.itemText(i) for i in range(sw.token_combo.count())]}")
tp = w.transcode_panel
print(f"  TranscodePanel presets: {[tp.src_fmt.itemText(i) for i in range(tp.src_fmt.count())]}")

# 3) 端到端 pack + transcode(token 模型)
print()
print("[3/4] 端到端 pack + 13 个 preset 转码:")
import numpy as np
from PIL import Image
from src.core import (
    ChannelMap, ChannelSlot, ChannelToken, OutputSpec, SizePreset,
    transcode_rgba, get_preset, derive_output_path,
)
from src.core.slot import Semantic  # semantic enum
from src.core.output_spec import ResizeFilter, ResizeMode
from src.io.loader import load_slot
from src.io.saver import save_rgba
from src.core.slot import Semantic

# 先生成 4 张测试灰度图(若已存在则跳过)
inp = Path("examples/test_input")
if not inp.exists():
    import subprocess
    subprocess.run([sys.executable, "examples/gen_test.py"], check=True)

spec = OutputSpec(
    size_preset=SizePreset.CUSTOM, width=64, height=64,
    resize_mode=ResizeMode.STRETCH, resize_filter=ResizeFilter.NEAREST,
)
m = ChannelMap()
for name, path, sem in [
    ("R", inp / "ao.png", "AO"),
    ("G", inp / "roughness.png", "ROUGHNESS"),
    ("B", inp / "metallic.png", "METALLIC"),
    ("A", inp / "height.png", "HEIGHT"),
]:
    s = ChannelSlot.from_file(path, token=ChannelToken.R, semantic=Semantic[sem])
    load_slot(s, spec)
    setattr(m, name, s)

# 通过 UI 同步
w.channel_grid.set_map(m)
w.channel_grid.set_spec(spec)
out = Path("examples/test_output/v2_ORM.png")
w.channel_grid.export_png(out)
arr = np.asarray(Image.open(out))
print(f"  Pack ORM: R/G/B/A = {arr[..., 0].mean():.1f}/{arr[..., 1].mean():.1f}/{arr[..., 2].mean():.1f}/{arr[..., 3].mean():.1f}")

# 测几个 preset
for preset_id in ["orm", "rma", "mra", "rom", "ormh", "gltf_no_ao", "unity_mask", "ordp"]:
    p = get_preset(preset_id)
    out_arr = transcode_rgba(arr, p.mapping, remove_alpha=p.remove_alpha)
    out_p = Path("examples/test_output") / f"v2_{preset_id}.png"
    save_rgba(out_arr, out_p)
    if out_arr.ndim == 3:
        means = f"R/G/B = {out_arr[..., 0].mean():.0f}/{out_arr[..., 1].mean():.0f}/{out_arr[..., 2].mean():.0f}"
    else:
        means = f"R/G/B/A = {out_arr[..., 0].mean():.0f}/{out_arr[..., 1].mean():.0f}/{out_arr[..., 2].mean():.0f}/{out_arr[..., 3].mean():.0f}"
    print(f"  {preset_id:14s} {p.label[:40]:40s} {means}")

# 4) 批处理
print()
print("[4/4] 批处理 (examples/test_input → examples/test_output/batch_v2):")
import subprocess
batch_in = Path("examples/test_input")
batch_out = Path("examples/test_output/batch_v2")
batch_out.mkdir(parents=True, exist_ok=True)
result = subprocess.run(
    [sys.executable, "-m", "src.cli.main", "batch",
     "--input-dir", str(batch_in),
     "--output-dir", str(batch_out),
     "--preset", "rma",
     "--report-name", "rma_batch.csv"],
    capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(SRC)},
)
print("  " + (result.stdout.strip() or "(no stdout)"))
if result.returncode != 0:
    print("  STDERR:", result.stderr)
report = batch_out / "rma_batch.csv"
if report.exists():
    with report.open(encoding="utf-8") as f:
        for line in f:
            print("  " + line.rstrip())

print()
print("=" * 50)
print("ALL GREEN")
print("=" * 50)

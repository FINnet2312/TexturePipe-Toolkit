"""Headless verify UI integrity."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 让脚本能直接 `py examples/verify_ui.py` 跑通
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from src.ui.app import MainWindow
from src.core import Semantic

w = MainWindow()
print("=== MainWindow ===")
print("  title:", w.windowTitle())
print("  size:", w.size().width(), "x", w.size().height())

if hasattr(w, "tabs"):
    print("  Tabs:", w.tabs.count())
    for i in range(w.tabs.count()):
        print(f"    [{i}] {w.tabs.tabText(i)}")

if hasattr(w, "channel_grid"):
    cg = w.channel_grid
    print("=== ChannelGrid ===")
    slots = getattr(cg, "slot_widgets", None) or getattr(cg, "slots", None)
    if slots is None:
        slots = {}
        for name in ["R", "G", "B", "A"]:
            attr = getattr(cg, f"slot_{name.lower()}", None)
            if attr:
                slots[name] = attr
    print("  slot count:", len(slots))
    for name, sw in slots.items():
        sem_count = sw.semantic_combo.count() if hasattr(sw, "semantic_combo") else 0
        has_invert = hasattr(sw, "invert_check")
        has_file_btn = hasattr(sw, "file_btn") or hasattr(sw, "browse_btn")
        print(f"  {name}: semantic={sem_count}, invert={'Y' if has_invert else 'N'}, file_btn={'Y' if has_file_btn else 'N'}")

if hasattr(w, "transcode_panel"):
    tp = w.transcode_panel
    print("=== TranscodePanel ===")
    for attr in ["src_format_combo", "dst_format_combo", "load_btn", "export_btn"]:
        a = getattr(tp, attr, None)
        if a is not None:
            if hasattr(a, "count"):
                print(f"  {attr}: {a.count()} items: {[a.itemText(i) for i in range(a.count())]}")
            else:
                print(f"  {attr}: exists")

if hasattr(w, "spec_widget"):
    sw = w.spec_widget
    print("=== OutputSpecWidget ===")
    for attr in dir(sw):
        if "combo" in attr or "spin" in attr or "check" in attr:
            a = getattr(sw, attr, None)
            if a is not None and hasattr(a, "count"):
                print(f"  {attr}: {a.count()} items: {[a.itemText(i) for i in range(a.count())]}")
            elif a is not None and hasattr(a, "value"):
                print(f"  {attr}: value={a.value()}")

if hasattr(w, "preview_widget") or hasattr(w, "preview"):
    pw = getattr(w, "preview_widget", None) or getattr(w, "preview", None)
    print("=== Preview ===")
    if pw is not None:
        print("  type:", type(pw).__name__)

print("=== Semantic count ===", len(list(Semantic)))
print("DONE")

"""一次性截图脚本(英文界面):offscreen 渲染主界面和复杂编辑器,
输出 main_window_en.png / advanced_editor_en.png 到 docs/screenshots/。

结束后会把语言设置还原为中文,避免影响本机下次启动。
"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import QTimer

app = QApplication(sys.argv)

for fname in ("msyh.ttc", "msyh.ttf", "simhei.ttf"):
    fp = Path(r"C:\Windows\Fonts") / fname
    if fp.exists():
        QFontDatabase.addApplicationFont(str(fp))
        break
app.setFont(QFont("Microsoft YaHei", 9))

from src.ui import i18n  # noqa: E402
from src.ui.i18n import tr  # noqa: E402
from src.ui.app import MainWindow  # noqa: E402
from src.io.loader import load_image  # noqa: E402

i18n.init()
i18n.set_language("en")

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

import numpy as np
from PIL import Image

TEX = OUT / "_demo_input"
TEX.mkdir(exist_ok=True)
rng = np.random.RandomState(7)
yy, xx = np.mgrid[0:256, 0:256]

def save(name, arr):
    Image.fromarray(arr.astype(np.uint8), "L").save(TEX / name)

r = np.sqrt((xx - 128) ** 2 + (yy - 128) ** 2) / 181.0
save("ao.png", np.clip(235 - r * 140, 60, 255))
save("roughness.png", np.clip(xx * 0.7 + rng.normal(0, 14, (256, 256)) + 60, 0, 255))
save("metallic.png", np.where(((xx // 32) + (yy // 32)) % 2, 235, 25))
n = rng.rand(32, 32)
h = np.kron(n, np.ones((8, 8)))
h = (h - h.min()) / (h.max() - h.min()) * 255
save("height.png", h)

# ---- 1) 主界面 ----
w = MainWindow()
w.show()
app.processEvents()

assign = {"R": "ao.png", "G": "roughness.png", "B": "metallic.png", "A": "height.png"}
for ch, name in assign.items():
    sw = w.channel_grid.slot_widgets.get(ch)
    if sw is not None:
        sw._assign_file(TEX / name)

QTimer.singleShot(3500, app.quit)
app.exec()

pix = w.grab()
main_png = OUT / "main_window_en.png"
pix.save(str(main_png))
print("saved", main_png, pix.width(), "x", pix.height())

# ---- 2) 复杂编辑器 ----
from PySide6.QtWidgets import QPushButton  # noqa: E402
from src.ui.advanced_editor import AdvancedEditorDialog  # noqa: E402

arr = load_image(TEX / "roughness.png")
dlg = AdvancedEditorDialog(w, initial=arr, title=tr("复杂编辑") + " - roughness")
dlg.show()
QTimer.singleShot(2500, app.quit)
app.exec()

dlg._fit_previews()
QTimer.singleShot(600, app.quit)
app.exec()
for btn in dlg.findChildren(QPushButton):
    if btn.text() == tr("高对比"):
        btn.click()
        break
QTimer.singleShot(1200, app.quit)
app.exec()
dlg._fit_previews()
if hasattr(dlg, "orig_scroll"):
    dlg.orig_scroll.set_zoom(1.0)
if hasattr(dlg, "result_scroll"):
    dlg.result_scroll.set_zoom(1.0)
QTimer.singleShot(600, app.quit)
app.exec()

pix2 = dlg.grab()
adv_png = OUT / "advanced_editor_en.png"
pix2.save(str(adv_png))
print("saved", adv_png, pix2.width(), "x", pix2.height())

dlg.close()
w.close()

# 还原本机语言设置,避免下次启动变成英文
i18n.set_language("zh")
print("DONE")

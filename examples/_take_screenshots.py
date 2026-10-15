"""一次性截图脚本:offscreen 渲染主界面和复杂编辑器,输出到 docs/screenshots/。"""
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

# offscreen 模式没有系统字体回退,手动注册微软雅黑保证中文渲染
for fname in ("msyh.ttc", "msyh.ttf", "simhei.ttf"):
    fp = Path(r"C:\Windows\Fonts") / fname
    if fp.exists():
        QFontDatabase.addApplicationFont(str(fp))
        break
app.setFont(QFont("Microsoft YaHei", 9))

from src.ui.app import MainWindow  # noqa: E402
from src.io.loader import load_image  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

# 生成有视觉内容的示例贴图(测试用图太小,截图里看不清)
import numpy as np
from PIL import Image

TEX = OUT / "_demo_input"
TEX.mkdir(exist_ok=True)
rng = np.random.RandomState(7)
yy, xx = np.mgrid[0:256, 0:256]

def save(name, arr):
    Image.fromarray(arr.astype(np.uint8), "L").save(TEX / name)

# AO:柔和暗角
r = np.sqrt((xx - 128) ** 2 + (yy - 128) ** 2) / 181.0
save("ao.png", np.clip(235 - r * 140, 60, 255))
# roughness:横向渐变 + 噪声
save("roughness.png", np.clip(xx * 0.7 + rng.normal(0, 14, (256, 256)) + 60, 0, 255))
# metallic:棋盘块
save("metallic.png", np.where(((xx // 32) + (yy // 32)) % 2, 235, 25))
# height:平滑噪声
n = rng.rand(32, 32)
h = np.kron(n, np.ones((8, 8)))
h = (h - h.min()) / (h.max() - h.min()) * 255
save("height.png", h)

# ---- 1) 主界面:加载 4 张通道图 ----
w = MainWindow()
w.show()
app.processEvents()

assign = {"R": "ao.png", "G": "roughness.png", "B": "metallic.png", "A": "height.png"}
for ch, name in assign.items():
    sw = w.channel_grid.slot_widgets.get(ch)
    if sw is not None:
        sw._assign_file(TEX / name)

# 图片加载/预览是异步的,跑事件循环等它完成
QTimer.singleShot(3500, app.quit)
app.exec()

pix = w.grab()
main_png = OUT / "main_window.png"
pix.save(str(main_png))
print("saved", main_png, pix.width(), "x", pix.height())

# ---- 2) 复杂编辑器:载入 roughness ----
from PySide6.QtWidgets import QPushButton  # noqa: E402
from src.ui.advanced_editor import AdvancedEditorDialog  # noqa: E402

arr = load_image(TEX / "roughness.png")
dlg = AdvancedEditorDialog(w, initial=arr, title="复杂编辑 - roughness")
dlg.show()
QTimer.singleShot(2500, app.quit)
app.exec()

# 布局稳定后重新适配预览,并应用一个曲线预设让"结果"与"原图"有对比
dlg._fit_previews()
QTimer.singleShot(600, app.quit)
app.exec()
for btn in dlg.findChildren(QPushButton):
    if btn.text() == "高对比":
        btn.click()
        break
QTimer.singleShot(1200, app.quit)
app.exec()
# 曲线刷新可能重置缩放,再适配一次
dlg._fit_previews()
# offscreen 下 fit 计算的视口偏小,手动固定到 100% 让内容清晰可见
if hasattr(dlg, "orig_scroll"):
    dlg.orig_scroll.set_zoom(1.0)
if hasattr(dlg, "result_scroll"):
    dlg.result_scroll.set_zoom(1.0)
QTimer.singleShot(600, app.quit)
app.exec()

pix2 = dlg.grab()
adv_png = OUT / "advanced_editor.png"
pix2.save(str(adv_png))
print("saved", adv_png, pix2.width(), "x", pix2.height())

dlg.close()
w.close()
print("DONE")

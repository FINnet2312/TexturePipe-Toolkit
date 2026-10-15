"""冒烟:验证 Skybox 插件 + 主窗口在中英文之间切换后文本正确更新。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from src.ui import i18n
from src.ui.i18n import tr
from src.ui.app import MainWindow
from src.ui.skybox_noise.main_window import NOISE_CUSTOM, SkyboxNoiseWidget

app = QApplication([])
i18n.init()

win = MainWindow()
skybox: SkyboxNoiseWidget = None
for i in range(win.tabs.count()):
    w = win.tabs.widget(i)
    if isinstance(w, SkyboxNoiseWidget):
        skybox = w
        break
assert skybox is not None, "未找到 SkyboxNoiseWidget"

# 中文态
assert skybox._grp_input.title() == "输入", skybox._grp_input.title()
assert skybox._lbl_noise.text() == "噪声类型:"
# 噪声类型 data 是功能键,显示文本是中文
assert skybox.cmb_noise.itemData(0) == "FBM (基础)"
assert skybox.cmb_noise.itemText(0) == "FBM (基础)"
assert skybox.cmb_noise.itemData(skybox.cmb_noise.count() - 1) == NOISE_CUSTOM

# 切英文
i18n.set_language("en")
assert skybox._grp_input.title() == "Input", skybox._grp_input.title()
assert skybox._grp_noise.title() == "Noise Parameters"
assert skybox._lbl_noise.text() == "Noise Type:"
assert skybox._lbl_proj.text() == "Projection:"
assert skybox.cmb_noise.itemText(0) == "FBM (Basic)", skybox.cmb_noise.itemText(0)
assert skybox.cmb_noise.itemData(0) == "FBM (基础)"  # 功能键不变
last = skybox.cmb_noise.count() - 1
assert skybox.cmb_noise.itemText(last) == "Custom (Node Graph)"
assert skybox.cmb_noise.itemData(last) == NOISE_CUSTOM
# 滑杆标签
scale_slider = skybox._param_widgets["noise_scale"]
assert scale_slider.label.text() == "Spatial Scale:", scale_slider.label.text()
# 按钮
btn_texts = [b.text() for b, _ in skybox._bar_buttons]
assert "📂 Open Image" in btn_texts, btn_texts
# 主窗口标题/菜单
assert win.windowTitle() == "Texture Channel Editor", win.windowTitle()
assert win.tabs.tabText(0) == "Edit Mode"

# 节点编辑器(构造时翻译)
from src.ui.skybox_noise.node_editor import NodeEditorDialog
dlg = NodeEditorDialog(skybox.node_graph, parent=skybox)
assert dlg.windowTitle() == "Node Graph Editor — Custom Noise"
lib_texts = [dlg.list_lib.item(i).text() for i in range(dlg.list_lib.count())]
assert "— Source —" in lib_texts, lib_texts
assert "FBM Noise" in lib_texts, lib_texts

# 切回中文:对话框是非模态长存对象,必须跟随刷新
i18n.set_language("zh")
assert dlg.windowTitle() == "节点图编辑器 — 自定义噪声", dlg.windowTitle()
lib_texts = [dlg.list_lib.item(i).text() for i in range(dlg.list_lib.count())]
assert "— 源 —" in lib_texts, lib_texts
assert "FBM 噪声" in lib_texts, lib_texts
tb_texts = [a.text() for a in dlg.findChildren(type(dlg._undo_act))]
assert "↩ 撤销" in tb_texts, tb_texts
dlg.close()

# 主窗口也已切回中文
assert skybox._grp_input.title() == "输入"
assert skybox.cmb_noise.itemText(0) == "FBM (基础)"
assert scale_slider.label.text() == "空间尺度:"
assert win.windowTitle() == "贴图通道编辑器"
assert win.tabs.tabText(0) == "编辑模式"

win.close()
print("OK — Skybox/主窗口/节点编辑器 中英双向切换验证通过")

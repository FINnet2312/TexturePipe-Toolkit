"""app — QMainWindow 主体。

组成:
- 菜单栏 / 工具栏 / 状态栏(自定义 StatusBanner)
- 中心:左侧 QTabWidget(编辑模式 + 互转模式),右侧 PreviewWidget
- 编辑模式 = ChannelGridWidget + OutputSpecWidget 垂直拼装
- 互转模式 = TranscodePanelWidget

信号连线(关键):
- OutputSpecWidget.spec_changed   → ChannelGridWidget.set_spec
- ChannelGridWidget.preview_requested → PreviewWidget.show_rgba
- ChannelGridWidget.map_changed    → PreviewWidget.show_map
- OutputSpecWidget.export_requested → ChannelGridWidget.export_png
- status_message(level, msg)  全局信号 → StatusBanner 显示(供各组件调用)
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.ui.channel_grid import ChannelGridWidget
from src.ui.i18n import LANGUAGES, i18n, set_language, tr
from src.ui.output_spec_widget import OutputSpecWidget
from src.ui.plugins import discover as discover_plugins
from src.ui.preview_widget import PreviewWidget
from src.ui.status_banner import StatusBanner
from src.ui.transcode_panel import TranscodePanelWidget
from src.core.plugin_manager import PluginManager
from src.io.saver import IMAGE_SAVE_FILTER


class MainWindow(QMainWindow):
    """主窗口。"""

    #: 全局状态消息信号(供各组件调用,level ∈ 'info'/'success'/'warning'/'error')
    status_message = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("贴图通道编辑器"))
        self.resize(1500, 820)

        # 启动期间产生的 plugin 提示(在 status bar 可用后再统一发)
        self._pending_plugin_warnings: list[str] = []

        self._build_central()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._wire_signals()

        # 启动后展示 plugin 加载结果
        for msg in self._pending_plugin_warnings:
            self.show_status("warning", msg)
        self._pending_plugin_warnings.clear()

        # 语言切换时重设本窗口及子控件文本
        i18n.language_changed.connect(self.retranslate)

    # -- UI 构建 -------------------------------------------------------
    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧 Tab
        self.tabs = QTabWidget()
        # --- 编辑模式 ---
        edit_tab = QWidget()
        edit_layout = QVBoxLayout(edit_tab)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(0)
        self.channel_grid = ChannelGridWidget()
        self.output_spec = OutputSpecWidget()
        edit_layout.addWidget(self.channel_grid, stretch=1)
        edit_layout.addWidget(self.output_spec)
        self.tabs.addTab(edit_tab, tr("编辑模式"))
        # --- 互转模式 ---
        self.transcode_panel = TranscodePanelWidget()
        self.tabs.addTab(self.transcode_panel, tr("互转模式"))

        # --- 插件 Tabs(动态发现,失败也不影响主程序)---
        self.plugin_manager: PluginManager = discover_plugins()
        for plugin in self.plugin_manager.all():
            ok, missing = plugin.is_available()
            if not ok:
                # 软依赖缺失,跳过这个 plugin(用状态横幅提示)
                self._pending_plugin_warnings.append(
                    tr("插件「{}」缺少依赖 {},已跳过").format(plugin.name, missing)
                )
                continue
            try:
                widget = plugin.factory()
                if plugin.position == "prepend":
                    self.tabs.insertTab(0, widget, plugin.name)
                else:
                    self.tabs.addTab(widget, plugin.name)
            except Exception as exc:  # noqa: BLE001
                self._pending_plugin_warnings.append(
                    tr("插件「{}」加载失败: {}").format(plugin.name, exc)
                )

        splitter.addWidget(self.tabs)

        # 右侧预览
        self.preview = PreviewWidget()
        splitter.addWidget(self.preview)

        # 比例:左侧占大头
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([900, 500])

        self.setCentralWidget(splitter)

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        # 文件
        self._file_menu = menubar.addMenu(tr("&文件"))
        self._act_save_ws = QAction(tr("保存工程…"), self)
        self._act_save_ws.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save_ws.triggered.connect(self.channel_grid._on_save_workspace)
        self._file_menu.addAction(self._act_save_ws)
        self._act_load_ws = QAction(tr("加载工程…"), self)
        self._act_load_ws.setShortcut(QKeySequence.StandardKey.Open)
        self._act_load_ws.triggered.connect(self.channel_grid._on_load_workspace)
        self._file_menu.addAction(self._act_load_ws)
        self._file_menu.addSeparator()
        self._act_export = QAction(tr("导出贴图…"), self)
        self._act_export.setShortcut(QKeySequence("Ctrl+E"))
        self._act_export.triggered.connect(self._menu_export)
        self._file_menu.addAction(self._act_export)
        self._file_menu.addSeparator()
        self._act_quit = QAction(tr("退出"), self)
        self._act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_quit.triggered.connect(self.close)
        self._file_menu.addAction(self._act_quit)
        # 编辑
        self._edit_menu = menubar.addMenu(tr("&编辑"))
        # Undo / Redo
        self.undo_action = QAction(tr("撤销"), self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)  # Ctrl+Z
        self.undo_action.triggered.connect(self._on_undo)
        self._edit_menu.addAction(self.undo_action)
        self.redo_action = QAction(tr("重做"), self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)  # Ctrl+Y / Ctrl+Shift+Z
        self.redo_action.triggered.connect(self._on_redo)
        self._edit_menu.addAction(self.redo_action)
        self._edit_menu.addSeparator()
        self._act_load_rgba = QAction(tr("加载 RGBA 并 unpack…"), self)
        self._act_load_rgba.triggered.connect(self.channel_grid._on_load_rgba)
        self._edit_menu.addAction(self._act_load_rgba)
        # 语言
        from src.ui.i18n import language as _cur_lang
        self._lang_menu = menubar.addMenu(tr("语言(&L)"))
        lang_group = QActionGroup(self)
        lang_group.setExclusive(True)
        self._lang_actions: dict[str, QAction] = {}
        for code, label in LANGUAGES.items():
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(code == _cur_lang())
            act.triggered.connect(lambda _checked=False, c=code: set_language(c))
            lang_group.addAction(act)
            self._lang_menu.addAction(act)
            self._lang_actions[code] = act
        # 帮助
        self._help_menu = menubar.addMenu(tr("&帮助"))
        self._act_about = QAction(tr("关于"), self)
        self._act_about.triggered.connect(self._show_about)
        self._help_menu.addAction(self._act_about)

    def _build_toolbar(self) -> None:
        self._toolbar = QToolBar(tr("主工具栏"), self)
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)
        self._tb_load_rgba = QAction(tr("加载 RGBA"), self)
        self._tb_load_rgba.triggered.connect(self.channel_grid._on_load_rgba)
        self._toolbar.addAction(self._tb_load_rgba)
        self._tb_save = QAction(tr("保存工程"), self)
        self._tb_save.triggered.connect(self.channel_grid._on_save_workspace)
        self._toolbar.addAction(self._tb_save)
        self._tb_load = QAction(tr("加载工程"), self)
        self._tb_load.triggered.connect(self.channel_grid._on_load_workspace)
        self._toolbar.addAction(self._tb_load)
        self._toolbar.addSeparator()
        self._tb_export = QAction(tr("导出贴图"), self)
        self._tb_export.triggered.connect(self._menu_export)
        self._toolbar.addAction(self._tb_export)

    def _build_statusbar(self) -> None:
        """状态栏:左侧永久消息(QStatusBar 文本) + 右侧彩色横幅(StatusBanner)。"""
        sb = QStatusBar()
        self.setStatusBar(sb)
        # 永久消息区(放左侧,显示当前文件 / 规格 / 缩放等次要信息)
        self._status_perm = sb
        sb.showMessage(tr("就绪"))
        # 彩色横幅(放右侧,显示操作反馈)
        self._status_banner = StatusBanner()
        sb.addPermanentWidget(self._status_banner)

    def show_status(self, level: str, msg: str, timeout: int = 0):
        """全局状态消息:转发到 StatusBanner。

        level: 'info' | 'success' | 'warning' | 'error'
        timeout: 毫秒,0 = 用级别默认
        """
        self.status_message.emit(level, msg)

    # -- 信号连线 ------------------------------------------------------
    def _wire_signals(self) -> None:
        # spec widget → channel grid
        self.output_spec.spec_changed.connect(self._on_spec_changed)
        self.channel_grid.spec_changed.connect(self._on_grid_spec_changed)
        # channel grid → preview
        self.channel_grid.preview_requested.connect(self.preview.show_rgba)
        self.channel_grid.map_changed.connect(self._on_map_changed)
        # undo/redo 状态变化 → 更新菜单 enabled
        self.channel_grid.undo_redo_changed.connect(self._update_undo_actions)
        # 初始同步
        self._update_undo_actions()
        # export
        self.output_spec.export_requested.connect(self._on_export_requested)
        # 各组件发 status_message → 状态栏
        self.channel_grid.status_message.connect(self._on_status_message)
        self.transcode_panel.status_message.connect(self._on_status_message)
        self.output_spec.status_message.connect(self._on_status_message)
        # 自身 status_message → banner(避免回环)
        self.status_message.connect(self._status_banner.show_message)

    def _on_status_message(self, level: str, msg: str):
        """子组件发的状态消息 → 横幅。"""
        self._status_banner.show_message(level, msg)

    def _on_undo(self) -> None:
        if not self.channel_grid.undo():
            self.statusBar().showMessage(tr("没有可撤销的操作"), 2000)

    def _on_redo(self) -> None:
        if not self.channel_grid.redo():
            self.statusBar().showMessage(tr("没有可重做的操作"), 2000)

    def _update_undo_actions(self) -> None:
        self.undo_action.setEnabled(self.channel_grid.can_undo())
        self.redo_action.setEnabled(self.channel_grid.can_redo())

    def _on_spec_changed(self) -> None:
        spec = self.output_spec.get_spec()
        self.channel_grid.set_spec(spec)
        w, h = spec.effective_size()
        self.statusBar().showMessage(
            tr("输出规格: {}×{}, preset={}").format(w, h, spec.size_preset.value)
        )

    def _on_grid_spec_changed(self) -> None:
        """导入、工作区加载、undo/redo 后把 Grid 规格反向同步到底部控件。"""
        spec = self.channel_grid.get_spec()
        if self.output_spec.get_spec() != spec:
            self.output_spec.set_spec(spec, emit=False)
        w, h = spec.effective_size()
        self.statusBar().showMessage(
            tr("输出规格: {}×{}, preset={}").format(w, h, spec.size_preset.value)
        )

    def _on_map_changed(self) -> None:
        # 同步 preview 的标题(semantic / display_name)
        self.preview.show_map(self.channel_grid.get_map())

    def _on_export_requested(self, path: str) -> None:
        try:
            self.channel_grid.export_png(Path(path))
        except Exception as exc:  # noqa: BLE001
            self.show_status("error", tr("导出失败 ({}): {}").format(Path(path).name, exc))
            return
        self.show_status("success", tr("已导出: {}").format(path))

    def _menu_export(self) -> None:
        """菜单 / 工具栏的导出:用 OutputSpec 里已填的路径,或临时问。"""
        p = self.output_spec.get_export_path()
        if p is None:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("选择导出路径"), "output.png", IMAGE_SAVE_FILTER
            )
            if not path:
                return
            p = Path(path)
            self.output_spec.set_export_path(p)
        self._on_export_requested(str(p))

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            tr("关于"),
            tr(
                "贴图通道编辑器\n\n"
                "MVP:4 槽 R/G/B/A 编辑 + 实时预览 + 格式互转。\n"
                "core 算法见 src/core/,UI 见 src/ui/。"
            ),
        )

    # -- 语言切换 ------------------------------------------------------
    def retranslate(self) -> None:
        """语言切换后重设本窗口及子控件的文本。"""
        self.setWindowTitle(tr("贴图通道编辑器"))
        # Tab 标题:前两个是内置模式,其余为插件(插件名不翻译)
        self.tabs.setTabText(0, tr("编辑模式"))
        self.tabs.setTabText(1, tr("互转模式"))
        # 菜单
        self._file_menu.setTitle(tr("&文件"))
        self._edit_menu.setTitle(tr("&编辑"))
        self._help_menu.setTitle(tr("&帮助"))
        self._lang_menu.setTitle(tr("语言(&L)"))
        self._act_save_ws.setText(tr("保存工程…"))
        self._act_load_ws.setText(tr("加载工程…"))
        self._act_export.setText(tr("导出贴图…"))
        self._act_quit.setText(tr("退出"))
        self.undo_action.setText(tr("撤销"))
        self.redo_action.setText(tr("重做"))
        self._act_load_rgba.setText(tr("加载 RGBA 并 unpack…"))
        self._act_about.setText(tr("关于"))
        # 工具栏
        self._toolbar.setWindowTitle(tr("主工具栏"))
        self._tb_load_rgba.setText(tr("加载 RGBA"))
        self._tb_save.setText(tr("保存工程"))
        self._tb_load.setText(tr("加载工程"))
        self._tb_export.setText(tr("导出贴图"))
        # 子控件(实现了 retranslate 的)
        for child in (
            self.channel_grid,
            self.output_spec,
            self.preview,
            self.transcode_panel,
        ):
            child_retranslate = getattr(child, "retranslate", None)
            if callable(child_retranslate):
                child_retranslate()
        # 插件 Tab(如 Skybox Noise 实现了 retranslate)
        for index in range(2, self.tabs.count()):
            plugin_widget = self.tabs.widget(index)
            widget_retranslate = getattr(plugin_widget, "retranslate", None)
            if callable(widget_retranslate):
                widget_retranslate()

    def closeEvent(self, event):  # noqa: N802
        """关闭前刷新工程恢复快照，避免 debounce 窗口内的操作丢失。"""
        self.channel_grid.flush_pending_autosave()
        super().closeEvent(event)

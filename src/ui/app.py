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
from PySide6.QtGui import QAction, QKeySequence
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
        self.setWindowTitle("贴图通道编辑器")
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
        self.tabs.addTab(edit_tab, "编辑模式")
        # --- 互转模式 ---
        self.transcode_panel = TranscodePanelWidget()
        self.tabs.addTab(self.transcode_panel, "互转模式")

        # --- 插件 Tabs(动态发现,失败也不影响主程序)---
        self.plugin_manager: PluginManager = discover_plugins()
        for plugin in self.plugin_manager.all():
            ok, missing = plugin.is_available()
            if not ok:
                # 软依赖缺失,跳过这个 plugin(用状态横幅提示)
                self._pending_plugin_warnings.append(
                    f"插件「{plugin.name}」缺少依赖 {missing},已跳过"
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
                    f"插件「{plugin.name}」加载失败: {exc}"
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
        file_menu = menubar.addMenu("&文件")
        act_save_ws = QAction("保存工程…", self)
        act_save_ws.setShortcut(QKeySequence.StandardKey.Save)
        act_save_ws.triggered.connect(self.channel_grid._on_save_workspace)
        file_menu.addAction(act_save_ws)
        act_load_ws = QAction("加载工程…", self)
        act_load_ws.setShortcut(QKeySequence.StandardKey.Open)
        act_load_ws.triggered.connect(self.channel_grid._on_load_workspace)
        file_menu.addAction(act_load_ws)
        file_menu.addSeparator()
        act_export = QAction("导出贴图…", self)
        act_export.setShortcut(QKeySequence("Ctrl+E"))
        act_export.triggered.connect(self._menu_export)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)
        # 编辑
        edit_menu = menubar.addMenu("&编辑")
        # Undo / Redo
        self.undo_action = QAction("撤销", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)  # Ctrl+Z
        self.undo_action.triggered.connect(self._on_undo)
        edit_menu.addAction(self.undo_action)
        self.redo_action = QAction("重做", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)  # Ctrl+Y / Ctrl+Shift+Z
        self.redo_action.triggered.connect(self._on_redo)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        act_load_rgba = QAction("加载 RGBA 并 unpack…", self)
        act_load_rgba.triggered.connect(self.channel_grid._on_load_rgba)
        edit_menu.addAction(act_load_rgba)
        # 帮助
        help_menu = menubar.addMenu("&帮助")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("主工具栏", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        act_load_rgba = QAction("加载 RGBA", self)
        act_load_rgba.triggered.connect(self.channel_grid._on_load_rgba)
        tb.addAction(act_load_rgba)
        act_save = QAction("保存工程", self)
        act_save.triggered.connect(self.channel_grid._on_save_workspace)
        tb.addAction(act_save)
        act_load = QAction("加载工程", self)
        act_load.triggered.connect(self.channel_grid._on_load_workspace)
        tb.addAction(act_load)
        tb.addSeparator()
        act_export = QAction("导出贴图", self)
        act_export.triggered.connect(self._menu_export)
        tb.addAction(act_export)

    def _build_statusbar(self) -> None:
        """状态栏:左侧永久消息(QStatusBar 文本) + 右侧彩色横幅(StatusBanner)。"""
        sb = QStatusBar()
        self.setStatusBar(sb)
        # 永久消息区(放左侧,显示当前文件 / 规格 / 缩放等次要信息)
        self._status_perm = sb
        sb.showMessage("就绪")
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
            self.statusBar().showMessage("没有可撤销的操作", 2000)

    def _on_redo(self) -> None:
        if not self.channel_grid.redo():
            self.statusBar().showMessage("没有可重做的操作", 2000)

    def _update_undo_actions(self) -> None:
        self.undo_action.setEnabled(self.channel_grid.can_undo())
        self.redo_action.setEnabled(self.channel_grid.can_redo())

    def _on_spec_changed(self) -> None:
        spec = self.output_spec.get_spec()
        self.channel_grid.set_spec(spec)
        w, h = spec.effective_size()
        self.statusBar().showMessage(f"输出规格: {w}×{h}, preset={spec.size_preset.value}")

    def _on_grid_spec_changed(self) -> None:
        """导入、工作区加载、undo/redo 后把 Grid 规格反向同步到底部控件。"""
        spec = self.channel_grid.get_spec()
        if self.output_spec.get_spec() != spec:
            self.output_spec.set_spec(spec, emit=False)
        w, h = spec.effective_size()
        self.statusBar().showMessage(f"输出规格: {w}×{h}, preset={spec.size_preset.value}")

    def _on_map_changed(self) -> None:
        # 同步 preview 的标题(semantic / display_name)
        self.preview.show_map(self.channel_grid.get_map())

    def _on_export_requested(self, path: str) -> None:
        try:
            self.channel_grid.export_png(Path(path))
        except Exception as exc:  # noqa: BLE001
            self.show_status("error", f"导出失败 ({Path(path).name}): {exc}")
            return
        self.show_status("success", f"已导出: {path}")

    def _menu_export(self) -> None:
        """菜单 / 工具栏的导出:用 OutputSpec 里已填的路径,或临时问。"""
        p = self.output_spec.get_export_path()
        if p is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "选择导出路径", "output.png", IMAGE_SAVE_FILTER
            )
            if not path:
                return
            p = Path(path)
            self.output_spec.set_export_path(p)
        self._on_export_requested(str(p))

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于",
            "贴图通道编辑器\n\n"
            "MVP:4 槽 R/G/B/A 编辑 + 实时预览 + 格式互转。\n"
            "core 算法见 src/core/,UI 见 src/ui/。",
        )

    def closeEvent(self, event):  # noqa: N802
        """关闭前刷新工程恢复快照，避免 debounce 窗口内的操作丢失。"""
        self.channel_grid.flush_pending_autosave()
        super().closeEvent(event)

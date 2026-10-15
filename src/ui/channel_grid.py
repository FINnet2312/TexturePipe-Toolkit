"""channel_grid — 4 槽(R/G/B/A)编辑器主面板。

职责:
- 横排 4 个 `SlotWidget`
- 任何编辑后,通过 QTimer debounce(200ms)重打包并通知外部刷新预览
- 提供工作区(整套 ChannelMap + OutputSpec)保存 / 加载
- 提供 "加载 RGBA 并按源格式 unpack" 的入口
- 暴露 `get_map() / set_map(m) / get_output_spec() / set_output_spec(spec)`
  以及信号 `preview_requested` 供外层预览组件订阅

为什么这里就重打包?
- 编辑后重打包 numpy 是 O(H*W) 的轻操作,2K 大约几毫秒,无需异步
- 把 pack 集中在 grid 里,避免每个上层都要重复触发
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.map import ChannelMap
from src.core.output_spec import OutputSpec
from src.core.file_cache import FileCache
from src.core.packer import pack_rgba
from src.core.pixels import full_scale
from src.core.presets import PRESETS, PRESET_BY_ID, get_preset
from src.core.slot import ChannelSlot, ChannelToken, ColorSpace, Semantic, SourceType
from src.io.loader import IMAGE_OPEN_FILTER, SUPPORTED_IMAGE_EXTS, load_image, load_slot
from src.io.saver import save_map_rgba
from src.io.workspace import (
    load_recovery_snapshot,
    load_workspace,
    recovery_snapshot_available,
    save_project_directory,
    save_recovery_snapshot,
)
from src.ui.slot_widget import SlotWidget
from src.ui.i18n import i18n, tr

from PySide6.QtWidgets import QCheckBox

_DEBOUNCE_MS = 200

# UI 上"加载 RGBA → 自动 unpack"用的下拉选项(走 semantic 解析,
# 所以仍按老格式给 4 语义)。互转模式用 PRESETS 全集。
UNPACK_FORMATS: dict[str, list[Semantic]] = {
    "ORM": [Semantic.AO, Semantic.ROUGHNESS, Semantic.METALLIC, Semantic.EMPTY],
    "RMA": [Semantic.ROUGHNESS, Semantic.METALLIC, Semantic.AO, Semantic.EMPTY],
    "MRA": [Semantic.METALLIC, Semantic.ROUGHNESS, Semantic.AO, Semantic.EMPTY],
    "ROM": [Semantic.ROUGHNESS, Semantic.AO, Semantic.METALLIC, Semantic.EMPTY],
    "ORMH": [Semantic.AO, Semantic.ROUGHNESS, Semantic.METALLIC, Semantic.HEIGHT],
    "RMAH": [Semantic.ROUGHNESS, Semantic.METALLIC, Semantic.AO, Semantic.HEIGHT],
    "GLTF": [Semantic.AO, Semantic.ROUGHNESS, Semantic.METALLIC, Semantic.EMPTY],
    "EMPTY": [Semantic.EMPTY, Semantic.EMPTY, Semantic.EMPTY, Semantic.EMPTY],
}

# 向后兼容(原 NAMED_FORMATS 引用处会报 AttributeError,改名)
NAMED_FORMATS = UNPACK_FORMATS  # legacy alias


class ChannelGridWidget(QWidget):
    """4 槽通道编辑器。"""

    #: debounce 结束后发出,通知预览组件刷新(参数:打包好的 H×W×4 数组)。
    preview_requested = Signal(np.ndarray)
    #: 输出规格发生改变(用于上层同步 spec widget)。
    spec_changed = Signal()
    #: 当前 map 发生改变(任意编辑后)。
    map_changed = Signal()
    #: undo/redo 栈变化(上层可据此更新菜单 enabled 状态)。
    undo_redo_changed = Signal()
    #: 状态消息(供上层状态栏显示)
    status_message = Signal(str, str)  # (level, msg)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._map = ChannelMap()
        self._spec = OutputSpec()
        self._suspend = False
        # 区分"用户编辑"vs"undo/redo 触发的 _on_rebuild"
        # 后者不应该清 redo 栈
        self._in_undo_redo = False
        # 中央 drop zone 的 RGBA 通道勾选(默认全选):未勾选的通道视为空(0/empty)
        self._rgba_mask = {"R": True, "G": True, "B": True, "A": True}
        self._workspace_dir: Path | None = None
        self._loading_workspace = False

        # Undo/Redo 栈:存 ChannelMap + OutputSpec 的 dict(不含像素)
        # 每次 _on_rebuild 完成后,如果状态变了 → 入 undo 栈
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._max_undo = 50
        # FILE 槽加载缓存:避免重复读盘 + resize(P0-2 性能优化)
        self._file_cache = FileCache(max_size=64)
        self._last_snapshot: dict = self._snapshot()

        self._build_ui()
        self._wire_signals()
        i18n.language_changed.connect(self.retranslate)

        # debounce timer
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._on_rebuild)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1500)
        self._autosave_timer.timeout.connect(self._write_autosave)

    # -- UI 构建 --------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 顶部操作行
        top = QHBoxLayout()
        self._unpack_label = QLabel(tr("载入 RGBA → 自动 unpack:"))
        top.addWidget(self._unpack_label)
        self.unpack_combo = QComboBox()
        for name in UNPACK_FORMATS:
            self.unpack_combo.addItem(name)
        top.addWidget(self.unpack_combo)
        self.unpack_btn = QPushButton(tr("加载 RGBA…"))
        top.addWidget(self.unpack_btn)
        top.addSpacing(20)
        self.save_workspace_btn = QPushButton(tr("保存工程"))
        top.addWidget(self.save_workspace_btn)
        self.load_workspace_btn = QPushButton(tr("加载工程"))
        top.addWidget(self.load_workspace_btn)
        top.addSpacing(20)
        # 导入后先编辑(打开 advanced editor 对原图调色 / 调明暗后,再按 R/G/B/A 拆)
        self.edit_before_import_check = QCheckBox(tr("导入后先编辑"))
        self.edit_before_import_check.setToolTip(
            tr("导入图片后,先弹复杂编辑窗口(可做 PS 风格调整 / 混合 / 曲线 / 缩放 pan),\n应用后再按 R/G/B/A 位置拆到 4 槽")
        )
        top.addWidget(self.edit_before_import_check)
        top.addStretch()
        root.addLayout(top)

        # 中央 drop zone — 拖一张 RGBA 图到此处,4 槽自动按位置取 R/G/B/A 通道
        from PySide6.QtWidgets import QFrame
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("ChannelGridDropZone")
        self.drop_zone.setFrameShape(QFrame.Shape.StyledPanel)
        self.drop_zone.setMinimumHeight(56)
        self.drop_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop_zone.setStyleSheet(
            "QFrame#ChannelGridDropZone { background:#1a1a1a; border:2px dashed #555; border-radius:6px; }"
            "QFrame#ChannelGridDropZone:hover { border-color:#0a84ff; }"
        )
        self.drop_zone.setAcceptDrops(True)
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(8, 4, 8, 4)
        self.drop_label = QLabel(tr("📥  拖一张 RGBA 贴图到这里,或点框体 / 「加载 RGBA…」选图 — 自动按 R/G/B/A 位置展开到 4 槽"))
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("color:#888;")
        drop_layout.addWidget(self.drop_label)
        root.addWidget(self.drop_zone)

        # RGBA 通道勾选(在 drop zone 下方一行):只把勾选的通道进内存
        rgba_row = QHBoxLayout()
        self._rgba_label = QLabel(tr("源 RGBA 通道(未勾选=不导入,视为空):"))
        rgba_row.addWidget(self._rgba_label)
        self._rgba_checks: dict[str, QCheckBox] = {}
        for ch in ("R", "G", "B", "A"):
            cb = QCheckBox(ch)
            cb.setChecked(True)
            cb.toggled.connect(self._on_rgba_toggled)
            self._rgba_checks[ch] = cb
            rgba_row.addWidget(cb)
        rgba_row.addStretch()
        root.addLayout(rgba_row)
        # drop zone 自身的事件
        self.drop_zone.dragEnterEvent = self._drop_zone_enter
        self.drop_zone.dragLeaveEvent = self._drop_zone_leave
        self.drop_zone.dropEvent = self._drop_zone_drop
        # 点击框体 = 加载 RGBA
        self.drop_zone.mousePressEvent = lambda ev: (
            self._on_load_rgba() if ev.button() == Qt.MouseButton.LeftButton else None
        )

        # 4 槽列
        slots_row = QHBoxLayout()
        slots_row.setSpacing(6)
        self.slot_widgets: dict[str, SlotWidget] = {}
        for name in ("R", "G", "B", "A"):
            sw = SlotWidget(name)
            sw.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.slot_widgets[name] = sw
            slots_row.addWidget(sw)
        root.addLayout(slots_row)

    def _wire_signals(self) -> None:
        for sw in self.slot_widgets.values():
            sw.edited.connect(self._on_slot_edited)
            # 子组件状态消息 → 转发到 channel_grid 自己的 status_message
            sw.status_message.connect(self.status_message)
        self.unpack_btn.clicked.connect(self._on_load_rgba)
        self.save_workspace_btn.clicked.connect(self._on_save_workspace)
        self.load_workspace_btn.clicked.connect(self._on_load_workspace)

    # -- 公开接口 -------------------------------------------------------
    def get_map(self) -> ChannelMap:
        """读出当前 ChannelMap(把 UI 改动写回,触发一次 load_slot)。"""
        for name in ("R", "G", "B", "A"):
            sw = self.slot_widgets[name]
            new = sw.get_slot()
            old = self._map.slot(name)
            # 保留 data/source_data(由 reload 重新生成)
            new.data = old.data
            new.source_data = old.source_data
            setattr(self._map, name, new)
        return self._map

    def set_map(self, m: ChannelMap, new_baseline: bool = True) -> None:
        """从外部把 ChannelMap 同步进 UI(不触发重打包,触发预览刷新一次)。

        Args:
            m: 要注入的 map
            new_baseline: True = 全新基线(工作区加载),清 undo/redo
                          False = 增量更新(导入图,RGBA 拆槽),保留 undo/redo
                                  让用户能 undo 回"导入前"
        """
        was_suspended = self._suspend
        self._suspend = True
        try:
            self._map = m
            for name, slot in m.slots():
                self.slot_widgets[name].set_slot(slot)
        finally:
            self._suspend = was_suspended
        # 立即触发一次重打包 → 预览
        if not self._suspend:
            self._on_rebuild()
        self.map_changed.emit()
        if new_baseline:
            # 外部注入的 map 视为"新基线",清空 undo/redo(避免回滚到不相关的旧状态)
            self.reset_history()
        # new_baseline=False:保留 undo/redo,用户可以 Ctrl+Z 回"导入前"

    def get_spec(self) -> OutputSpec:
        return self._spec

    def set_spec(self, spec: OutputSpec) -> None:
        self._spec = spec
        self.spec_changed.emit()
        # 尺寸变了,需要重打包
        self._schedule_rebuild()

    # -- 编辑回调 -------------------------------------------------------
    def _on_slot_edited(self) -> None:
        if self._suspend:
            return
        # 把 UI 改动同步到 _map(供后续 reload 拿到正确 file_path / invert 等)
        for name in ("R", "G", "B", "A"):
            sw = self.slot_widgets[name]
            new = sw.get_slot()
            old = self._map.slot(name)
            new.data = old.data
            new.source_data = old.source_data
            setattr(self._map, name, new)
        self.map_changed.emit()
        self._schedule_rebuild()

    def _schedule_rebuild(self) -> None:
        """启动(或重置)debounce,200ms 后真正重打包。"""
        self._debounce.start()

    def _on_rebuild(self) -> None:
        """debounce 结束:对每个 FILE 槽 reload,更新缩略图,发出预览信号。"""
        if self._suspend:
            return
        spec = self._spec
        # 拿当前最新的 UI 状态
        self.get_map()
        for name in ("R", "G", "B", "A"):
            slot = self._map.slot(name)
            try:
                load_slot(slot, spec, file_cache=self._file_cache)
            except Exception as exc:  # noqa: BLE001
                # 单个槽加载失败:让上层看到(走 status_message 提示)
                slot.data = None
                slot.source_data = None
                self._last_error = tr("槽 {} 加载失败: {}").format(name, exc)
            # 缩略图更新
            self.slot_widgets[name].set_thumbnail(slot.data)
        # 打包 → 预览
        try:
            arr = pack_rgba(self._map)
        except ValueError:
            # 全空:发一个空数组(预览组件按空白处理)
            arr = np.zeros((64, 64, 4), dtype=np.uint8)
        self.preview_requested.emit(arr)
        err = getattr(self, "_last_error", None)
        if err:
            self.status_message.emit("warning", err)
            self._last_error = None

        # undo/redo 区分:
        # - undo/redo 触发的 _on_rebuild:只更新 _last(不要清 redo)
        # - 用户编辑触发的 _on_rebuild:推 undo,清 redo
        if self._in_undo_redo:
            self._last_snapshot = self._snapshot()
        else:
            self._push_undo_if_changed()
        if self._workspace_dir is not None and not self._loading_workspace:
            self._autosave_timer.start()

    # -- Undo / Redo ---------------------------------------------------
    def _snapshot(self) -> dict:
        """捕获可撤销状态。

        FILE/SOLID 可从配置重建;EXTRACTED 是复杂编辑产物,需保留母版数组引用。
        数组按替换而非原地修改,因此历史项可安全共享引用,避免 4K/8K 多次复制。
        """
        map_data = self._map.to_dict()
        spec_data = self._spec.to_dict()
        pixels: dict[str, np.ndarray] = {}
        digests: dict[str, str] = {}
        for name, slot in self._map.slots():
            if slot.source_type is not SourceType.EXTRACTED:
                continue
            arr = slot.source_data if slot.source_data is not None else slot.data
            if arr is None:
                continue
            contiguous = np.ascontiguousarray(arr)
            pixels[name] = contiguous
            digests[name] = hashlib.blake2b(
                contiguous.view(np.uint8), digest_size=16,
            ).hexdigest()
        key = json.dumps(
            {"map": map_data, "spec": spec_data, "pixels": digests},
            ensure_ascii=True, sort_keys=True,
        )
        return {
            "map": map_data,
            "spec": spec_data,
            "_pixel_data": pixels,
            "_key": key,
        }

    def _push_undo_if_changed(self) -> None:
        """如果当前状态跟上次的 snapshot 不同,把旧状态压入 undo 栈,清 redo。

        注意:这个方法只应该被"用户编辑"触发的 _on_rebuild 调用。
        undo/redo 自己管自己的栈,不走这里。
        """
        cur = self._snapshot()
        if cur["_key"] == self._last_snapshot["_key"]:
            return
        self._undo_stack.append(self._last_snapshot)
        # 栈满:FIFO 丢最早的
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        # 新编辑 → 打断 redo 链
        self._redo_stack.clear()
        self._last_snapshot = cur
        self.undo_redo_changed.emit()

    def _restore_snapshot(self, snap: dict) -> None:
        """把 ChannelMap + OutputSpec 还原到给定 snapshot。"""
        self._suspend = True
        self._in_undo_redo = True
        try:
            self._map = ChannelMap.from_dict(snap["map"])
            for name, arr in snap.get("_pixel_data", {}).items():
                slot = self._map.slot(name)
                slot.source_data = np.asarray(arr).copy()
                slot.data = slot.source_data.copy()
            for name, slot in self._map.slots():
                self.slot_widgets[name].set_slot(slot)
            self._spec = OutputSpec.from_dict(snap["spec"])
        finally:
            self._suspend = False
        # 触发重打包(预览 + 缩略图)
        # 此时 _in_undo_redo=True,_on_rebuild 只更新 _last_snapshot,不推 undo / 不清 redo
        try:
            self._on_rebuild()
        finally:
            self._in_undo_redo = False
        self.spec_changed.emit()
        self.map_changed.emit()

    def undo(self) -> bool:
        """撤销到上一步。返回 True 表示执行了 undo,False 表示栈空。"""
        if not self._undo_stack:
            return False
        # 当前状态入 redo 栈
        self._redo_stack.append(self._snapshot())
        # 弹出 undo 栈顶(是上一步的状态)并恢复
        prev = self._undo_stack.pop()
        self._restore_snapshot(prev)
        self.undo_redo_changed.emit()
        return True

    def redo(self) -> bool:
        """重做到下一步。返回 True 表示执行了 redo,False 表示栈空。"""
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot())
        nxt = self._redo_stack.pop()
        self._restore_snapshot(nxt)
        self.undo_redo_changed.emit()
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def reset_history(self) -> None:
        """清空 undo/redo(用于工作区加载后,避免回滚到旧状态)。"""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._last_snapshot = self._snapshot()
        self.undo_redo_changed.emit()
    def _on_load_rgba(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选择 RGBA 源图"), "", IMAGE_OPEN_FILTER
        )
        if not path:
            return
        self._load_rgba_from_path(Path(path))

    def _load_rgba_from_path(self, path: Path) -> None:
        """核心:从一张图按 unpack_combo 选定的格式展开到 4 槽。

        流程:
        1. load_image 读图(支持灰度/RGB/RGBA)
        2. 应用 RGBA mask(未勾选通道置 0)
        3. 如果"先编辑"勾选 → 弹 advanced editor,编辑完 → 用编辑结果继续
        4. 按 unpack_combo 格式拆到 4 槽
        """
        try:
            arr = load_image(path).copy()
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("error", tr("读图失败 ({}): {}").format(path.name, exc))
            return
        if arr.ndim == 2:
            rgba = np.zeros(arr.shape + (4,), dtype=arr.dtype)
            rgba[..., 0] = arr
            rgba[..., 3] = full_scale(arr.dtype)
            arr = rgba
        elif arr.shape[-1] == 3:
            rgba = np.zeros(arr.shape[:2] + (4,), dtype=arr.dtype)
            rgba[..., :3] = arr
            rgba[..., 3] = full_scale(arr.dtype)
            arr = rgba
        elif arr.shape[-1] != 4:
            self.status_message.emit("warning", tr("通道数 {} 不支持(需要 1/3/4): {}").format(arr.shape[-1], path.name))
            return

        # RGBA mask:未勾选 → 该通道视为空(置 0)
        for ch, idx in [("R", 0), ("G", 1), ("B", 2), ("A", 3)]:
            if not self._rgba_mask.get(ch, True):
                arr[..., idx] = 0

        # "先编辑"开关:弹 advanced editor 让用户对原图做调整,应用后用编辑结果
        was_preedited = False
        if self.edit_before_import_check.isChecked():
            from src.ui.advanced_editor import AdvancedEditorDialog
            self.status_message.emit("info", tr("打开复杂编辑窗口(对 {} 进行预先调整)…").format(path.name))
            dlg = AdvancedEditorDialog(
                self,
                initial=arr,
                title=tr("预先编辑 - {}  (完成后按 R/G/B/A 拆到 4 槽)").format(path.name),
            )
            if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_data is None:
                self.status_message.emit("info", tr("已取消预先编辑,放弃本次导入"))
                return
            arr = dlg.result_data
            was_preedited = True
            # arr 可能是 H×W(灰度)或 H×W×3(彩色) → 统一补成 H×W×4
            if arr.ndim == 2:
                rgba = np.zeros(arr.shape + (4,), dtype=arr.dtype)
                rgba[..., 0] = arr
                rgba[..., 3] = full_scale(arr.dtype)
                arr = rgba
            elif arr.ndim == 3 and arr.shape[-1] == 3:
                rgba = np.zeros(arr.shape[:2] + (4,), dtype=arr.dtype)
                rgba[..., :3] = arr
                rgba[..., 3] = full_scale(arr.dtype)
                arr = rgba
            self.status_message.emit("success", tr("预先编辑完成,继续按 R/G/B/A 拆槽"))

        fmt_name = self.unpack_combo.currentText()
        sems = UNPACK_FORMATS.get(fmt_name, [Semantic.EMPTY] * 4)

        from src.core.unpacker import unpack_rgba
        m = unpack_rgba(arr, sems)
        # display_name 用源图 stem + 通道名,方便查看
        for ch_name, slot in m.slots():
            if slot.semantic is not Semantic.EMPTY and slot.data is not None:
                slot.display_name = slot.semantic.value
        # 把文件来源信息也带上(用 token 替代旧 channel_in_file)
        token_map = {
            "R": ChannelToken.R, "G": ChannelToken.G,
            "B": ChannelToken.B, "A": ChannelToken.A,
        }
        # 未勾选的通道 → 不带 source(视为空槽,不参与 export)
        checked = {ch: self._rgba_mask.get(ch, True) for ch in ("R", "G", "B", "A")}
        for ch_name, slot in m.slots():
            if slot.data is None:
                continue
            if not checked[ch_name]:
                # 未勾选 → 强制空
                slot.data = None
                slot.source_data = None
                slot.semantic = Semantic.EMPTY
                slot.display_name = ""
                slot.source_type = SourceType.EMPTY
                slot.file_path = None
                slot.token = ChannelToken.BLACK
                continue
            slot.source_type = SourceType.EXTRACTED if was_preedited else SourceType.FILE
            slot.file_path = path
            slot.token = ChannelToken.R if was_preedited else token_map[ch_name]
            slot.color_space = ColorSpace.LINEAR

        # 先把 spec 调成图原始大小,让缩略图清晰
        h, w = arr.shape[:2]
        self._spec.width = int(w)
        self._spec.height = int(h)
        self._spec.size_preset = __import__("src.core.output_spec", fromlist=["SizePreset"]).SizePreset.CUSTOM
        # 导入图是增量更新 → 保留 undo(用户能 undo 回"导入前")
        self.set_map(m, new_baseline=False)
        self.spec_changed.emit()
        # 状态提示
        n_loaded = sum(1 for ch in ("R", "G", "B", "A") if getattr(m, ch).data is not None)
        self.status_message.emit(
            "success",
            tr("已导入 {}（{}×{}, {}, {} 格式），").format(path.name, w, h, arr.dtype, fmt_name)
            + tr("{}/4 槽有数据").format(n_loaded)
        )

    def _on_rgba_toggled(self) -> None:
        """中央 drop zone 的 RGBA 勾选变化时,更新内部状态(下次加载时生效)。"""
        for ch, cb in self._rgba_checks.items():
            self._rgba_mask[ch] = cb.isChecked()
        # 显示当前 mask 状态在 drop label 上
        mask_str = "".join(
            c for c, on in [
                ("R", self._rgba_mask["R"]),
                ("G", self._rgba_mask["G"]),
                ("B", self._rgba_mask["B"]),
                ("A", self._rgba_mask["A"]),
            ] if on
        ) or tr("(全空)")
        self.drop_label.setText(
            tr("✓ 通道 mask: {}    |    拖一张 RGBA 贴图到这里 / 点框体 / 「加载 RGBA…」选图").format(mask_str)
        )

    # -- drop zone(中央 RGBA 自动展开) ---------------------------------
    _DROP_EXTS_GRID = SUPPORTED_IMAGE_EXTS

    def _drop_zone_enter(self, event) -> None:
        if event.mimeData().hasUrls() and any(
            Path(u.toLocalFile()).suffix.lower() in self._DROP_EXTS_GRID
            for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _drop_zone_leave(self, event) -> None:
        event.accept()

    def _drop_zone_drop(self, event) -> None:
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in self._DROP_EXTS_GRID and p.exists():
                self._load_rgba_from_path(p)
                event.acceptProposedAction()
                return
        event.ignore()

    # -- 工作区 ---------------------------------------------------------
    def _on_save_workspace(self) -> None:
        project_dir = self._workspace_dir
        if project_dir is None:
            selected = QFileDialog.getExistingDirectory(
                self,
                tr("选择或新建工程目录（将在其中创建 project.json）"),
                str(Path.cwd()),
            )
            if not selected:
                return
            project_dir = Path(selected)
        try:
            manifest_path = self.save_workspace_directory(project_dir)
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("error", tr("保存工程失败: {}").format(exc))
            return
        self.status_message.emit("success", tr("工程已保存: {}").format(manifest_path))

    def _on_load_workspace(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择工程的 project.json 或旧工作区 JSON"),
            "",
            "Texpipe Project (project.json);;Legacy Workspace (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            loaded = self.load_workspace_path(Path(path))
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit(
                "error", tr("加载工程失败 ({}): {}").format(Path(path).name, exc),
            )
            return
        kind = tr("旧工作区") if loaded.legacy else tr("工程")
        self.status_message.emit("success", tr("{}已加载: {}").format(kind, loaded.manifest_path))

    def save_workspace_directory(self, project_dir: Path) -> Path:
        """保存到工程目录；拆出公共方法便于自动保存和测试复用。"""
        self._autosave_timer.stop()
        self._debounce.stop()
        self._loading_workspace = True
        try:
            self._on_rebuild()
        finally:
            self._loading_workspace = False
        manifest_path = save_project_directory(
            project_dir,
            self._map,
            self._spec,
        )
        self._workspace_dir = manifest_path.parent
        return manifest_path

    def load_workspace_path(self, path: Path):
        """加载目录化工程或旧 JSON，并建立新的 undo 基线。"""
        loaded = load_workspace(path)
        recovered = False
        if (
            not loaded.legacy
            and recovery_snapshot_available(loaded.project_dir)
        ):
            answer = QMessageBox.question(
                self,
                tr("发现自动恢复数据"),
                tr("检测到比正式保存更新的操作数据，是否恢复？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                loaded = load_recovery_snapshot(loaded.project_dir)
                recovered = True
        self._workspace_dir = loaded.project_dir
        self._spec = loaded.output_spec
        self._loading_workspace = True
        try:
            self.set_map(loaded.channel_map, new_baseline=True)
        finally:
            self._loading_workspace = False
        self.spec_changed.emit()
        if recovered:
            self.status_message.emit(
                "warning", tr("已恢复上次未正式保存的操作数据"),
            )
        return loaded

    def _write_autosave(self) -> None:
        """把当前内存状态写入工程的 autosave/recovery.json。"""
        if self._workspace_dir is None or self._loading_workspace:
            return
        try:
            self.get_map()
            save_recovery_snapshot(
                self._workspace_dir,
                self._map,
                self._spec,
                clean=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("warning", tr("自动保存失败: {}").format(exc))

    def flush_pending_autosave(self) -> None:
        """应用关闭前同步写完尚在 debounce 等待中的恢复数据。"""
        if not self._autosave_timer.isActive():
            return
        self._autosave_timer.stop()
        self._write_autosave()

    # -- 直接导出 -------------------------------------------------------
    def export_png(self, path: Path) -> None:
        """用当前 map + spec 调 save_map_rgba 写盘。"""
        # 确保 map 已经 reload 一次
        self._on_rebuild()
        # 若仍有空槽,允许(将填 255);但若全空就报错
        if self._map.all_empty():
            raise ValueError(tr("4 个槽全空,无数据可导出"))
        save_map_rgba(self._map, path)

    # -- 语言切换 -------------------------------------------------------
    def retranslate(self) -> None:
        self._unpack_label.setText(tr("载入 RGBA → 自动 unpack:"))
        self.unpack_btn.setText(tr("加载 RGBA…"))
        self.save_workspace_btn.setText(tr("保存工程"))
        self.load_workspace_btn.setText(tr("加载工程"))
        self.edit_before_import_check.setText(tr("导入后先编辑"))
        self.edit_before_import_check.setToolTip(
            tr("导入图片后,先弹复杂编辑窗口(可做 PS 风格调整 / 混合 / 曲线 / 缩放 pan),\n应用后再按 R/G/B/A 位置拆到 4 槽")
        )
        self._rgba_label.setText(tr("源 RGBA 通道(未勾选=不导入,视为空):"))
        # drop label:全选时是默认提示,否则显示当前 mask
        if all(self._rgba_mask.get(ch, True) for ch in ("R", "G", "B", "A")):
            self.drop_label.setText(
                tr("📥  拖一张 RGBA 贴图到这里,或点框体 / 「加载 RGBA…」选图 — 自动按 R/G/B/A 位置展开到 4 槽")
            )
        else:
            self._on_rgba_toggled()
        for sw in self.slot_widgets.values():
            slot_retranslate = getattr(sw, "retranslate", None)
            if callable(slot_retranslate):
                slot_retranslate()

    # -- 直接访问(给 transcode panel 复用) ------------------------------
    def current_spec(self) -> OutputSpec:
        return self._spec

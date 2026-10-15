"""slot_widget — 单个通道槽组件(v2 token 模型)。

承载一个 `ChannelSlot` 的全部 UI 控件:
- 64×64 缩略图(空时显示 "empty" 文本)
- display_name(可编辑)
- semantic 下拉(roughness/metallic/ao/...)
- **token 下拉(R/G/B/A/INV_R/INV_G/INV_B/INV_A/BLACK/WHITE)** ← 替代旧的 channel + invert
- color_space 下拉
- 源文件路径(只读)+ 浏览按钮
- 一键清空

接受常规贴图与高位深 PNG/TIFF/EXR 拖入。任意编辑都发出 `edited` 信号。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from src.core.slot import (
    ChannelSlot,
    ChannelToken,
    ColorSpace,
    Semantic,
    SourceType,
)
from src.core.pixels import to_display_u8
from src.io.loader import IMAGE_OPEN_FILTER, SUPPORTED_IMAGE_EXTS
from src.io.saver import IMAGE_SAVE_FILTER
from src.ui.i18n import i18n, tr

_DROP_EXTS = SUPPORTED_IMAGE_EXTS
_THUMB_SIZE = 64

# token 标签(中文 + 简短说明)
_TOKEN_LABELS = {
    ChannelToken.R: "R(取红通道)",
    ChannelToken.G: "G(取绿通道)",
    ChannelToken.B: "B(取蓝通道)",
    ChannelToken.A: "A(取透明通道)",
    ChannelToken.INV_R: "INV_R(反相红通道)",
    ChannelToken.INV_G: "INV_G(反相绿通道)",
    ChannelToken.INV_B: "INV_B(反相蓝通道)",
    ChannelToken.INV_A: "INV_A(反相透明通道)",
    ChannelToken.BLACK: "BLACK(全黑 0)",
    ChannelToken.WHITE: "WHITE(全白 255)",
}


class SlotWidget(QFrame):
    """单个通道槽(R / G / B / A 其中之一)的 UI。"""

    edited = Signal()
    status_message = Signal(str, str)  # (level, msg)

    def __init__(self, channel_name: str, parent=None):
        super().__init__(parent)
        self.channel_name = channel_name
        # 按物理位置设默认 token: R 槽 → token=R, G 槽 → token=G, B 槽 → token=B, A 槽 → token=A
        token_map = {
            "R": ChannelToken.R, "G": ChannelToken.G,
            "B": ChannelToken.B, "A": ChannelToken.A,
        }
        self._slot: ChannelSlot = ChannelSlot(token=token_map.get(channel_name, ChannelToken.R))
        self._suspend_signals = False

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAcceptDrops(True)
        self.setMinimumWidth(190)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._build_ui()
        self._wire_signals()
        self._refresh_ui_from_slot()
        i18n.language_changed.connect(self.retranslate)

    # -- 4 槽主题色 -----------------------------------------------------
    # R=红 / G=绿 / B=蓝 / A=紫(灰紫,跟其它 3 色区分明显)
    _CHANNEL_COLORS = {
        "R": "#ff5252",  # 红
        "G": "#4caf50",  # 绿
        "B": "#448aff",  # 蓝
        "A": "#ab47bc",  # 紫(灰紫)
    }

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # 槽主题色(标题文字 + 边框)
        ch_color = self._CHANNEL_COLORS.get(self.channel_name, "#cccccc")
        # 边框(StyledPanel + 1px 实线)
        self.setStyleSheet(
            f"SlotWidget {{ border:1px solid {ch_color}; border-radius:3px; }}"
        )

        # 标题(用主题色,加粗加大)
        self.title_label = QLabel(self.channel_name)
        font = self.title_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.title_label.setFont(font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"color:{ch_color};")
        root.addWidget(self.title_label)

        # 缩略图
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.thumb_label.setStyleSheet("QLabel { background:#222; color:#888; }")
        thumb_row = QHBoxLayout()
        thumb_row.addStretch()
        thumb_row.addWidget(self.thumb_label)
        thumb_row.addStretch()
        root.addLayout(thumb_row)

        # display_name
        self._name_label = QLabel(tr("显示名:"))
        root.addWidget(self._name_label)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("(可填中文/英文)"))
        root.addWidget(self.name_edit)

        # semantic
        self._semantic_label = QLabel(tr("语义:"))
        root.addWidget(self._semantic_label)
        self.semantic_combo = QComboBox()
        for sem in Semantic.data_channels():
            self.semantic_combo.addItem(sem.value, sem)
        self.semantic_combo.insertItem(0, Semantic.EMPTY.value, Semantic.EMPTY)
        self.semantic_combo.setCurrentIndex(0)
        root.addWidget(self.semantic_combo)

        # token(替代 channel_in_file + invert)
        self._token_label = QLabel(tr("源 token:"))
        root.addWidget(self._token_label)
        self.token_combo = QComboBox()
        for t in ChannelToken:
            self.token_combo.addItem(tr(_TOKEN_LABELS[t]), t)
        self.token_combo.setCurrentIndex(0)
        root.addWidget(self.token_combo)

        # color_space
        self._color_label = QLabel(tr("颜色空间标签:"))
        self._color_label.setToolTip(tr("当前版本仅记录语义标签,不会改写通道数值或 PNG gamma。"))
        root.addWidget(self._color_label)
        self.colorspace_combo = QComboBox()
        for cs in ColorSpace:
            self.colorspace_combo.addItem(cs.value, cs)
        root.addWidget(self.colorspace_combo)

        # 源文件
        self._file_label = QLabel(tr("源文件:"))
        root.addWidget(self._file_label)
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText(tr("(拖入贴图或点浏览)"))
        file_row.addWidget(self.file_edit, stretch=1)
        self.browse_btn = QPushButton("…")
        self.browse_btn.setFixedWidth(28)
        file_row.addWidget(self.browse_btn)
        root.addLayout(file_row)

        # 单槽操作:第一行 导出 / 替换 / 清空(1:1:1 等分)
        ops_row = QHBoxLayout()
        ops_row.setSpacing(4)
        self.export_btn = QPushButton(tr("导出"))
        self.export_btn.setToolTip(tr("把当前通道(已应用 token)导出为单通道灰度 PNG"))
        ops_row.addWidget(self.export_btn, stretch=1)
        self.replace_btn = QPushButton(tr("替换"))
        self.replace_btn.setToolTip(tr("用另一个源文件替换本槽(保留 token / invert / semantic / colorspace)"))
        ops_row.addWidget(self.replace_btn, stretch=1)
        self.clear_btn = QPushButton(tr("清空"))
        self.clear_btn.setToolTip(tr("清空本槽所有数据"))
        ops_row.addWidget(self.clear_btn, stretch=1)
        root.addLayout(ops_row)

        # 第二行:复杂编辑(独占一行,宽度 = 上面 3 个按钮之和,字数多,避免挤压)
        self.advanced_btn = QPushButton(tr("复杂编辑"))
        self.advanced_btn.setToolTip(tr("打开独立窗口:PS 风格调整 + 15 种混合模式 + 3 点 LUT + 第二张图"))
        root.addWidget(self.advanced_btn)

        root.addStretch()

    # -- 语言切换 -------------------------------------------------------
    def retranslate(self) -> None:
        self._name_label.setText(tr("显示名:"))
        self.name_edit.setPlaceholderText(tr("(可填中文/英文)"))
        self._semantic_label.setText(tr("语义:"))
        self._token_label.setText(tr("源 token:"))
        # token 下拉:重建条目文本,保留当前选中
        current_token = self.token_combo.currentData()
        self._suspend_signals = True
        try:
            self.token_combo.clear()
            for t in ChannelToken:
                self.token_combo.addItem(tr(_TOKEN_LABELS[t]), t)
            idx = self.token_combo.findData(current_token)
            if idx >= 0:
                self.token_combo.setCurrentIndex(idx)
        finally:
            self._suspend_signals = False
        self._color_label.setText(tr("颜色空间标签:"))
        self._color_label.setToolTip(tr("当前版本仅记录语义标签,不会改写通道数值或 PNG gamma。"))
        self._file_label.setText(tr("源文件:"))
        self.file_edit.setPlaceholderText(tr("(拖入贴图或点浏览)"))
        self.export_btn.setText(tr("导出"))
        self.export_btn.setToolTip(tr("把当前通道(已应用 token)导出为单通道灰度 PNG"))
        self.replace_btn.setText(tr("替换"))
        self.replace_btn.setToolTip(tr("用另一个源文件替换本槽(保留 token / invert / semantic / colorspace)"))
        self.clear_btn.setText(tr("清空"))
        self.clear_btn.setToolTip(tr("清空本槽所有数据"))
        self.advanced_btn.setText(tr("复杂编辑"))
        self.advanced_btn.setToolTip(tr("打开独立窗口:PS 风格调整 + 15 种混合模式 + 3 点 LUT + 第二张图"))

    def _wire_signals(self) -> None:
        self.name_edit.textChanged.connect(self._on_edited)
        self.semantic_combo.currentIndexChanged.connect(self._on_semantic_changed)
        self.token_combo.currentIndexChanged.connect(self._on_edited)
        self.colorspace_combo.currentIndexChanged.connect(self._on_edited)
        self.browse_btn.clicked.connect(self._on_browse)
        self.export_btn.clicked.connect(self._on_export)
        self.replace_btn.clicked.connect(self._on_replace)
        self.advanced_btn.clicked.connect(self._on_advanced)
        self.clear_btn.clicked.connect(self._on_clear)

    def set_slot(self, slot: ChannelSlot) -> None:
        self._slot = slot
        self._suspend_signals = True
        try:
            self._refresh_ui_from_slot()
        finally:
            self._suspend_signals = False

    def get_slot(self) -> ChannelSlot:
        s = self._slot
        s.display_name = self.name_edit.text()
        s.semantic = self.semantic_combo.currentData() or Semantic.EMPTY
        s.token = self.token_combo.currentData() or ChannelToken.R
        s.color_space = self.colorspace_combo.currentData() or ColorSpace.LINEAR
        return s

    def _refresh_ui_from_slot(self) -> None:
        s = self._slot
        self.name_edit.setText(s.display_name or "")
        # semantic
        idx = self.semantic_combo.findData(s.semantic)
        if idx >= 0:
            self.semantic_combo.setCurrentIndex(idx)
        else:
            self.semantic_combo.setCurrentIndex(0)
        # token
        idx = self.token_combo.findData(s.token)
        if idx >= 0:
            self.token_combo.setCurrentIndex(idx)
        else:
            self.token_combo.setCurrentIndex(0)
        # color_space
        idx = self.colorspace_combo.findData(s.color_space)
        if idx >= 0:
            self.colorspace_combo.setCurrentIndex(idx)
        # file
        self.file_edit.setText(str(s.file_path) if s.file_path else "")
        # 缩略图
        self.set_thumbnail(s.data)

    def set_thumbnail(self, arr: Optional[np.ndarray]) -> None:
        if arr is None or arr.ndim < 2:
            self.thumb_label.setText("empty")
            self.thumb_label.setPixmap(QPixmap())
            return
        height, width = arr.shape[:2]
        step = max(1, int(np.ceil(max(height, width) / _THUMB_SIZE)))
        arr = to_display_u8(arr[::step, ::step])
        if arr.ndim == 2:
            h, w = arr.shape
            data = np.ascontiguousarray(arr)
            qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            h, w = arr.shape[:2]
            if arr.shape[-1] >= 3:
                rgb = np.ascontiguousarray(arr[..., :3])
                qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
            else:
                data = np.ascontiguousarray(arr[..., 0])
                qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg)
        scaled = pix.scaled(
            QSize(_THUMB_SIZE, _THUMB_SIZE),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setText("")
        self.thumb_label.setPixmap(scaled)

    def clear_thumbnail(self) -> None:
        self.thumb_label.setText("empty")
        self.thumb_label.setPixmap(QPixmap())

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(210, 480)

    def _emit_edited(self) -> None:
        if not self._suspend_signals:
            self.edited.emit()

    def _on_edited(self, *_args) -> None:
        self._emit_edited()

    def _on_semantic_changed(self, _idx: int) -> None:
        sem = self.semantic_combo.currentData()
        if isinstance(sem, Semantic):
            default = Semantic.default_color_space(sem)
            if self.colorspace_combo.currentData() == ColorSpace.LINEAR and sem is not Semantic.EMPTY:
                idx = self.colorspace_combo.findData(default)
                if idx >= 0:
                    self._suspend_signals = True
                    self.colorspace_combo.setCurrentIndex(idx)
                    self._suspend_signals = False
        self._emit_edited()

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择 {} 通道源文件").format(self.channel_name),
            "",
            IMAGE_OPEN_FILTER,
        )
        if path:
            self._assign_file(Path(path))

    def _on_export(self) -> None:
        """把当前通道（已应用 token 后）按所选格式导出。"""
        if self._slot.data is None:
            self.status_message.emit("warning", tr("{} 槽为空,先载入源文件再导出").format(self.channel_name))
            return
        # 默认文件名:用显示名(若空则用 channel_name)
        stem = (self._slot.display_name or self.channel_name).strip() or self.channel_name
        # 通道标记:R/G/B/A
        suffix = ".exr" if self._slot.data.dtype.kind == "f" else ".png"
        default_name = f"{stem}_{self.channel_name}{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("导出 {} 通道").format(self.channel_name),
            default_name,
            IMAGE_SAVE_FILTER,
        )
        if not path:
            return
        try:
            from src.io.saver import save_grayscale
            save_grayscale(self._slot.data, path)
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("error", tr("导出 {} 通道失败: {}").format(self.channel_name, exc))
            return
        self.status_message.emit("success", tr("{} 通道已导出到: {}").format(self.channel_name, path))

    def _on_replace(self) -> None:
        """用新源文件替换本槽(保留 token / semantic / colorspace / invert)。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("替换 {} 通道源文件").format(self.channel_name),
            "",
            IMAGE_OPEN_FILTER,
        )
        if not path:
            return
        self._assign_file(Path(path))
        self.status_message.emit("info", tr("{} 槽已替换源文件: {}").format(self.channel_name, Path(path).name))

    def _advanced_initial_data(self) -> Optional[np.ndarray]:
        """返回复杂编辑器应使用的母版数据，而不是已经按输出规格裁切的预览。

        FILE 槽的 ``source_data``/``data`` 会在常规重建时按 OutputSpec 缩放，
        因而不能作为复杂编辑的输入。这里重新读取源文件并提取当前 token，
        保留源贴图的完整宽高。派生编辑结果则优先使用未缩放的 source_data。
        """
        slot = self.get_slot()
        if slot.source_type is SourceType.FILE and slot.file_path is not None:
            from src.io.loader import extract_by_token, load_image

            source = load_image(slot.file_path)
            return extract_by_token(source, slot.token).copy()
        if slot.source_data is not None:
            return slot.source_data.copy()
        if slot.data is not None:
            return slot.data.copy()
        return None

    def _on_advanced(self) -> None:
        """打开"复杂编辑"独立窗口,编辑完后写回 slot.data。"""
        try:
            initial = self._advanced_initial_data()
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit(
                "error",
                tr("{} 槽原始贴图加载失败: {}").format(self.channel_name, exc),
            )
            return
        if initial is None:
            self.status_message.emit("warning", tr("{} 槽为空,先载入源文件或 token 提取后再编辑").format(self.channel_name))
            return
        from src.ui.advanced_editor import AdvancedEditorDialog
        dlg = AdvancedEditorDialog(
            self,
            initial=initial,
            title=tr("复杂编辑 - {} 槽").format(self.channel_name),
        )
        # 转发 dlg 内部状态消息到 slot 的 status_message
        dlg.status_message.connect(self.status_message)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_data is not None:
            # source_data 保留完整编辑尺寸；上层重建只为预览/导出生成目标尺寸 data。
            self._slot.data = dlg.result_data.copy()
            self._slot.source_data = dlg.result_data.copy()
            self._slot.source_type = SourceType.EXTRACTED
            self._slot.token = ChannelToken.R
            # 缩略图也更新
            self.set_thumbnail(self._slot.data)
            # 触发上层 debounce + 入 undo 栈
            self._emit_edited()
            self.status_message.emit("success", tr("{} 槽已应用复杂编辑结果").format(self.channel_name))

    def _on_clear(self) -> None:
        had_data = self._slot.data is not None
        token_map = {
            "R": ChannelToken.R, "G": ChannelToken.G,
            "B": ChannelToken.B, "A": ChannelToken.A,
        }
        self._slot = ChannelSlot(token=token_map.get(self.channel_name, ChannelToken.R))
        self._suspend_signals = True
        try:
            self._refresh_ui_from_slot()
        finally:
            self._suspend_signals = False
        self.clear_thumbnail()
        self._emit_edited()
        if had_data:
            self.status_message.emit("info", tr("{} 槽已清空").format(self.channel_name))

    def _assign_file(self, path: Path, token: Optional[ChannelToken] = None) -> None:
        """把源文件绑到该槽。

        Args:
            path: 源文件路径
            token: 显式指定 token。如果不传,保留当前 token(用户可手动改 token_combo)。
        """
        self._slot.source_type = SourceType.FILE
        self._slot.file_path = path
        if token is not None:
            self._slot.token = token
        if not (self._slot.display_name or self.name_edit.text()):
            self._slot.display_name = path.stem
        self._suspend_signals = True
        try:
            self._refresh_ui_from_slot()
        finally:
            self._suspend_signals = False
        self._emit_edited()
        self.status_message.emit("info", tr("{} 槽载入源文件: {}").format(self.channel_name, path.name))

    def _accept_url(self, path: Path) -> bool:
        return path.suffix.lower() in _DROP_EXTS and path.exists()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        md = event.mimeData()
        if md.hasUrls() and any(self._accept_url(Path(u.toLocalFile())) for u in md.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        md = event.mimeData()
        for url in md.urls():
            p = Path(url.toLocalFile())
            if self._accept_url(p):
                self._assign_file(p)
                event.acceptProposedAction()
                return
        event.ignore()

"""transcode_panel — 互转模式面板。

工作流:
- 选源格式(下拉) + 选目标格式(下拉) + 载入源图
- 自动按 src_format unpack → 按 dst_format 重打包,显示结果缩略图
- "导出目标图" 按钮调 save_map_rgba 落盘

不修改上层 ChannelMap（互转是独立的高位深安全处理流程）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.transcoder import compose_token_mappings, transcode_between_presets
from src.core.pixels import full_scale
from src.core.presets import PRESETS
from src.io.loader import IMAGE_OPEN_FILTER, load_image
from src.io.saver import IMAGE_SAVE_FILTER, save_rgba
from src.ui.i18n import i18n, tr
from src.ui.preview_widget import _ChannelPreview

# 13 个预设(从 PRESETS 取)
PRESET_OPTIONS: list[str] = [p.id for p in PRESETS]


def _ensure_rgba(arr: np.ndarray) -> np.ndarray:
    """把 H×W / H×W×3 升到 H×W×4。"""
    if arr.ndim == 2:
        rgba = np.zeros(arr.shape + (4,), dtype=arr.dtype)
        rgba[..., 0] = arr
        rgba[..., 3] = full_scale(arr.dtype)
        return rgba
    if arr.shape[-1] == 3:
        rgba = np.zeros(arr.shape[:2] + (4,), dtype=arr.dtype)
        rgba[..., :3] = arr
        rgba[..., 3] = full_scale(arr.dtype)
        return rgba
    return arr


class TranscodePanelWidget(QWidget):
    """互转模式面板。"""

    status_message = Signal(str, str)  # (level, msg)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src_arr: np.ndarray | None = None
        self._build_ui()
        self._wire_signals()
        # 初始清空预览
        self._refresh()
        i18n.language_changed.connect(self.retranslate)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        # 格式选择 + 载入/导出
        top = QHBoxLayout()
        self._src_label = QLabel(tr("源 preset:"))
        top.addWidget(self._src_label)
        self.src_fmt = QComboBox()
        for pid in PRESET_OPTIONS:
            self.src_fmt.addItem(pid)
        top.addWidget(self.src_fmt)
        top.addSpacing(16)
        self._dst_label = QLabel(tr("目标 preset:"))
        top.addWidget(self._dst_label)
        self.dst_fmt = QComboBox()
        for pid in PRESET_OPTIONS:
            self.dst_fmt.addItem(pid)
        top.addWidget(self.dst_fmt)
        top.addSpacing(16)
        self.load_btn = QPushButton(tr("载入源图…"))
        top.addWidget(self.load_btn)
        self.export_btn = QPushButton(tr("导出目标图…"))
        top.addWidget(self.export_btn)
        top.addStretch()
        root.addLayout(top)

        # 预览区:源 / 目标 并排
        preview_row = QHBoxLayout()
        # 源
        self._src_box = QGroupBox(tr("源 RGBA"))
        src_layout = QVBoxLayout(self._src_box)
        self.src_preview = _ChannelPreview(tr("载入后显示"))
        self.src_preview.setMinimumHeight(280)
        src_layout.addWidget(self.src_preview)
        preview_row.addWidget(self._src_box, stretch=1)
        # 目标
        self._dst_box = QGroupBox(tr("目标 RGBA"))
        dst_layout = QVBoxLayout(self._dst_box)
        self.dst_preview = _ChannelPreview(tr("实时转换结果"))
        self.dst_preview.setMinimumHeight(280)
        dst_layout.addWidget(self.dst_preview)
        preview_row.addWidget(self._dst_box, stretch=1)
        root.addLayout(preview_row, stretch=1)

        # 状态信息
        self.status_label = QLabel(tr("未载入源图。"))
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def retranslate(self) -> None:
        self._src_label.setText(tr("源 preset:"))
        self._dst_label.setText(tr("目标 preset:"))
        self.load_btn.setText(tr("载入源图…"))
        self.export_btn.setText(tr("导出目标图…"))
        self._src_box.setTitle(tr("源 RGBA"))
        self._dst_box.setTitle(tr("目标 RGBA"))
        self.src_preview.set_title(tr("载入后显示"))
        self.dst_preview.set_title(tr("实时转换结果"))
        for p in (self.src_preview, self.dst_preview):
            p.thumb.setToolTip(tr("点击查看大图(滚轮缩放 / 右键 pan / 双击重置)"))
            if p._arr is None:
                p.thumb.setText(tr("empty\n(点击查看)"))
        # 状态文本:重新生成(已载入则重算映射信息)
        if self._src_arr is None:
            self.status_label.setText(tr("未载入源图。"))
        else:
            self._refresh()

    def _wire_signals(self) -> None:
        self.src_fmt.currentIndexChanged.connect(self._refresh)
        self.dst_fmt.currentIndexChanged.connect(self._refresh)
        self.load_btn.clicked.connect(self._on_load)
        self.export_btn.clicked.connect(self._on_export)

    # -- 载入 ---------------------------------------------------------
    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("选择源图"), "", IMAGE_OPEN_FILTER
        )
        if not path:
            return
        try:
            arr = load_image(path)
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("error", tr("读图失败 ({}): {}").format(Path(path).name, exc))
            return
        self._src_arr = _ensure_rgba(arr)
        h, w = self._src_arr.shape[:2]
        self.status_label.setText(tr("源图: {}\n  尺寸: {}×{}  精度: {}").format(path, w, h, self._src_arr.dtype))
        self.status_message.emit(
            "success", tr("已载入源图: {} ({}×{}, {})").format(Path(path).name, w, h, self._src_arr.dtype),
        )
        self._refresh()

    # -- 转换 + 刷新预览 ---------------------------------------------
    def _refresh(self) -> None:
        # 源预览
        if self._src_arr is not None:
            self.src_preview.set_array(self._src_arr)
        else:
            self.src_preview.set_array(None)

        # 目标预览(实时)
        if self._src_arr is None:
            self.dst_preview.set_array(None)
            return
        src_id = self.src_fmt.currentText()
        dst_id = self.dst_fmt.currentText()
        from src.core.presets import get_preset
        try:
            src_preset = get_preset(src_id)
            dst_preset = get_preset(dst_id)
        except ValueError as exc:
            self.dst_preview.set_array(None)
            self.status_label.setText(tr("未知 preset: {}").format(exc))
            return
        # 用源 preset 的 mapping 解析 → 用目标 preset 的 mapping 重新打包
        try:
            out = transcode_between_presets(self._src_arr, src_preset, dst_preset)
        except Exception as exc:  # noqa: BLE001
            self.dst_preview.set_array(None)
            self.status_label.setText(tr("转换失败: {}").format(exc))
            self.status_message.emit("error", tr("转换失败 ({}→{}): {}").format(src_id, dst_id, exc))
            return
        self.dst_preview.set_array(out)
        composed = compose_token_mappings(src_preset.mapping, dst_preset.mapping)
        h, w = self._src_arr.shape[:2]
        self.status_label.setText(
            tr("源: {}  →  目标: {}\n").format(src_id, dst_id)
            + tr("  源尺寸: {}×{}\n").format(w, h)
            + tr("  实际映射: {}").format([t.value for t in composed])
        )

    # -- 导出 ---------------------------------------------------------
    def _on_export(self) -> None:
        if self._src_arr is None:
            self.status_message.emit("warning", tr("请先在互转模式载入源图(顶部「载入源图…」)"))
            return
        from src.core.presets import get_preset
        src_preset = get_preset(self.src_fmt.currentText())
        dst_preset = get_preset(self.dst_fmt.currentText())
        suffix = ".exr" if self._src_arr.dtype.kind == "f" else ".png"
        default_name = f"transcoded_{dst_preset.suffix.lstrip('_')}{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("导出目标图"), default_name, IMAGE_SAVE_FILTER
        )
        if not path:
            return
        try:
            out = transcode_between_presets(self._src_arr, src_preset, dst_preset)
            save_rgba(out, path)
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("error", tr("导出失败 ({}): {}").format(Path(path).name, exc))
            return
        self.status_message.emit("success", tr("互转图已导出: {}  ({} → {})").format(path, src_preset.id, dst_preset.id))

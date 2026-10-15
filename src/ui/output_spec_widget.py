"""output_spec_widget — OutputSpec 编辑器。

给主窗口的"编辑模式"底部使用,提供:
- size_preset 档位
- 自定义 width/height
- resize_mode / resize_filter
- force_pot / pot_strategy
- 导出路径(只读) + 浏览

信号:
- spec_changed  任意编辑后发出
- export_requested  点击"导出贴图"后发出(参数:目标 path)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.output_spec import (
    OutputSpec,
    PotStrategy,
    ResizeFilter,
    ResizeMode,
    SizePreset,
)
from src.io.saver import IMAGE_SAVE_FILTER


class OutputSpecWidget(QGroupBox):
    """编辑模式底部的输出规格控件。"""

    spec_changed = Signal()
    export_requested = Signal(str)  # 目标文件路径
    status_message = Signal(str, str)  # (level, msg)

    def __init__(self, parent=None):
        super().__init__("输出规格", parent)
        self._suspend = False
        self._build_ui()
        self._wire_signals()
        self._refresh_enabled()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())

        # size_preset
        self.preset_combo = QComboBox()
        for sp in SizePreset:
            self.preset_combo.addItem(sp.value, sp)
        self.preset_combo.setCurrentIndex(0)
        form.addRow("尺寸档位:", self.preset_combo)

        # width / height(同 row)
        wh_row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 16384)
        self.width_spin.setValue(2048)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 16384)
        self.height_spin.setValue(2048)
        wh_row.addWidget(self.width_spin)
        wh_row.addWidget(QLabel("×"))
        wh_row.addWidget(self.height_spin)
        wh_widget = QWidget()
        wh_widget.setLayout(wh_row)
        form.addRow("自定义 (W × H):", wh_widget)

        # resize_mode
        self.resize_mode_combo = QComboBox()
        for m in ResizeMode:
            self.resize_mode_combo.addItem(m.value, m)
        form.addRow("resize 模式:", self.resize_mode_combo)

        # resize_filter
        self.resize_filter_combo = QComboBox()
        for f in ResizeFilter:
            self.resize_filter_combo.addItem(f.value, f)
        form.addRow("resize 滤镜:", self.resize_filter_combo)

        # force_pot
        self.force_pot_check = QCheckBox("force_pot (对齐到 2 的幂)")
        form.addRow("", self.force_pot_check)

        # pot_strategy
        self.pot_strategy_combo = QComboBox()
        for p in PotStrategy:
            self.pot_strategy_combo.addItem(p.value, p)
        form.addRow("POT 策略:", self.pot_strategy_combo)

        root.addLayout(form)

        # 导出
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("导出路径:"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("(选择 PNG / TIFF / EXR 输出位置)")
        export_row.addWidget(self.path_edit, stretch=1)
        self.browse_btn = QPushButton("…")
        self.browse_btn.setFixedWidth(28)
        export_row.addWidget(self.browse_btn)
        self.export_btn = QPushButton("导出贴图")
        export_row.addWidget(self.export_btn)
        root.addLayout(export_row)

    def _wire_signals(self) -> None:
        self.preset_combo.currentIndexChanged.connect(self._on_changed)
        self.width_spin.valueChanged.connect(self._on_changed)
        self.height_spin.valueChanged.connect(self._on_changed)
        self.resize_mode_combo.currentIndexChanged.connect(self._on_changed)
        self.resize_filter_combo.currentIndexChanged.connect(self._on_changed)
        self.force_pot_check.toggled.connect(self._on_changed)
        self.pot_strategy_combo.currentIndexChanged.connect(self._on_changed)
        self.browse_btn.clicked.connect(self._on_browse)
        self.export_btn.clicked.connect(self._on_export)

    # -- 公开接口 -------------------------------------------------------
    def get_spec(self) -> OutputSpec:
        sp = self._preset_from_combo(self.preset_combo, SizePreset.CUSTOM)
        return OutputSpec(
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            size_preset=sp,
            resize_mode=self._enum_from_combo(self.resize_mode_combo, ResizeMode.FIT),
            resize_filter=self._enum_from_combo(self.resize_filter_combo, ResizeFilter.LANCZOS),
            force_pot=self.force_pot_check.isChecked(),
            pot_strategy=self._enum_from_combo(self.pot_strategy_combo, PotStrategy.ROUND_UP),
        )

    def set_spec(self, spec: OutputSpec, emit: bool = True) -> None:
        self._suspend = True
        try:
            self._set_combo_by_value(self.preset_combo, spec.size_preset.value)
            self.width_spin.setValue(int(spec.width))
            self.height_spin.setValue(int(spec.height))
            self._set_combo_by_value(self.resize_mode_combo, spec.resize_mode.value)
            self._set_combo_by_value(self.resize_filter_combo, spec.resize_filter.value)
            self.force_pot_check.setChecked(bool(spec.force_pot))
            self._set_combo_by_value(self.pot_strategy_combo, spec.pot_strategy.value)
        finally:
            self._suspend = False
        self._refresh_enabled()
        # 让外部订阅者(主窗口)同步到 ChannelGrid。
        # 走 spec_changed 信号,不在这里直接调 channel_grid,避免反向耦合。
        if emit:
            self.spec_changed.emit()

    @staticmethod
    def _enum_from_combo(combo: QComboBox, default):
        """PySide6 的 QComboBox.currentData() 把 str-Enum 当字符串返回,这里按 value 反查。"""
        text = combo.currentText()
        for i in range(combo.count()):
            data = combo.itemData(i)
            if isinstance(data, type(default)) and data.value == text:
                return data
        # 兜底:把 text 当作 value 构造枚举
        try:
            return type(default)(text)
        except Exception:
            return default

    @staticmethod
    def _set_combo_by_value(combo: QComboBox, value: str) -> None:
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data is not None and getattr(data, "value", data) == value:
                combo.setCurrentIndex(i)
                return
        # 兜底:按 text
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _preset_from_combo(self, combo: QComboBox, default: SizePreset) -> SizePreset:
        return self._enum_from_combo(combo, default)

    def get_export_path(self) -> Optional[Path]:
        t = self.path_edit.text().strip()
        if not t:
            return None
        return Path(t)

    def set_export_path(self, p: Path) -> None:
        self.path_edit.setText(str(p))

    # -- 内部 -----------------------------------------------------------
    def _on_changed(self, *_args) -> None:
        if self._suspend:
            return
        self._refresh_enabled()
        self.spec_changed.emit()
        # 给个简要提示(spec 改变 → 触发重打包)
        w, h = self.get_spec().effective_size()
        self.status_message.emit("info", f"输出规格已更新 → {w}×{h}")

    def _refresh_enabled(self) -> None:
        sp = self._preset_from_combo(self.preset_combo, SizePreset.CUSTOM)
        custom = sp is SizePreset.CUSTOM
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "选择导出路径", self.path_edit.text() or "output.png",
            IMAGE_SAVE_FILTER,
        )
        if path:
            self.path_edit.setText(path)
            self.status_message.emit("info", f"已选择导出路径: {path}")

    def _on_export(self) -> None:
        p = self.get_export_path()
        if p is None:
            self.status_message.emit("warning", "请先选择导出路径（点右侧「浏览…」）")
            return
        if not p.suffix:
            p = p.with_suffix(".png")
            self.path_edit.setText(str(p))
        self.export_requested.emit(str(p))

"""复杂编辑对话框的状态管理与 UI 编排。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.core.pixels import full_scale, to_display_u8
from src.core.resize import resize_to
from src.core.transform import normalize_angle, rotate_image
from src.io.loader import IMAGE_OPEN_FILTER, SUPPORTED_IMAGE_EXTS, load_image
from src.ui.i18n import tr

from .advanced_editor_components.adjustments import (
    AdjustmentSettings,
    compute_adjustments,
)
from .advanced_editor_components.blend_modes import BLEND_MODES
from .advanced_editor_components.curves import CurveWidget
from .advanced_editor_components.mapping import (
    SECOND_IMAGE_MAPPINGS,
    map_second_to_canvas,
)
from .advanced_editor_components.preview import (
    ClickableDropFrame,
    PannableScrollArea,
)


class AdvancedEditorDialog(QDialog):
    """单通道或 RGB/RGBA 贴图的非破坏性复杂编辑窗口。

    对话框只维护控件状态、第二图片资源和预览；像素运算、混合、曲线、
    映射与预览交互分别由 ``advanced_editor_components`` 中的模块负责。
    """

    status_message = Signal(str, str)
    PREVIEW_MAX_EDGE = 1024

    def __init__(
        self,
        parent=None,
        initial: Optional[np.ndarray] = None,
        title: str = "复杂编辑",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1280, 800)

        self._preserved_alpha: Optional[np.ndarray] = None
        if initial is None:
            self._original = np.zeros((64, 64), dtype=np.uint8)
            self._is_color = False
        else:
            source = np.asarray(initial).copy()
            if source.ndim == 3:
                if source.shape[-1] not in (3, 4):
                    raise ValueError(
                        tr("复杂编辑只支持灰度/RGB/RGBA，收到 {}").format(source.shape),
                    )
                if source.shape[-1] == 4:
                    self._preserved_alpha = source[..., 3].copy()
                self._original = source[..., :3].copy()
                self._is_color = True
            elif source.ndim == 2:
                self._original = source
                self._is_color = False
            else:
                raise ValueError(
                    tr("复杂编辑只支持 H×W 或 H×W×3/4，收到 {}").format(source.shape),
                )

        self._brightness = 0
        self._contrast = 1.0
        self._exposure = 0.0
        self._shadows = 0
        self._highlights = 0
        self._gamma = 1.0
        self._saturation = 1.0
        self._threshold = -1
        self._posterize = 256
        self._invert = False
        self._rotation = 0.0
        self._rotated_cache_angle: Optional[float] = None
        self._rotated_cache: Optional[np.ndarray] = None
        self._preview_original = self._make_preview_proxy(self._original)
        self._preview_rotated_cache_angle: Optional[float] = None
        self._preview_rotated_cache: Optional[np.ndarray] = None

        self._blend_id = "normal"
        self._second_path: Optional[Path] = None
        self._second_source_data: Optional[np.ndarray] = None
        self._second_data: Optional[np.ndarray] = None
        self._second_mapping_mode = "stretch"
        self._second_scale_x = 1.0
        self._second_scale_y = 1.0
        self._second_offset_x = 0
        self._second_offset_y = 0
        self._syncing_second_transform = False
        self._second_rgba_mask = {
            "R": True,
            "G": True,
            "B": True,
            "A": True,
        }

        self.result_data: Optional[np.ndarray] = None
        self._did_initial_fit = False
        self._build_ui()
        self._render_preview()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        self._main_splitter = QSplitter(Qt.Orientation.Vertical)
        self._configure_splitter(self._main_splitter, vertical=True)
        self._top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._configure_splitter(self._top_splitter, vertical=False)
        self._top_splitter.addWidget(self._build_blend_panel())
        self._top_splitter.addWidget(self._build_color_panel())
        self._top_splitter.addWidget(self._build_curve_panel())
        self._top_splitter.setSizes([320, 320, 320])
        self._main_splitter.addWidget(self._top_splitter)

        self._preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._configure_splitter(self._preview_splitter, vertical=False)
        self._preview_splitter.addWidget(
            self._build_preview_box(tr("原图（应用前）"), self._original, "orig"),
        )
        self._preview_splitter.addWidget(
            self._build_preview_box(tr("结果（应用后）"), self._original, "result"),
        )
        self._preview_splitter.setSizes([600, 600])
        self._main_splitter.addWidget(self._preview_splitter)
        self._main_splitter.setSizes([400, 400])
        root.addWidget(self._main_splitter, 1)

        buttons = QHBoxLayout()
        reset_button = QPushButton(tr("重置所有参数"))
        reset_button.clicked.connect(self._on_reset)
        buttons.addWidget(reset_button)
        fit_button = QPushButton(tr("适应窗口"))
        fit_button.clicked.connect(self._fit_previews)
        buttons.addWidget(fit_button)
        buttons.addStretch()
        self._zoom_label = QLabel(tr("缩放: 100% / 100%"))
        self._zoom_label.setStyleSheet("color:#888;")
        buttons.addWidget(self._zoom_label)
        buttons.addStretch()
        apply_button = QPushButton(tr("应用并关闭"))
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        buttons.addWidget(apply_button)
        cancel_button = QPushButton(tr("取消"))
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        root.addLayout(buttons)

    @staticmethod
    def _configure_splitter(splitter: QSplitter, *, vertical: bool) -> None:
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        axis = "vertical" if vertical else "horizontal"
        size = "height" if vertical else "width"
        splitter.setStyleSheet(
            "QSplitter::handle { background:#444; }"
            "QSplitter::handle:hover { background:#0a84ff; }"
            f"QSplitter::handle:{axis} {{ {size}:6px; }}",
        )

    def _build_blend_panel(self) -> QWidget:
        box = QGroupBox(tr("混合（原图 + 第二张图）"))
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(tr("第二张图（支持拖拽 / 点击 / 浏览 / 编辑）:")))

        self._second_drop = ClickableDropFrame()
        self._second_drop.setObjectName("BlendSecondDrop")
        self._second_drop.setMinimumHeight(60)
        self._second_drop.setStyleSheet(
            "QFrame#BlendSecondDrop { background:#1a1a1a;"
            " border:2px dashed #555; border-radius:6px; }"
            "QFrame#BlendSecondDrop:hover { border-color:#0a84ff; }",
        )
        self._second_drop.dragEnterEvent = self._second_drag_enter
        self._second_drop.dragLeaveEvent = self._second_drag_leave
        self._second_drop.dropEvent = self._second_drop_event
        self._second_drop._on_click = self._on_pick_second
        drop_layout = QVBoxLayout(self._second_drop)
        drop_layout.setContentsMargins(8, 4, 8, 4)
        self._second_drop_label = QLabel(tr("📥  拖入 / 点击框体 / 用「浏览」选文件"))
        self._second_drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._second_drop_label.setStyleSheet("color:#888;")
        drop_layout.addWidget(self._second_drop_label)
        layout.addWidget(self._second_drop)

        self._second_edit = QLineEdit()
        self._second_edit.setReadOnly(True)
        self._second_edit.setPlaceholderText(tr("（空 = 不混合）"))
        layout.addWidget(self._second_edit)

        rgba_row = QHBoxLayout()
        rgba_row.addWidget(QLabel(tr("源 RGBA 通道:")))
        self._second_rgba_checks: dict[str, QCheckBox] = {}
        for channel in "RGBA":
            checkbox = QCheckBox(channel)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._on_second_rgba_toggled)
            self._second_rgba_checks[channel] = checkbox
            rgba_row.addWidget(checkbox)
        rgba_row.addStretch()
        layout.addLayout(rgba_row)

        mapping_row = QHBoxLayout()
        mapping_row.addWidget(QLabel(tr("尺寸映射:")))
        self._second_mapping_combo = QComboBox()
        for mode_id, label in SECOND_IMAGE_MAPPINGS:
            self._second_mapping_combo.addItem(tr(label), mode_id)
        self._second_mapping_combo.currentIndexChanged.connect(
            self._on_second_transform_changed,
        )
        mapping_row.addWidget(self._second_mapping_combo, 1)
        layout.addLayout(mapping_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel(tr("拉伸/缩放:")))
        self._second_scale_x_spin = self._make_percent_spin(" X")
        self._second_scale_y_spin = self._make_percent_spin(" Y")
        self._second_scale_x_spin.valueChanged.connect(
            self._on_second_transform_changed,
        )
        self._second_scale_y_spin.valueChanged.connect(
            self._on_second_transform_changed,
        )
        scale_row.addWidget(self._second_scale_x_spin)
        scale_row.addWidget(self._second_scale_y_spin)
        self._second_scale_lock = QCheckBox(tr("锁定"))
        self._second_scale_lock.setChecked(True)
        self._second_scale_lock.toggled.connect(
            self._on_second_scale_lock_toggled,
        )
        scale_row.addWidget(self._second_scale_lock)
        layout.addLayout(scale_row)

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel(tr("偏移:")))
        self._second_offset_x_spin = self._make_offset_spin(" X")
        self._second_offset_y_spin = self._make_offset_spin(" Y")
        self._second_offset_x_spin.valueChanged.connect(
            self._on_second_transform_changed,
        )
        self._second_offset_y_spin.valueChanged.connect(
            self._on_second_transform_changed,
        )
        offset_row.addWidget(self._second_offset_x_spin)
        offset_row.addWidget(self._second_offset_y_spin)
        layout.addLayout(offset_row)

        action_row = QHBoxLayout()
        pick_button = QPushButton(tr("浏览…"))
        pick_button.clicked.connect(self._on_pick_second)
        action_row.addWidget(pick_button)
        self._edit_second_btn = QPushButton(tr("✎ 编辑这张"))
        self._edit_second_btn.clicked.connect(self._on_edit_second)
        self._edit_second_btn.setEnabled(False)
        action_row.addWidget(self._edit_second_btn)
        clear_button = QPushButton(tr("清空"))
        clear_button.clicked.connect(self._on_clear_second)
        action_row.addWidget(clear_button)
        action_row.addStretch()
        layout.addLayout(action_row)

        layout.addWidget(QLabel(tr("混合模式:")))
        self._blend_combo = QComboBox()
        for mode_id, label, _function in BLEND_MODES:
            self._blend_combo.addItem(tr(label), mode_id)
        self._blend_combo.currentIndexChanged.connect(self._on_blend_changed)
        layout.addWidget(self._blend_combo)
        layout.addStretch()
        self._update_second_transform_enabled()
        return box

    @staticmethod
    def _make_percent_spin(axis: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, 800)
        spin.setValue(100)
        spin.setSuffix(f"%{axis}")
        return spin

    @staticmethod
    def _make_offset_spin(axis: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(-999999, 999999)
        spin.setSuffix(f" px{axis}")
        return spin

    def _build_color_panel(self) -> QWidget:
        box = QGroupBox(tr("调整（PS 风格）"))
        layout = QVBoxLayout(box)

        layout.addWidget(QLabel(tr("旋转（逆时针，自动扩展画布）:")))
        rotation_row = QHBoxLayout()
        self._rotation_spin = QDoubleSpinBox()
        self._rotation_spin.setRange(-180, 180)
        self._rotation_spin.setDecimals(1)
        self._rotation_spin.setSingleStep(1.0)
        self._rotation_spin.setSuffix("°")
        self._rotation_spin.valueChanged.connect(self._on_rotation)
        rotation_row.addWidget(self._rotation_spin)
        for text, delta in (("↶ 90°", 90), ("↷ 90°", -90), ("180°", 180)):
            button = QPushButton(text)
            button.clicked.connect(
                lambda _checked=False, value=delta: self._rotate_by(value),
            )
            rotation_row.addWidget(button)
        layout.addLayout(rotation_row)

        self._bright_slider, self._bright_label = self._add_slider(
            layout, tr("亮度（-100 ~ +100）:"), -100, 100, 0,
            self._on_brightness,
        )
        self._contrast_slider, self._contrast_label = self._add_slider(
            layout, tr("对比（0.0 ~ 2.0）:"), 0, 200, 100,
            self._on_contrast,
        )
        self._exposure_slider, self._exposure_label = self._add_slider(
            layout, tr("曝光（-2.0 ~ +2.0 EV）:"), -200, 200, 0,
            self._on_exposure,
        )
        self._shadows_slider, self._shadows_label = self._add_slider(
            layout, tr("阴影（-100 ~ +100）:"), -100, 100, 0,
            self._on_shadows,
        )
        self._highlights_slider, self._highlights_label = self._add_slider(
            layout, tr("高光（-100 ~ +100）:"), -100, 100, 0,
            self._on_highlights,
        )
        self._gamma_slider, self._gamma_label = self._add_slider(
            layout, tr("伽马（0.1 ~ 3.0）:"), 10, 300, 100,
            self._on_gamma,
        )
        self._saturation_slider, self._saturation_label = self._add_slider(
            layout, tr("饱和度（0.0 ~ 2.0；灰度无效）:"), 0, 200, 100,
            self._on_saturation,
        )
        self._threshold_slider, self._threshold_label = self._add_slider(
            layout, tr("阈值（0-255，-1=关）:"), -1, 255, -1,
            self._on_threshold,
        )
        self._posterize_slider, self._posterize_label = self._add_slider(
            layout, tr("色调分离（2-256 级，256=关）:"), 2, 256, 256,
            self._on_posterize,
        )
        self._invert_check = QCheckBox(tr("反相（Invert）"))
        self._invert_check.toggled.connect(self._on_invert)
        layout.addWidget(self._invert_check)
        layout.addStretch()
        self._sync_adjustment_labels()
        return box

    @staticmethod
    def _add_slider(
        layout: QVBoxLayout,
        title: str,
        minimum: int,
        maximum: int,
        value: int,
        callback,
    ) -> tuple[QSlider, QLabel]:
        layout.addWidget(QLabel(title))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.valueChanged.connect(callback)
        layout.addWidget(slider)
        label = QLabel()
        layout.addWidget(label)
        return slider, label

    def _build_curve_panel(self) -> QWidget:
        box = QGroupBox(tr("曲线（贝塞尔控制点）"))
        layout = QVBoxLayout(box)
        layout.addWidget(
            QLabel(tr("点曲线附近空白处 = 加点；双击控制点 = 删除")),
        )
        self._curve = CurveWidget()
        self._curve.lut_changed.connect(self._render_preview)
        layout.addWidget(self._curve, 1)
        presets = QHBoxLayout()
        for label, points in (
            ("原样", [(0, 0), (255, 255)]),
            ("提亮", [(0, 40), (128, 180), (255, 255)]),
            ("压暗", [(0, 0), (128, 60), (255, 200)]),
            ("高对比", [(0, 0), (64, 32), (192, 224), (255, 255)]),
            ("反转", [(0, 255), (255, 0)]),
        ):
            button = QPushButton(tr(label))
            button.clicked.connect(
                lambda _checked=False, values=points: self._curve.set_points(values),
            )
            presets.addWidget(button)
        reset_button = QPushButton(tr("重置曲线"))
        reset_button.clicked.connect(self._curve.reset)
        presets.addWidget(reset_button)
        layout.addLayout(presets)
        return box

    def _build_preview_box(
        self,
        title: str,
        array: np.ndarray,
        name: str,
    ) -> QWidget:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        scroll = PannableScrollArea()
        scroll.setStyleSheet("QScrollArea { background:#222; }")
        scroll.set_base_pixmap(self._arr_to_pixmap(array))
        scroll.zoom_changed.connect(self._update_zoom_label)
        layout.addWidget(scroll, 1)
        setattr(self, f"{name}_scroll", scroll)
        setattr(self, f"{name}_label", scroll._lbl)
        return box

    # ------------------------------------------------------------------
    # Preview and processing
    # ------------------------------------------------------------------
    @staticmethod
    def _arr_to_pixmap(array: np.ndarray) -> QPixmap:
        display = to_display_u8(array)
        if display.ndim == 2:
            height, width = display.shape
            data = np.ascontiguousarray(display)
            image = QImage(
                data.data, width, height, width,
                QImage.Format.Format_Grayscale8,
            )
        elif display.shape[-1] >= 3:
            height, width = display.shape[:2]
            rgb = np.ascontiguousarray(display[..., :3])
            image = QImage(
                rgb.data, width, height, width * 3,
                QImage.Format.Format_RGB888,
            )
        else:
            height, width = display.shape[:2]
            data = np.ascontiguousarray(display[..., 0])
            image = QImage(
                data.data, width, height, width,
                QImage.Format.Format_Grayscale8,
            )
        return QPixmap.fromImage(image)

    def _base_for_editing(self) -> np.ndarray:
        angle = normalize_angle(self._rotation)
        if angle == 0:
            return self._original
        if (
            self._rotated_cache is None
            or self._rotated_cache_angle != angle
        ):
            self._rotated_cache = rotate_image(self._original, angle)
            self._rotated_cache_angle = angle
        return self._rotated_cache

    @staticmethod
    def _resize_array(array: np.ndarray, height: int, width: int) -> np.ndarray:
        if array.ndim == 2:
            return resize_to(array, height, width)
        return np.stack(
            [resize_to(array[..., index], height, width)
             for index in range(array.shape[-1])],
            axis=-1,
        )

    def _make_preview_proxy(self, array: np.ndarray) -> np.ndarray:
        height, width = array.shape[:2]
        longest = max(height, width)
        if longest <= self.PREVIEW_MAX_EDGE:
            return array
        scale = self.PREVIEW_MAX_EDGE / float(longest)
        return self._resize_array(
            array,
            max(1, int(round(height * scale))),
            max(1, int(round(width * scale))),
        )

    def _preview_base_for_editing(self) -> np.ndarray:
        angle = normalize_angle(self._rotation)
        if angle == 0:
            return self._preview_original
        if (
            self._preview_rotated_cache is None
            or self._preview_rotated_cache_angle != angle
        ):
            self._preview_rotated_cache = rotate_image(
                self._preview_original, angle,
            )
            self._preview_rotated_cache_angle = angle
        return self._preview_rotated_cache

    def _settings(self) -> AdjustmentSettings:
        return AdjustmentSettings(
            brightness=self._brightness,
            contrast=self._contrast,
            exposure=self._exposure,
            shadows=self._shadows,
            highlights=self._highlights,
            gamma=self._gamma,
            saturation=self._saturation,
            threshold=self._threshold,
            posterize=self._posterize,
            invert=self._invert,
            blend_id=self._blend_id,
        )

    def _current_computed(self) -> np.ndarray:
        curve_lut = None if self._curve.is_default() else self._curve.get_lut()
        return compute_adjustments(
            self._base_for_editing(),
            self._settings(),
            curve_lut=curve_lut,
            second_data=self._second_data,
        )

    def _current_preview_computed(self) -> np.ndarray:
        base = self._preview_base_for_editing()
        second = self._second_data
        if second is not None and second.shape[:2] != base.shape[:2]:
            second = self._resize_array(second, *base.shape[:2])
        curve_lut = None if self._curve.is_default() else self._curve.get_lut()
        return compute_adjustments(
            base,
            self._settings(),
            curve_lut=curve_lut,
            second_data=second,
        )

    def _render_preview(self, *_args) -> None:
        if hasattr(self, "orig_scroll"):
            self.orig_scroll.set_base_pixmap(
                self._arr_to_pixmap(self._preview_original),
            )
        if hasattr(self, "result_scroll"):
            self.result_scroll.set_base_pixmap(
                self._arr_to_pixmap(self._current_preview_computed()),
            )
        self._update_zoom_label()

    def _fit_previews(self) -> None:
        if hasattr(self, "orig_scroll"):
            self.orig_scroll.fit_to_viewport()
        if hasattr(self, "result_scroll"):
            self.result_scroll.fit_to_viewport()
        self._update_zoom_label()

    def _update_zoom_label(self, _zoom: float = 0.0) -> None:
        if not hasattr(self, "_zoom_label"):
            return
        original_zoom = (
            self.orig_scroll.zoom() * 100
            if hasattr(self, "orig_scroll")
            else 100
        )
        result_zoom = (
            self.result_scroll.zoom() * 100
            if hasattr(self, "result_scroll")
            else 100
        )
        self._zoom_label.setText(
            tr("缩放: 原图 {:.0f}% / 结果 {:.0f}%").format(original_zoom, result_zoom)
            + tr("（滚轮缩放 / 右键平移 / 双击重置）"),
        )

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._did_initial_fit:
            self._did_initial_fit = True
            QTimer.singleShot(0, self._fit_previews)

    # ------------------------------------------------------------------
    # Second image
    # ------------------------------------------------------------------
    def _on_pick_second(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, tr("选择第二张图"), "", IMAGE_OPEN_FILTER,
        )
        if path:
            self._load_second_image(Path(path))

    def _load_second_image(self, path: Path) -> None:
        try:
            array = load_image(path)
        except Exception as exc:  # noqa: BLE001
            self.status_message.emit("error", tr("第二张图加载失败: {}").format(exc))
            return
        mask = self._second_rgba_mask
        if array.ndim == 3:
            if array.shape[-1] == 4:
                rgba = array.copy()
            else:
                rgba = np.zeros(array.shape[:2] + (4,), dtype=array.dtype)
                rgba[..., :3] = array
                rgba[..., 3] = full_scale(array.dtype)
            for channel, index in zip("RGBA", range(4)):
                if not mask[channel]:
                    rgba[..., index] = 0
            rgb_float = rgba[..., :3].astype(np.float32)
            gray_float = (
                0.299 * rgb_float[..., 0]
                + 0.587 * rgb_float[..., 1]
                + 0.114 * rgb_float[..., 2]
            )
            gray = (
                np.rint(gray_float).astype(rgba.dtype)
                if rgba.dtype.kind == "u"
                else gray_float.astype(rgba.dtype)
            )
        else:
            gray = array.copy()

        self._second_path = path
        self._second_edit.setText(str(path))
        self._second_source_data = gray.copy()
        self._remap_second_image(render=False)
        selected_channels = "".join(
            channel for channel in "RGBA" if mask[channel]
        )
        self._second_drop_label.setText(
            tr("✓ {}（通道:{} / {}）").format(
                path.name, selected_channels,
                self._second_mapping_combo.currentText(),
            ),
        )
        self._edit_second_btn.setEnabled(True)
        self._render_preview()

    def _remap_second_image(self, render: bool = True) -> None:
        if self._second_source_data is None:
            self._second_data = None
        else:
            target_height, target_width = self._base_for_editing().shape[:2]
            self._second_data = map_second_to_canvas(
                self._second_source_data,
                target_height,
                target_width,
                mode=self._second_mapping_mode,
                scale_x=self._second_scale_x,
                scale_y=self._second_scale_y,
                offset_x=self._second_offset_x,
                offset_y=self._second_offset_y,
            )
        if render:
            self._render_preview()

    def _update_second_transform_enabled(self) -> None:
        if not hasattr(self, "_second_mapping_combo"):
            return
        enabled = (
            self._second_mapping_combo.currentData() or "stretch"
        ) in {"crop", "tile"}
        for widget in (
            self._second_scale_x_spin,
            self._second_scale_y_spin,
            self._second_scale_lock,
            self._second_offset_x_spin,
            self._second_offset_y_spin,
        ):
            widget.setEnabled(enabled)

    def _on_second_scale_lock_toggled(self, checked: bool) -> None:
        if checked:
            self._syncing_second_transform = True
            try:
                self._second_scale_y_spin.setValue(
                    self._second_scale_x_spin.value(),
                )
            finally:
                self._syncing_second_transform = False
        self._on_second_transform_changed()

    def _on_second_transform_changed(self, *_args) -> None:
        if self._syncing_second_transform:
            return
        sender = self.sender()
        scale_spins = {
            self._second_scale_x_spin,
            self._second_scale_y_spin,
        }
        if self._second_scale_lock.isChecked() and sender in scale_spins:
            target = (
                self._second_scale_y_spin
                if sender is self._second_scale_x_spin
                else self._second_scale_x_spin
            )
            self._syncing_second_transform = True
            try:
                target.setValue(sender.value())
            finally:
                self._syncing_second_transform = False
        self._second_mapping_mode = (
            self._second_mapping_combo.currentData() or "stretch"
        )
        self._second_scale_x = self._second_scale_x_spin.value() / 100.0
        self._second_scale_y = self._second_scale_y_spin.value() / 100.0
        self._second_offset_x = self._second_offset_x_spin.value()
        self._second_offset_y = self._second_offset_y_spin.value()
        self._update_second_transform_enabled()
        self._remap_second_image()

    def _on_second_rgba_toggled(self, *_args) -> None:
        for channel, checkbox in self._second_rgba_checks.items():
            self._second_rgba_mask[channel] = checkbox.isChecked()
        if self._second_path is not None:
            self._load_second_image(self._second_path)

    def _on_clear_second(self) -> None:
        self._second_path = None
        self._second_source_data = None
        self._second_data = None
        self._second_edit.clear()
        self._second_drop_label.setText(
            tr("📥  拖入 / 点击框体 / 用「浏览」选文件"),
        )
        self._edit_second_btn.setEnabled(False)
        self._render_preview()

    def _on_edit_second(self) -> None:
        if self._second_source_data is None:
            return
        nested = AdvancedEditorDialog(
            self,
            initial=self._second_source_data,
            title=tr("复杂编辑 - 第二张图（可再嵌套）"),
        )
        if (
            nested.exec() == QDialog.DialogCode.Accepted
            and nested.result_data is not None
        ):
            self._second_source_data = nested.result_data.copy()
            self._second_drop_label.setText(tr("✓（已嵌套编辑）"))
            self._remap_second_image()

    def _second_drag_enter(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(
            Path(url.toLocalFile()).suffix.lower() in SUPPORTED_IMAGE_EXTS
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    @staticmethod
    def _second_drag_leave(event) -> None:
        event.accept()

    def _second_drop_event(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_IMAGE_EXTS and path.exists():
                self._load_second_image(path)
                event.acceptProposedAction()
                return
        event.ignore()

    # ------------------------------------------------------------------
    # Control callbacks
    # ------------------------------------------------------------------
    def _on_rotation(self, value: float) -> None:
        self._rotation = normalize_angle(value)
        self._rotated_cache = None
        self._rotated_cache_angle = None
        self._preview_rotated_cache = None
        self._preview_rotated_cache_angle = None
        self._remap_second_image(render=False)
        self._render_preview()

    def _rotate_by(self, delta: int) -> None:
        self._rotation_spin.setValue(
            normalize_angle(self._rotation_spin.value() + delta),
        )

    def _on_brightness(self, value: int) -> None:
        self._brightness = value
        self._bright_label.setText(str(value))
        self._render_preview()

    def _on_contrast(self, value: int) -> None:
        self._contrast = value / 100.0
        self._contrast_label.setText(f"{self._contrast:.2f}")
        self._render_preview()

    def _on_exposure(self, value: int) -> None:
        self._exposure = value / 100.0
        self._exposure_label.setText(f"{self._exposure:+.2f}")
        self._render_preview()

    def _on_shadows(self, value: int) -> None:
        self._shadows = value
        self._shadows_label.setText(str(value))
        self._render_preview()

    def _on_highlights(self, value: int) -> None:
        self._highlights = value
        self._highlights_label.setText(str(value))
        self._render_preview()

    def _on_gamma(self, value: int) -> None:
        self._gamma = value / 100.0
        self._gamma_label.setText(f"{self._gamma:.2f}")
        self._render_preview()

    def _on_saturation(self, value: int) -> None:
        self._saturation = value / 100.0
        self._saturation_label.setText(f"{self._saturation:.2f}")
        self._render_preview()

    def _on_threshold(self, value: int) -> None:
        self._threshold = value
        self._threshold_label.setText(tr("关") if value < 0 else str(value))
        self._render_preview()

    def _on_posterize(self, value: int) -> None:
        self._posterize = value
        self._posterize_label.setText(
            tr("关") if value >= 256 else tr("{} 级").format(value),
        )
        self._render_preview()

    def _on_invert(self, checked: bool) -> None:
        self._invert = checked
        self._render_preview()

    def _on_blend_changed(self, index: int) -> None:
        self._blend_id = self._blend_combo.itemData(index) or "normal"
        self._render_preview()

    def _sync_adjustment_labels(self) -> None:
        self._bright_label.setText(str(self._brightness))
        self._contrast_label.setText(f"{self._contrast:.2f}")
        self._exposure_label.setText(f"{self._exposure:+.2f}")
        self._shadows_label.setText(str(self._shadows))
        self._highlights_label.setText(str(self._highlights))
        self._gamma_label.setText(f"{self._gamma:.2f}")
        self._saturation_label.setText(f"{self._saturation:.2f}")
        self._threshold_label.setText(tr("关"))
        self._posterize_label.setText(tr("关"))

    def _on_reset(self) -> None:
        self._rotation_spin.setValue(0)
        self._bright_slider.setValue(0)
        self._contrast_slider.setValue(100)
        self._exposure_slider.setValue(0)
        self._shadows_slider.setValue(0)
        self._highlights_slider.setValue(0)
        self._gamma_slider.setValue(100)
        self._saturation_slider.setValue(100)
        self._threshold_slider.setValue(-1)
        self._posterize_slider.setValue(256)
        self._invert_check.setChecked(False)
        self._curve.reset()
        self._blend_combo.setCurrentIndex(0)
        self._on_clear_second()
        self._second_mapping_combo.setCurrentIndex(0)
        self._second_scale_x_spin.setValue(100)
        self._second_scale_y_spin.setValue(100)
        self._second_scale_lock.setChecked(True)
        self._second_offset_x_spin.setValue(0)
        self._second_offset_y_spin.setValue(0)
        for checkbox in self._second_rgba_checks.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
        for channel in self._second_rgba_mask:
            self._second_rgba_mask[channel] = True
        self._render_preview()

    def accept(self) -> None:
        computed = self._current_computed()
        if self._preserved_alpha is not None:
            alpha = (
                rotate_image(self._preserved_alpha, self._rotation)
                if normalize_angle(self._rotation) != 0
                else self._preserved_alpha.copy()
            )
            self.result_data = np.dstack((computed, alpha))
        else:
            self.result_data = computed
        super().accept()


__all__ = ["AdvancedEditorDialog"]

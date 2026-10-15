"""复杂编辑器的稳定公共入口。

实现已按职责拆分；保留本模块是为了兼容现有调用方和工作区脚本。
"""
from .advanced_editor_dialog import AdvancedEditorDialog
from .advanced_editor_components import blend_modes as _blend
from .advanced_editor_components.blend_modes import BLEND_MODES, BLEND_BY_ID
from .advanced_editor_components.curves import CurveWidget, bezier_lut, catmull_rom_lut
from .advanced_editor_components.mapping import (
    SECOND_IMAGE_MAPPINGS,
    map_second_to_canvas,
)
from .advanced_editor_components.preview import (
    ClickableDropFrame,
    PannableScrollArea,
)

# 旧私有名字曾被测试和外部脚本引用，继续提供兼容别名。
_bezier_lut = bezier_lut
_catmull_rom_lut = catmull_rom_lut
_map_second_to_canvas = map_second_to_canvas
# 旧版以下划线开头的预览类,被 verify_zoom / verify_advanced_v3 引用
_PannableScrollArea = PannableScrollArea
_ClickableDropFrame = ClickableDropFrame
# 旧版混合模式函数都带 _ 前缀,verify_blend_modes 直接 import
_blend_normal = _blend.blend_normal
_blend_multiply = _blend.blend_multiply
_blend_screen = _blend.blend_screen
_blend_overlay = _blend.blend_overlay
_blend_darken = _blend.blend_darken
_blend_lighten = _blend.blend_lighten
_blend_color_dodge = _blend.blend_color_dodge
_blend_color_burn = _blend.blend_color_burn
_blend_hard_light = _blend.blend_hard_light
_blend_soft_light = _blend.blend_soft_light
_blend_difference = _blend.blend_difference
_blend_exclusion = _blend.blend_exclusion
_blend_add = _blend.blend_add
_blend_subtract = _blend.blend_subtract
_blend_divide = _blend.blend_divide

__all__ = [
    "AdvancedEditorDialog",
    "CurveWidget",
    "SECOND_IMAGE_MAPPINGS",
    "map_second_to_canvas",
    "BLEND_MODES",
    "PannableScrollArea",
    "ClickableDropFrame",
]

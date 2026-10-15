"""复杂编辑器模块边界与纯算法测试。"""
from __future__ import annotations

import unittest

import numpy as np

from src.ui.advanced_editor import (
    CurveWidget,
    _bezier_lut,
    _catmull_rom_lut,
    _map_second_to_canvas,
)
from src.ui.advanced_editor_components.adjustments import (
    AdjustmentSettings,
    compute_adjustments,
)
from src.ui.advanced_editor_components.blend_modes import BLEND_BY_ID
from src.ui.advanced_editor_components.mapping import map_second_to_canvas


class TestAdvancedEditorModuleBoundaries(unittest.TestCase):
    def test_stable_module_reexports_legacy_helpers(self):
        self.assertIs(_map_second_to_canvas, map_second_to_canvas)
        self.assertTrue(callable(_bezier_lut))
        self.assertTrue(callable(_catmull_rom_lut))
        self.assertTrue(hasattr(CurveWidget, "get_lut"))

    def test_noop_adjustment_keeps_float_hdr_exactly(self):
        source = np.array([[-0.5, 0.0, 1.0, 4.0]], dtype=np.float32)
        result = compute_adjustments(source, AdjustmentSettings())
        self.assertTrue(np.array_equal(result, source))
        self.assertIsNot(result, source)

    def test_uint16_brightness_preserves_dtype_and_uses_normalized_scale(self):
        source = np.array([[0, 32768, 65535]], dtype=np.uint16)
        result = compute_adjustments(
            source,
            AdjustmentSettings(brightness=10),
        )
        self.assertEqual(result.dtype, np.uint16)
        expected_middle = round((32768 / 65535 + 10 / 255) * 65535)
        self.assertEqual(int(result[0, 1]), expected_middle)
        self.assertEqual(int(result[0, 2]), 65535)

    def test_subtract_blend_keeps_previous_formula(self):
        base = np.array([[100.0]], dtype=np.float32)
        blend = np.array([[30.0]], dtype=np.float32)
        result = BLEND_BY_ID["subtract"](base, blend)
        self.assertEqual(float(result[0, 0]), 70.0)

    def test_curve_default_lut_is_identity(self):
        lut = _bezier_lut(
            [(0.0, 0.0, 85.0, 0.0), (255.0, 255.0, 85.0, 0.0)],
            256,
        )
        self.assertTrue(np.array_equal(lut, np.arange(256, dtype=np.float32)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

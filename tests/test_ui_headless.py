"""UI headless 端到端集成测试。

不实际 show 窗口,只构造 MainWindow,模拟用户操作,验证:
- 编辑模式:创建临时 PNG → 灌到 ChannelMap → set_map → 触发 _on_rebuild → preview 收到 RGBA
- 编辑模式:set_spec → 切到 1K → reload 后形状是 1024
- 编辑模式:export_png 写盘,文件可读
- 互转模式:载入源图 → 切源/目标格式 → 转换有结果
- 工作区:save → load 往返一致
- 拖入文件路径:assign_file 后 file_path 正确

跑法:
    cd 贴图转换
    set QT_QPA_PLATFORM=offscreen
    py tests/test_ui_headless.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保能找到 src 包
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 必须在 QApplication 之前设 offscreen
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

# 单例 QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from src.core.output_spec import OutputSpec, ResizeFilter, SizePreset
from src.core.slot import ChannelSlot, ChannelToken, Semantic, SourceType
from src.io.loader import load_image
from src.io.saver import save_image
from src.ui.app import MainWindow
from src.ui.advanced_editor import AdvancedEditorDialog, _map_second_to_canvas
from src.ui.channel_grid import ChannelGridWidget
from src.ui.output_spec_widget import OutputSpecWidget
from src.ui.slot_widget import SlotWidget
from src.ui.transcode_panel import TranscodePanelWidget


def _make_test_png(path: Path, color=(255, 128, 64, 200), size=(128, 128)) -> None:
    """写一张测试 PNG,内容是均匀 RGBA(便于读后断言)。"""
    arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    arr[..., 0] = color[0]
    arr[..., 1] = color[1]
    arr[..., 2] = color[2]
    arr[..., 3] = color[3]
    Image.fromarray(arr, mode="RGBA").save(path)


class TestUIHeadless(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="texpipe_ui_test_"))
        self.w = MainWindow()

    def tearDown(self) -> None:
        # 关闭所有子窗口,避免 Qt 警告
        self.w.close()
        self.w.deleteLater()
        # 临时目录留作调试,测试结束统一清

    # -- 1) 编辑模式:set_map + 预览 ----------------------------------
    def test_set_map_triggers_preview(self) -> None:
        received = []
        self.w.preview.show_rgba = lambda arr: received.append(arr.copy())  # type: ignore

        png = self.tmp / "src.png"
        _make_test_png(png, color=(50, 100, 150, 200), size=(64, 64))

        # 构造一个简单的 ChannelMap:R 槽文件源(roughness)
        m = self.w.channel_grid.get_map()
        m.R = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.ROUGHNESS)
        m.R.display_name = "Rgh"
        m.G = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.METALLIC)
        m.G.display_name = "Mtl"
        m.B = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.AO)
        m.A = ChannelSlot.from_solid(0, semantic=Semantic.HEIGHT, display_name="H")

        # 调小输出尺寸让 reload 快
        self.w.output_spec.set_spec(OutputSpec(size_preset=SizePreset.P512, width=512, height=512))
        # set_map 内部会触发 _on_rebuild
        self.w.channel_grid.set_map(m)
        # _on_rebuild 是 debounce 的(但 set_map 内部直接调,不走 debounce)
        self.assertGreaterEqual(len(received), 1, "preview 应至少收到 1 次")
        rgba = received[-1]
        self.assertEqual(rgba.shape, (512, 512, 4))
        self.assertEqual(int(rgba[0, 0, 0]), 50)
        self.assertEqual(int(rgba[0, 0, 1]), 50)
        self.assertEqual(int(rgba[0, 0, 2]), 50)
        self.assertEqual(int(rgba[0, 0, 3]), 0)   # height solid 0

    # -- 2) 编辑模式:set_spec 1K → reload 形状 ------------------------
    def test_spec_change_resizes(self) -> None:
        png = self.tmp / "small.png"
        _make_test_png(png, size=(32, 32))
        m = self.w.channel_grid.get_map()
        m.R = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.AO)
        m.G = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.ROUGHNESS)
        m.B = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.METALLIC)
        self.w.channel_grid.set_map(m)
        # 切到 1K
        self.w.output_spec.set_spec(OutputSpec(size_preset=SizePreset.P1K))
        # debounce
        self.w.channel_grid._debounce.stop()
        self.w.channel_grid._on_rebuild()
        rgba = self.w.preview._last_rgba
        self.assertIsNotNone(rgba)
        self.assertEqual(rgba.shape, (1024, 1024, 4))

    # -- 3) 编辑模式:export_png 写盘 ----------------------------------
    def test_export_png(self) -> None:
        png = self.tmp / "src.png"
        _make_test_png(png, color=(10, 20, 30, 40), size=(64, 64))
        m = self.w.channel_grid.get_map()
        m.R = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.ROUGHNESS)
        m.G = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.METALLIC)
        m.B = ChannelSlot.from_file(png, token=ChannelToken.R, semantic=Semantic.AO)
        self.w.output_spec.set_spec(OutputSpec(size_preset=SizePreset.P512))
        self.w.channel_grid.set_map(m)
        self.w.channel_grid._on_rebuild()

        out = self.tmp / "out.png"
        self.w.channel_grid.export_png(out)
        self.assertTrue(out.exists())
        # 读回来验证大小
        loaded = load_image(out)
        self.assertEqual(loaded.shape, (512, 512, 4))

    def test_uint16_import_edit_pipeline_and_png_export(self) -> None:
        source = np.array(
            [
                [[0, 1000, 2000, 65535], [3000, 4000, 5000, 6000]],
                [[65535, 32768, 16384, 8192], [7, 11, 13, 17]],
            ],
            dtype=np.uint16,
        )
        src_path = self.tmp / "source16.png"
        out_path = self.tmp / "packed16.png"
        save_image(source, src_path)

        self.w.channel_grid._load_rgba_from_path(src_path)
        packed = self.w.channel_grid.get_map()
        self.assertEqual(packed.R.data.dtype, np.uint16)
        self.assertEqual(packed.G.data.dtype, np.uint16)
        self.w.channel_grid.export_png(out_path)

        loaded = load_image(out_path)
        self.assertEqual(loaded.dtype, np.uint16)
        self.assertTrue(np.array_equal(loaded, source))

    # -- 4) SlotWidget:assign_file 行为 --------------------------------
    def test_slot_widget_assign_file(self) -> None:
        sw: SlotWidget = self.w.channel_grid.slot_widgets["R"]
        png = self.tmp / "r.png"
        _make_test_png(png, size=(48, 48))
        sw._assign_file(png)
        self.assertEqual(sw._slot.file_path, png)
        self.assertEqual(sw._slot.source_type, SourceType.FILE)
        # 路径出现在 UI 上
        self.assertEqual(sw.file_edit.text(), str(png))

    # -- 5) 工作区 save → load 往返 ------------------------------------
    def test_workspace_roundtrip(self) -> None:
        png = self.tmp / "src.png"
        _make_test_png(png, size=(64, 64))
        m = self.w.channel_grid.get_map()
        m.R = ChannelSlot.from_file(png, token=ChannelToken.INV_R, semantic=Semantic.ROUGHNESS,
                                     display_name="Rgh")
        m.G = ChannelSlot.from_solid(200, semantic=Semantic.METALLIC, display_name="M")
        spec = OutputSpec(size_preset=SizePreset.P2K, resize_filter=ResizeFilter.BICUBIC)
        self.w.output_spec.set_spec(spec)
        self.w.channel_grid.set_map(m)

        ws = self.tmp / "ws.json"
        data = {
            "map": self.w.channel_grid.get_map().to_dict(),
            "spec": self.w.channel_grid.get_spec().to_dict(),
        }
        ws.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 重新解析
        d2 = json.loads(ws.read_text(encoding="utf-8"))
        m2 = self.w.channel_grid.get_map()  # reset
        from src.core.map import ChannelMap
        new_m = ChannelMap.from_dict(d2["map"])
        new_spec = OutputSpec.from_dict(d2["spec"])
        self.w.output_spec.set_spec(new_spec)
        self.w.channel_grid.set_map(new_m)
        # 校验
        m3 = self.w.channel_grid.get_map()
        self.assertEqual(m3.R.semantic, Semantic.ROUGHNESS)
        self.assertEqual(m3.R.display_name, "Rgh")
        self.assertEqual(m3.R.token, ChannelToken.INV_R)
        self.assertEqual(m3.G.semantic, Semantic.METALLIC)
        self.assertEqual(int(m3.G.solid_value), 200)
        s3 = self.w.channel_grid.get_spec()
        self.assertEqual(s3.size_preset, SizePreset.P2K)

    # -- 6) 互转模式:载入 + 转换 --------------------------------------
    def test_transcode_panel(self) -> None:
        png = self.tmp / "orm.png"
        # 模拟 ORM:R=AO G=Rough B=Metallic A=Height
        arr = np.zeros((64, 64, 4), dtype=np.uint8)
        arr[..., 0] = 200  # AO
        arr[..., 1] = 150  # Roughness
        arr[..., 2] = 100  # Metallic
        arr[..., 3] = 50   # Height
        Image.fromarray(arr, mode="RGBA").save(png)

        panel: TranscodePanelWidget = self.w.transcode_panel
        # 模拟载入
        panel._src_arr = load_image(png)
        if panel._src_arr.ndim == 2:
            rgba = np.zeros(panel._src_arr.shape + (4,), dtype=np.uint8)
            rgba[..., 0] = panel._src_arr
            rgba[..., 3] = 255
            panel._src_arr = rgba
        elif panel._src_arr.shape[-1] == 3:
            rgba = np.zeros(panel._src_arr.shape[:2] + (4,), dtype=np.uint8)
            rgba[..., :3] = panel._src_arr
            rgba[..., 3] = 255
            panel._src_arr = rgba
        panel._refresh()
        panel.src_fmt.setCurrentIndex(panel.src_fmt.findText("orm"))
        panel.dst_fmt.setCurrentIndex(panel.dst_fmt.findText("rma"))
        panel._refresh()
        out = panel.dst_preview._arr
        self.assertIsNotNone(out)
        self.assertEqual(out[0, 0].tolist(), [150, 100, 200])

        export_path = self.tmp / "rma.png"
        with patch(
            "src.ui.transcode_panel.QFileDialog.getSaveFileName",
            return_value=(str(export_path), "PNG (*.png)"),
        ):
            panel._on_export()
        self.assertTrue(export_path.exists())
        self.assertEqual(load_image(export_path)[0, 0].tolist(), [150, 100, 200])

    # -- 7) 互转模式:输出 RMA 后 R 通道 = 原 ORM G 通道(150) --------
    def test_transcode_orm_to_rma(self) -> None:
        from src.core.presets import get_preset
        from src.core.transcoder import transcode_between_presets
        arr = np.zeros((8, 8, 4), dtype=np.uint8)
        arr[..., 0] = 200  # ORM: R=AO
        arr[..., 1] = 150  # ORM: G=Rough
        arr[..., 2] = 100  # ORM: B=Metal
        arr[..., 3] = 50   # ORM: A=unused/Height
        out = transcode_between_presets(arr, get_preset("orm"), get_preset("rmah"))
        # RMA: R=Rough(=150), G=Metal(=100), B=AO(=200)
        self.assertEqual(int(out[0, 0, 0]), 150)
        self.assertEqual(int(out[0, 0, 1]), 100)
        self.assertEqual(int(out[0, 0, 2]), 200)
        self.assertEqual(int(out[0, 0, 3]), 50)

    def test_extracted_pixels_survive_rebuild_undo_and_redo(self) -> None:
        spec = OutputSpec(width=8, height=8, size_preset=SizePreset.CUSTOM)
        self.w.channel_grid.set_spec(spec)
        self.w.channel_grid._debounce.stop()
        self.w.channel_grid._on_rebuild()
        self.w.channel_grid.reset_history()

        m = self.w.channel_grid.get_map()
        slot = ChannelSlot(
            semantic=Semantic.ROUGHNESS,
            source_type=SourceType.EXTRACTED,
            token=ChannelToken.R,
        )
        slot.source_data = np.full((8, 8), 77, dtype=np.uint8)
        slot.data = slot.source_data.copy()
        m.R = slot
        self.w.channel_grid.set_map(m, new_baseline=False)
        self.assertEqual(int(self.w.channel_grid.get_map().R.data[0, 0]), 77)

        self.assertTrue(self.w.channel_grid.undo())
        self.assertTrue(self.w.channel_grid.get_map().R.is_empty())
        self.assertTrue(self.w.channel_grid.redo())
        self.assertEqual(int(self.w.channel_grid.get_map().R.data[0, 0]), 77)

    def test_workspace_sidecar_and_spec_reverse_sync(self) -> None:
        spec = OutputSpec(width=7, height=5, size_preset=SizePreset.CUSTOM)
        self.w.channel_grid.set_spec(spec)
        self.assertEqual(self.w.output_spec.width_spin.value(), 7)
        self.assertEqual(self.w.output_spec.height_spin.value(), 5)

        m = self.w.channel_grid.get_map()
        slot = ChannelSlot(
            semantic=Semantic.HEIGHT,
            source_type=SourceType.EXTRACTED,
            token=ChannelToken.R,
        )
        slot.source_data = np.full((5, 7), 123, dtype=np.uint8)
        slot.data = slot.source_data.copy()
        m.A = slot
        self.w.channel_grid.set_map(m)

        project_dir = self.tmp / "edited_project"
        project_dir.mkdir()
        with patch(
            "src.ui.channel_grid.QFileDialog.getExistingDirectory",
            return_value=str(project_dir),
        ):
            self.w.channel_grid._on_save_workspace()
        manifest = project_dir / "project.json"
        sidecar = project_dir / "assets" / "state" / "A.npy"
        self.assertTrue(manifest.exists())
        self.assertTrue(sidecar.exists())

        self.w.channel_grid.set_map(self.w.channel_grid.get_map().__class__())
        with patch(
            "src.ui.channel_grid.QFileDialog.getOpenFileName",
            return_value=(str(manifest), "Texpipe Project (project.json)"),
        ):
            self.w.channel_grid._on_load_workspace()
        self.assertEqual(int(self.w.channel_grid.get_map().A.data[0, 0]), 123)
        self.assertEqual(self.w.output_spec.get_spec().effective_size(), (7, 5))

    def test_advanced_editor_preserves_rgba_alpha_and_loads_second_image(self) -> None:
        rgba = np.zeros((6, 4, 4), dtype=np.uint8)
        rgba[..., :3] = 100
        rgba[..., 3] = np.arange(6, dtype=np.uint8)[:, None]
        dlg = AdvancedEditorDialog(initial=rgba)
        dlg._brightness = 10

        second = self.tmp / "second.png"
        _make_test_png(second, size=(2, 3))
        dlg._load_second_image(second)
        self.assertEqual(dlg._second_data.shape, (6, 4))

        dlg._second_data = None
        dlg.accept()
        self.assertEqual(dlg.result_data.shape, (6, 4, 4))
        self.assertTrue(np.array_equal(dlg.result_data[..., 3], rgba[..., 3]))
        self.assertTrue(np.all(dlg.result_data[..., :3] == 110))

    def test_advanced_editor_preserves_uint16_and_rotates_rgba(self) -> None:
        rgba = np.zeros((2, 3, 4), dtype=np.uint16)
        rgba[..., :3] = np.arange(18, dtype=np.uint16).reshape(2, 3, 3) * 3000
        rgba[..., 3] = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint16)
        dlg = AdvancedEditorDialog(initial=rgba)
        dlg._rotation_spin.setValue(90)
        dlg.accept()
        self.assertEqual(dlg.result_data.dtype, np.uint16)
        self.assertEqual(dlg.result_data.shape, (3, 2, 4))
        self.assertTrue(np.array_equal(dlg.result_data, np.rot90(rgba)))

    def test_advanced_editor_float_noop_keeps_hdr_values(self) -> None:
        source = np.array([[0.0, 1.0, 2.0, 4.0]], dtype=np.float32)
        dlg = AdvancedEditorDialog(initial=source)
        dlg.accept()
        self.assertEqual(dlg.result_data.dtype, np.float32)
        self.assertTrue(np.array_equal(dlg.result_data, source))

    def test_second_image_crop_offset_and_tile_mapping(self) -> None:
        source = np.array(
            [
                [10, 20, 30, 40],
                [50, 60, 70, 80],
            ],
            dtype=np.uint8,
        )
        centered = _map_second_to_canvas(source, 2, 2, mode="crop")
        shifted = _map_second_to_canvas(
            source, 2, 2, mode="crop", offset_x=1,
        )
        self.assertTrue(np.array_equal(centered, source[:, 1:3]))
        self.assertTrue(np.array_equal(shifted, source[:, :2]))

        tile_source = np.array([[1, 2]], dtype=np.uint8)
        tiled = _map_second_to_canvas(tile_source, 2, 5, mode="tile")
        shifted_tile = _map_second_to_canvas(
            tile_source, 2, 5, mode="tile", offset_x=1,
        )
        self.assertEqual(tiled[0].tolist(), [1, 2, 1, 2, 1])
        self.assertEqual(shifted_tile[0].tolist(), [2, 1, 2, 1, 2])

        contain_source = np.full((1, 2), 100, dtype=np.uint8)
        contained = _map_second_to_canvas(
            contain_source, 4, 4, mode="contain",
        )
        stretched = _map_second_to_canvas(
            contain_source, 4, 4, mode="stretch",
        )
        self.assertTrue(np.all(contained[[0, 3], :] == 0))
        self.assertTrue(np.all(contained[1:3, :] == 100))
        self.assertTrue(np.all(stretched == 100))

    def test_second_image_mapping_controls_remap_from_source(self) -> None:
        dlg = AdvancedEditorDialog(initial=np.zeros((2, 5), dtype=np.uint8))
        second = self.tmp / "tile.png"
        rgba = np.zeros((1, 2, 4), dtype=np.uint8)
        rgba[..., 0] = np.array([[10, 20]], dtype=np.uint8)
        rgba[..., 3] = 255
        Image.fromarray(rgba, mode="RGBA").save(second)
        dlg._second_rgba_checks["G"].setChecked(False)
        dlg._second_rgba_checks["B"].setChecked(False)
        dlg._load_second_image(second)

        tile_index = dlg._second_mapping_combo.findData("tile")
        dlg._second_mapping_combo.setCurrentIndex(tile_index)
        self.assertEqual(dlg._second_source_data.shape, (1, 2))
        self.assertEqual(dlg._second_data.shape, (2, 5))
        self.assertEqual(dlg._second_data[0].tolist(), [3, 6, 3, 6, 3])

        dlg._second_offset_x_spin.setValue(1)
        self.assertEqual(dlg._second_data[0].tolist(), [6, 3, 6, 3, 6])
        dlg._second_scale_x_spin.setValue(200)
        self.assertEqual(dlg._second_scale_y_spin.value(), 200)
        dlg._second_scale_lock.setChecked(False)
        dlg._second_scale_y_spin.setValue(50)
        self.assertEqual(dlg._second_scale_x_spin.value(), 200)
        self.assertEqual(dlg._second_scale_y_spin.value(), 50)

    def test_slot_advanced_editor_uses_uncropped_source_size(self) -> None:
        """复杂编辑应拿到完整源通道，而不是 OutputSpec 裁切后的 data。"""
        source = np.zeros((4, 12, 4), dtype=np.uint8)
        source[..., 0] = np.arange(12, dtype=np.uint8)[None, :]
        source[..., 3] = 255
        path = self.tmp / "wide.png"
        Image.fromarray(source, mode="RGBA").save(path)

        spec = OutputSpec(width=8, height=8, size_preset=SizePreset.CUSTOM)
        self.w.channel_grid.set_spec(spec)
        m = self.w.channel_grid.get_map()
        m.R = ChannelSlot.from_file(
            path,
            token=ChannelToken.R,
            semantic=Semantic.ROUGHNESS,
        )
        self.w.channel_grid.set_map(m)
        slot = self.w.channel_grid.get_map().R
        self.assertEqual(slot.data.shape, (8, 8))

        sw: SlotWidget = self.w.channel_grid.slot_widgets["R"]
        editor_input = sw._advanced_initial_data()
        self.assertIsNotNone(editor_input)
        self.assertEqual(editor_input.shape, (4, 12))
        self.assertTrue(np.array_equal(editor_input, source[..., 0]))

    def test_advanced_editor_initial_preview_fits_large_wide_texture(self) -> None:
        dlg = AdvancedEditorDialog(initial=np.zeros((512, 4096), dtype=np.uint8))
        dlg.show()
        _app.processEvents()
        dlg._fit_previews()
        self.assertLess(dlg.orig_scroll.zoom(), 1.0)
        self.assertLessEqual(dlg.orig_scroll._lbl.width(), dlg.orig_scroll.viewport().width())
        self.assertLessEqual(dlg.orig_scroll._lbl.height(), dlg.orig_scroll.viewport().height())
        dlg.close()

    def test_advanced_editor_uses_proxy_but_applies_full_resolution(self) -> None:
        source = np.zeros((512, 2048), dtype=np.uint16)
        dlg = AdvancedEditorDialog(initial=source)
        self.assertEqual(dlg._preview_original.shape, (256, 1024))
        dlg._brightness = 10
        self.assertEqual(dlg._current_preview_computed().shape, (256, 1024))
        self.assertEqual(dlg._current_computed().shape, source.shape)
        dlg.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)

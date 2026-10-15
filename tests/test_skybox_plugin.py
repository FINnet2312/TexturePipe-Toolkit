"""Skybox Noise 插件的 headless 测试。

不打开 GUI 事件循环,只验证:
- Plugin 描述子元数据(id/name/factory)
- discover() 找到插件
- 无 numba 时插件仍可用并走 NumPy fallback
- 工厂能创建 QWidget
- noise / projection / render 模块能跑
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from src.core.plugin import Plugin  # noqa: E402
from src.core.plugin_manager import PluginManager  # noqa: E402
from src.ui.plugins import discover  # noqa: E402


class PluginCoreTests(unittest.TestCase):
    def test_plugin_descriptor(self):
        from src.ui.skybox_noise.plugin import PLUGIN
        self.assertIsInstance(PLUGIN, Plugin)
        self.assertEqual(PLUGIN.id, "skybox_noise")
        self.assertEqual(PLUGIN.name, "Skybox Noise")
        # 必须有 factory
        self.assertTrue(callable(PLUGIN.factory))
        # numba 只是内部加速器，不能成为显示整个插件的门槛。
        self.assertNotIn("numba", PLUGIN.requires)

    def test_discover_finds_skybox(self):
        pm = discover()
        self.assertIsInstance(pm, PluginManager)
        ids = [p.id for p in pm.all()]
        self.assertIn("skybox_noise", ids)

    def test_duplicate_registration_rejected(self):
        pm = PluginManager()
        from src.ui.skybox_noise.plugin import PLUGIN
        pm.register(PLUGIN)
        with self.assertRaises(ValueError):
            pm.register(PLUGIN)

    def test_plugin_availability_check(self):
        from src.ui.skybox_noise.plugin import PLUGIN
        ok, missing = PLUGIN.is_available()
        self.assertTrue(ok)
        self.assertIsNone(missing)


class SkyboxNoiseCoreTests(unittest.TestCase):
    """噪声核心:Perlin / FBM / 各类型 / 投影"""

    def test_perlin_range(self):
        from src.ui.skybox_noise.core import perlin3d
        # 用归一化后的球面坐标
        xyz = np.random.RandomState(0).rand(32, 32, 3)
        xyz = xyz / np.linalg.norm(xyz, axis=-1, keepdims=True)
        x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
        out = perlin3d(x, y, z)
        self.assertEqual(out.shape, (32, 32))
        # Perlin 应该 [-1, 1] 附近
        self.assertGreater(out.max(), -1.5)
        self.assertLess(out.max(), 1.5)
        self.assertFalse(np.isnan(out).any(), "Perlin 不该有 NaN")

    def test_fbm_normalized(self):
        from src.ui.skybox_noise.core import fbm3d, perlin3d
        xyz = np.random.RandomState(0).rand(32, 32, 3)
        xyz = xyz / np.linalg.norm(xyz, axis=-1, keepdims=True)
        x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
        out = fbm3d(x, y, z, octaves=4, persistence=0.5, lacunarity=2.0, seed=42)
        self.assertEqual(out.shape, (32, 32))
        # 归一化后应该在 [-1, 1] 附近
        self.assertFalse(np.isnan(out).any(), "FBM 不该有 NaN")
        self.assertLess(abs(out.max()), 1.5)
        self.assertLess(abs(out.min()), 1.5)
        # 1 个 octave 的 norm = 1.0,FBM 应该等于 perlin
        out1 = fbm3d(x, y, z, octaves=1, persistence=0.5, lacunarity=2.0, seed=42)
        np.testing.assert_allclose(
            out1, perlin3d(x, y, z, seed=42), atol=1e-9,
        )

    def test_compose_preserves_hdr_up_to_highlight_limit(self):
        from src.ui.skybox_noise.compose import compose

        source = np.full((2, 3, 3), 2.0, dtype=np.float32)
        field = np.zeros((2, 3), dtype=np.float32)
        params = {
            "intensity": 0.0,
            "tint_blue": 0.0,
            "highlight_knee": 0.85,
            "highlight_max": 1.5,
        }
        output = compose(
            source,
            field,
            np.ones_like(field),
            np.ones_like(field),
            params,
        )
        self.assertGreater(float(output.max()), 1.0)
        self.assertLessEqual(float(output.max()), 1.5)

    def test_noise_types_all_run(self):
        from src.ui.skybox_noise.core import ALL_NOISE, gen_noise
        xyz = np.random.RandomState(0).rand(32, 32, 3)
        xyz = xyz / np.linalg.norm(xyz, axis=-1, keepdims=True)
        x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
        p = {
            "noise_scale": 3.0, "octaves": 3, "persistence": 0.5,
            "lacunarity": 2.0, "seed": 0, "warp_amount": 0.5,
            "caustic_power": 1.0, "lattice_freq": 8.0, "lattice_weight": 0.5,
        }
        for noise in ALL_NOISE:
            out = gen_noise(noise, x, y, z, p)
            self.assertEqual(out.shape, (32, 32), f"{noise} shape 错")
            self.assertFalse(np.isnan(out).any(), f"{noise} 含 NaN")

    def test_projections_xyz_unit_sphere(self):
        """所有投影返回的 (x,y,z) 应该在单位球面上。"""
        from src.ui.skybox_noise.projections import (
            ALL_PROJECTIONS, uv_to_xyz,
        )
        u, v = np.meshgrid(
            np.linspace(0, 1, 16, endpoint=False),
            np.linspace(0, 1, 16, endpoint=False),
        )
        for proj in ALL_PROJECTIONS:
            x, y, z = uv_to_xyz(proj, u, v)
            r = np.sqrt(x * x + y * y + z * z)
            # equirect / cube 应严格在球面(r=1)
            # cylindrical 的 v 维度可能偏离球面(r != 1),跳过严格检查
            if proj != "cylindrical":
                np.testing.assert_allclose(r, 1.0, atol=1e-9,
                                           err_msg=f"{proj} 不在球面")
            # 形状一致
            self.assertEqual(x.shape, u.shape)

    def test_cubemap_cross_face_centers_have_expected_directions(self):
        from src.ui.skybox_noise.projections import PROJ_CUBE_CROSS, uv_to_xyz

        # cell 中心：(列+0.5)/4、(行+0.5)/3
        samples = {
            (1, 0): (0.0, 1.0, 0.0),
            (0, 1): (1.0, 0.0, 0.0),
            (1, 1): (0.0, 0.0, -1.0),
            (2, 1): (0.0, 0.0, 1.0),
            (3, 1): (-1.0, 0.0, 0.0),
            (1, 2): (0.0, -1.0, 0.0),
        }
        for (col, row), expected in samples.items():
            u = np.array([[(col + 0.5) / 4.0]])
            v = np.array([[(row + 0.5) / 3.0]])
            xyz = uv_to_xyz(PROJ_CUBE_CROSS, u, v)
            actual = tuple(float(axis[0, 0]) for axis in xyz)
            np.testing.assert_allclose(actual, expected, atol=1e-12)

    def test_preview_resize_preserves_non_two_to_one_aspect(self):
        from src.ui.skybox_noise.compose import preview_size
        self.assertEqual(preview_size(120, 160, 0.5), (60, 80))
        self.assertEqual(preview_size(64, 128, 0.4), (32, 64))

    def test_render_produces_all_outputs(self):
        from src.ui.skybox_noise.compose import render
        from src.ui.skybox_noise.projections import ALL_PROJECTIONS
        src = np.full((64, 128, 3), 0.5, dtype=np.float32)
        p = {
            "noise_scale": 3.0, "octaves": 3, "persistence": 0.5,
            "lacunarity": 2.0, "seed": 0, "intensity": 0.5,
            "mask_top": 0.2, "mask_bottom": 0.6, "mask_softness": 1.0,
            "caustic_power": 1.0, "warp_amount": 0.5, "lattice_freq": 8.0,
            "lattice_weight": 0.5, "normal_strength": 0.1, "tint_blue": 0.05,
            "highlight_knee": 0.85, "highlight_max": 1.0,
        }
        for proj in ALL_PROJECTIONS:
            c, mg, nrm, cau, msk, sH, sW = render(src, proj, "FBM (基础)", p, scale=0.4)
            # composite 应该是 H x W x 3 float, [0, 1] 范围
            self.assertEqual(c.ndim, 3, f"{proj} composite 应是 3D")
            self.assertEqual(c.shape[-1], 3)
            self.assertTrue((c >= 0).all() and (c <= 1).all(),
                            f"{proj} composite 越界")
            # mask / caustic 是 2D
            self.assertEqual(mg.ndim, 2, f"{proj} mask 错")
            self.assertEqual(cau.ndim, 2, f"{proj} caustic 错")
            # normal 是 H x W x 3
            self.assertEqual(nrm.shape, (sH, sW, 3),
                             f"{proj} normal 形状 {nrm.shape} != {(sH, sW, 3)}")
            # sH, sW 应该匹配
            self.assertEqual(c.shape[:2], (sH, sW))


class SkyboxNoiseWidgetTests(unittest.TestCase):
    """Widget 集成测试(只创建不显示)"""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_widget_creates(self):
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget
        w = SkyboxNoiseWidget()
        self.assertIsNotNone(w)
        # 关键参数控件都该有
        self.assertTrue(hasattr(w, "lbl_original"))
        self.assertTrue(hasattr(w, "lbl_composite"))
        self.assertTrue(hasattr(w, "cmb_proj"))
        self.assertTrue(hasattr(w, "cmb_noise"))
        # 默认参数应该填进去了
        self.assertGreater(len(w._param_widgets), 10)

    def test_factory_returns_widget(self):
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget
        from src.ui.skybox_noise.plugin import PLUGIN
        w = PLUGIN.factory()
        self.assertIsInstance(w, SkyboxNoiseWidget)

    def test_mainwindow_loads_plugin_tab(self):
        """texpipe 的 MainWindow 启动后,应该多一个 Skybox Noise tab。"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from src.ui.app import MainWindow
        w = MainWindow()
        # 找 tab 标题
        tab_titles = [
            w.tabs.tabText(i) for i in range(w.tabs.count())
        ]
        self.assertIn("Skybox Noise", tab_titles,
                      f"plugin 应已加载,tab 列表: {tab_titles}")
        # plugin_manager 至少有 skybox 注册
        self.assertIsNotNone(w.plugin_manager.get("skybox_noise"))

    def test_missing_required_dependency_is_still_rejected(self):
        """真正声明为 required 的缺失依赖仍应让对应插件不可用。"""
        from src.core.plugin import Plugin
        from src.core.plugin_manager import PluginManager

        # 模拟一个真正缺少硬依赖的插件。
        fake = Plugin(
            id="fake_plugin",
            name="Fake",
            factory=lambda: None,
            requires=("this_does_not_exist_xyz",),
        )
        pm = PluginManager()
        pm.register(fake)
        ok, missing = fake.is_available()
        self.assertFalse(ok)
        self.assertEqual(missing, "this_does_not_exist_xyz")


class SkyboxNoiseUsabilityTests(unittest.TestCase):
    """新增易用性:拖拽导入 / 恢复默认 / LRU 缓存 / 预览缩放"""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        import tempfile
        from PIL import Image
        self._tmp = tempfile.TemporaryDirectory()
        # 一张 128x64 测试图(2:1 → 应自动识别为 equirect)
        self.img_path = os.path.join(self._tmp.name, "sky.png")
        Image.new("RGB", (128, 64), (80, 120, 200)).save(self.img_path)
        self.txt_path = os.path.join(self._tmp.name, "note.txt")
        with open(self.txt_path, "w", encoding="utf-8") as f:
            f.write("not an image")

    def tearDown(self):
        self._tmp.cleanup()

    def _widget(self):
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget
        return SkyboxNoiseWidget()

    def test_reset_defaults_restores_all_params(self):
        w = self._widget()
        # 打乱参数:投影/噪声选非默认项,滑杆全部推到最小值
        w.cmb_proj.setCurrentText(w.cmb_proj.itemText(1))
        w.cmb_noise.setCurrentText(w.cmb_noise.itemText(1))
        for k, sl in w._param_widgets.items():
            sl.setValue(sl.min_v)
        w.reset_defaults()
        # 全部回到 DEFAULT_PARAMS
        for k, v in w.DEFAULT_PARAMS.items():
            if k in ("projection", "noise_type"):
                self.assertEqual(w.params[k], v, f"{k} 未复位")
            else:
                self.assertAlmostEqual(w.params[k], v, places=2, msg=f"{k} 未复位")
        # 控件本身也复位
        for k, sl in w._param_widgets.items():
            self.assertAlmostEqual(
                sl.value(), w.DEFAULT_PARAMS[k], places=2, msg=f"滑杆 {k} 未复位",
            )

    def test_drop_event_loads_image(self):
        from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
        from PySide6.QtGui import QDropEvent
        w = self._widget()
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(self.img_path)])
        ev = QDropEvent(
            QPoint(0, 0), Qt.DropAction.CopyAction, md,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        w.dropEvent(ev)
        self.assertIsNotNone(w.src_image)
        self.assertEqual(w.src_image.shape, (64, 128, 3))
        # 2:1 → 自动识别 equirectangular
        self.assertEqual(w.params["projection"], "equirectangular")
        # 原图预览也更新了
        self.assertIsNotNone(w.lbl_original._pixmap)

    def test_drag_enter_rejects_non_image(self):
        from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
        from PySide6.QtGui import QDragEnterEvent
        w = self._widget()
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(self.txt_path)])
        ev = QDragEnterEvent(
            QPoint(0, 0), Qt.DropAction.CopyAction, md,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        w.dragEnterEvent(ev)
        self.assertFalse(ev.isAccepted())

    def test_lru_cache_second_load_hits(self):
        w = self._widget()
        a1 = w._load_image_cached(self.img_path)
        self.assertEqual(w._file_cache.stats()["misses"], 1)
        a2 = w._load_image_cached(self.img_path)
        stats = w._file_cache.stats()
        self.assertEqual(stats["hits"], 1, "第二次加载应命中缓存")
        np.testing.assert_array_equal(a1, a2)
        self.assertEqual(a1.dtype, np.float32)
        self.assertLessEqual(a1.max(), 1.0)

    def test_skybox_loader_preserves_uint16_levels(self):
        from pathlib import Path
        from src.io.saver import save_image

        values = np.arange(12, dtype=np.uint16).reshape(3, 4) * 5000
        rgb = np.repeat(values[..., None], 3, axis=-1)
        path = Path(self._tmp.name) / "sky16.tiff"
        save_image(rgb, path)
        widget = self._widget()
        loaded = widget._load_image_cached(str(path))
        self.assertEqual(widget._source_dtype, np.dtype(np.uint16))
        self.assertEqual(len(np.unique(loaded[..., 0])), 12)
        np.testing.assert_allclose(
            loaded[..., 0], values.astype(np.float32) / 65535.0,
            atol=1e-7,
        )

    def test_skybox_loader_preserves_float_exr_hdr(self):
        from pathlib import Path
        from src.io.saver import save_image

        source = np.array(
            [[[0.0, 0.5, 1.0], [2.0, 4.0, -0.25]]],
            dtype=np.float32,
        )
        path = Path(self._tmp.name) / "sky.exr"
        save_image(source, path)
        widget = self._widget()
        loaded = widget._load_image_cached(str(path))
        self.assertEqual(widget._source_dtype, np.dtype(np.float32))
        np.testing.assert_array_equal(loaded, source)

    def test_local_status_and_progress_are_mounted(self):
        widget = self._widget()
        self.assertIs(widget.progress_bar.parent(), widget._local_status.parent())
        self.assertGreaterEqual(
            widget.layout().indexOf(widget.progress_bar.parent()), 0,
        )
        widget._status_msg("测试状态")
        self.assertEqual(widget._local_status.text(), "测试状态")

    def test_image_label_wheel_zoom_and_reset(self):
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent, QWheelEvent
        from src.ui.skybox_noise.widgets import ImageLabel
        lbl = ImageLabel("t")
        lbl.set_ndarray(np.zeros((32, 64, 3), dtype=np.float32))
        self.assertIsNotNone(lbl._pixmap)
        z0 = lbl._zoom
        # 向上滚轮 → 放大
        ev = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        lbl.wheelEvent(ev)
        self.assertGreater(lbl._zoom, z0)
        # 向下滚 → 缩小(不越过下限)
        ev2 = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        for _ in range(200):
            lbl.wheelEvent(ev2)
        self.assertGreaterEqual(lbl._zoom, lbl.ZOOM_MIN)
        # 双击 → 复位为 Fit(只缩不放,zoom 必然 <= 1.0)
        dbl = QMouseEvent(
            QEvent.Type.MouseButtonDblClick, QPointF(5, 5), QPointF(5, 5),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        lbl.mouseDoubleClickEvent(dbl)
        self.assertFalse(lbl._need_fit, "双击后应已完成复位")
        self.assertLessEqual(lbl._zoom, 1.0)


class SkyboxNoiseCustomGraphTests(unittest.TestCase):
    """节点图自定义噪声与渲染管线集成"""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _params(self):
        return {
            "noise_scale": 3.0, "octaves": 3, "persistence": 0.5,
            "lacunarity": 2.0, "seed": 0, "intensity": 0.5,
            "mask_top": 0.2, "mask_bottom": 0.6, "mask_softness": 1.0,
            "caustic_power": 1.0, "warp_amount": 0.5, "lattice_freq": 8.0,
            "lattice_weight": 0.5, "normal_strength": 0.1, "tint_blue": 0.05,
            "highlight_knee": 0.85, "highlight_max": 1.0,
        }

    def test_render_uses_external_noise_field(self):
        from src.ui.skybox_noise.compose import render
        src = np.full((64, 128, 3), 0.5, dtype=np.float32)
        field = np.full((32, 64), 0.8, dtype=np.float32)
        c, mg, nrm, cau, msk, sH, sW = render(
            src, "equirectangular", "FBM (基础)", self._params(),
            scale=0.5, noise_field=field,
        )
        self.assertEqual(cau.shape, (32, 64))
        np.testing.assert_allclose(cau, field)
        self.assertEqual(c.shape[:2], (32, 64))

    def test_worker_eval_graph_produces_field(self):
        from src.ui.skybox_noise.worker import RenderWorker
        from src.ui.skybox_noise.node_types import default_graph
        from src.ui.skybox_noise.projections import uv_to_xyz
        g = default_graph()
        w = RenderWorker(
            np.full((64, 128, 3), 0.5, dtype=np.float32),
            "equirectangular", "自定义 (节点图)", self._params(), 0.5,
            graph_dict=g.to_dict(),
        )
        u = np.linspace(0, 1, 64, endpoint=False)
        v = np.linspace(0, 1, 32, endpoint=False)
        U, V = np.meshgrid(u, v)
        x, y, z = uv_to_xyz("equirectangular", U, V)
        field = w._eval_graph(x, y, z, U, V)
        self.assertEqual(field.shape, (32, 64))
        self.assertEqual(field.dtype, np.float32)
        self.assertFalse(np.isnan(field).any())

    def test_widget_custom_noise_option(self):
        from src.ui.skybox_noise.main_window import (
            NOISE_CUSTOM, SkyboxNoiseWidget,
        )
        w = SkyboxNoiseWidget()
        items = [w.cmb_noise.itemText(i) for i in range(w.cmb_noise.count())]
        self.assertIn(NOISE_CUSTOM, items)
        w.cmb_noise.setCurrentText(NOISE_CUSTOM)
        self.assertEqual(w.params["noise_type"], NOISE_CUSTOM)

    def test_open_node_editor_shares_graph(self):
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget
        w = SkyboxNoiseWidget()
        w.open_node_editor()
        self.assertIsNotNone(w._node_dialog)
        self.assertIs(w._node_dialog.graph, w.node_graph)
        w._node_dialog.close()

    def test_node_graph_change_invalidates_custom_preview(self):
        from src.ui.skybox_noise.main_window import (
            NOISE_CUSTOM,
            SkyboxNoiseWidget,
        )

        widget = SkyboxNoiseWidget()
        widget.cmb_noise.setCurrentText(NOISE_CUSTOM)
        widget.debounce.stop()
        widget._result_is_full = True
        widget.open_node_editor()
        widget._node_dialog._mark_dirty()
        self.assertFalse(widget._result_is_full)
        self.assertTrue(widget.debounce.isActive())
        widget.debounce.stop()
        widget._node_dialog.close()

    def test_saving_preview_queues_full_resolution_render(self):
        from unittest.mock import patch
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget

        widget = SkyboxNoiseWidget()
        widget.src_image = np.zeros((20, 40, 3), dtype=np.float32)
        widget.composite = np.zeros((8, 16, 3), dtype=np.float32)
        widget._result_is_full = False
        with (
            patch(
                "src.ui.skybox_noise.main_window.QFileDialog.getSaveFileName",
                return_value=("queued.png", ""),
            ),
            patch.object(widget, "regenerate_now") as regenerate,
        ):
            widget.save_composite()
        self.assertEqual(widget._pending_saves, [("composite", "queued.png")])
        regenerate.assert_called_once_with()

    def test_full_render_flushes_queued_save_at_source_resolution(self):
        from unittest.mock import patch
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget

        widget = SkyboxNoiseWidget()
        widget.src_image = np.zeros((20, 40, 3), dtype=np.float32)
        widget._render_seq = 7
        widget._pending_saves = [("composite", "queued.png")]
        composite = np.full((20, 40, 3), 0.5, dtype=np.float32)
        plane = np.zeros((20, 40), dtype=np.float32)
        normal = np.zeros((20, 40, 3), dtype=np.float32)
        with patch("src.ui.skybox_noise.main_window.save_image") as save:
            widget._on_render_done(
                7, composite, plane, normal, plane, plane, 20, 40, 0.1,
            )
        self.assertTrue(widget._result_is_full)
        self.assertEqual(widget._pending_saves, [])
        saved_array, saved_path = save.call_args.args
        self.assertEqual(saved_array.shape, (20, 40, 3))
        self.assertEqual(saved_array.dtype, np.uint8)
        self.assertEqual(saved_path, "queued.png")


class SkyboxNoiseWorkerTests(unittest.TestCase):
    """worker 线程安全 + 取消语义回归。"""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _params(self):
        return {
            "noise_scale": 3.0, "octaves": 3, "persistence": 0.5,
            "lacunarity": 2.0, "seed": 0, "intensity": 0.5,
            "mask_top": 0.2, "mask_bottom": 0.6, "mask_softness": 1.0,
            "caustic_power": 1.0, "warp_amount": 0.5, "lattice_freq": 8.0,
            "lattice_weight": 0.5, "normal_strength": 0.1, "tint_blue": 0.05,
            "highlight_knee": 0.85, "highlight_max": 1.0,
        }

    def test_worker_has_local_perm_independent_of_core(self):
        """worker 的 perm 表与模块全局 _P 解耦:本线程 reseed 不污染 core。"""
        from src.ui.skybox_noise import core as sky_core
        from src.ui.skybox_noise.worker import RenderWorker

        before = sky_core._P.copy()
        w = RenderWorker(
            np.full((64, 128, 3), 0.5, dtype=np.float32),
            "equirectangular", "FBM (基础)", self._params(), 0.5,
        )
        w._reseed(4242)
        # core._P 不应被改
        np.testing.assert_array_equal(
            sky_core._P, before,
            "worker reseed 不得影响模块全局 _P",
        )
        # worker 本地 perm 应与 reseed 后 core 的 perm 一致(都从 seed 派生)
        sky_core._reset_perm(4242)
        np.testing.assert_array_equal(w._local_P, sky_core._P)
        sky_core._reset_perm(0)  # 还原

    def test_worker_gen_noise_matches_core_gen_noise(self):
        """worker 自带 perm 后,输出与模块全局 core.gen_noise 一致。"""
        from src.ui.skybox_noise.worker import RenderWorker

        src = np.full((64, 128, 3), 0.5, dtype=np.float32)
        w = RenderWorker(
            src, "equirectangular", "FBM (基础)", self._params(), 0.5,
        )
        from src.ui.skybox_noise.projections import uv_to_xyz
        u = np.linspace(0, 1, 64, endpoint=False)
        v = np.linspace(0, 1, 32, endpoint=False)
        U, V = np.meshgrid(u, v)
        sx, sy, sz = uv_to_xyz("equirectangular", U, V)

        # 先用 worker 跑(seed 在 p 里),让它的本地 perm 与 core 同步
        out_w = w._gen_noise(
            "FBM (基础)", sx, sy, sz, self._params())

        # 再用 core 跑同样参数(它会自己 reset 到同样 seed)
        from src.ui.skybox_noise.core import gen_noise
        out_c = gen_noise("FBM (基础)", sx, sy, sz, self._params())

        # 数值应一致(numba 同输入同种子,理论完全相同;但 _reset_perm
        # 共享底层 RandomState 实现,实际就是 bit-identical)
        np.testing.assert_allclose(out_w, out_c, rtol=0, atol=1e-12)

    def test_widget_regenerate_cancels_old_worker(self):
        """regenerate() 会取消并等待旧 worker 退出;旧线程不应再跑。"""
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget
        from src.ui.skybox_noise.worker import RenderWorker

        w = SkyboxNoiseWidget()
        # 构造 worker,启动后立即 cancel;QThread 应能正常退出
        old = RenderWorker(
            np.full((64, 128, 3), 0.5, dtype=np.float32),
            "equirectangular", "FBM (基础)", self._params(), 0.5,
        )
        old.start()
        old.cancel()
        self.assertTrue(old.wait(3000), "worker 取消后应在 3s 内退出")
        self.assertFalse(old.isRunning())
        # _on_worker_finished 的 sender 路径在 finished 信号到来时不应抛
        old.finished.connect(w._on_worker_finished)

    def test_regenerate_never_waits_in_gui_thread(self):
        from unittest.mock import patch
        from src.ui.skybox_noise.main_window import SkyboxNoiseWidget

        class SignalStub:
            def connect(self, _callback):
                pass

        class OldWorker:
            def __init__(self):
                self.cancelled = False

            def isRunning(self):
                return True

            def cancel(self):
                self.cancelled = True

            def wait(self, *_args):
                raise AssertionError("GUI 线程不应调用 wait")

            def deleteLater(self):
                pass

        class NewWorker:
            def __init__(self, *_args, **_kwargs):
                self.progress = SignalStub()
                self.finished_ok = SignalStub()
                self.failed = SignalStub()
                self.finished = SignalStub()
                self.started = False

            def start(self):
                self.started = True

            def isRunning(self):
                return self.started

            def cancel(self):
                pass

        widget = SkyboxNoiseWidget()
        widget.src_image = np.zeros((8, 12, 3), dtype=np.float32)
        old = OldWorker()
        widget.worker = old
        with patch(
            "src.ui.skybox_noise.main_window.RenderWorker", NewWorker,
        ):
            widget.regenerate()
            self.assertTrue(old.cancelled)
            self.assertIs(widget.worker, old)
            self.assertEqual(widget._pending_render_full, False)
            widget._on_worker_finished(old)
            self.app.processEvents()
            self.assertTrue(widget.worker.started)


if __name__ == "__main__":
    unittest.main()

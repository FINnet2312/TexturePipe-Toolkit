"""节点图模型 + 求值引擎 + 节点类型 + 编辑器 UI 测试(Skybox 自定义噪声)。"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from src.ui.skybox_noise.node_graph import (  # noqa: E402
    GraphEvaluator,
    NodeGraph,
    NodeGraphError,
    PORT_COORD,
    PORT_FIELD,
)
from src.ui.skybox_noise.node_types import (  # noqa: E402
    NODE_REGISTRY,
    default_graph,
    get_node_def,
)


def make_ctx(H=32, W=64):
    u = np.linspace(0, 1, W, endpoint=False)
    v = np.linspace(0, 1, H, endpoint=False)
    U, V = np.meshgrid(u, v)
    from src.ui.skybox_noise.projections import uv_to_xyz
    x, y, z = uv_to_xyz("equirectangular", U, V)
    return {
        "xyz": np.stack([x, y, z], axis=-1).astype(np.float32),
        "uv": np.stack([U, V], axis=-1).astype(np.float32),
        "load_texture": lambda p: np.full((16, 32, 3), 0.5, dtype=np.float32),
    }


def eval_output(graph: NodeGraph) -> np.ndarray:
    ev = GraphEvaluator(graph, make_ctx(), NODE_REGISTRY)
    return ev.eval_output("output", 0)


class GraphModelTests(unittest.TestCase):
    def test_add_remove_node(self):
        g = NodeGraph()
        a = g.add_node("noise_fbm")
        b = g.add_node("output")
        self.assertEqual(len(g.nodes), 2)
        g.remove_node(a.id)
        self.assertEqual(len(g.nodes), 1)
        self.assertNotIn(a.id, g.nodes)

    def test_connect_type_mismatch_rejected(self):
        g = NodeGraph()
        src = g.add_node("coord_source")
        math = g.add_node("math")
        with self.assertRaises(NodeGraphError):
            g.connect(src.id, 0, math.id, 0, NODE_REGISTRY)  # coord→field

    def test_input_port_single_connection(self):
        g = NodeGraph()
        s1 = g.add_node("coord_source")
        s2 = g.add_node("coord_source")
        fbm = g.add_node("noise_fbm")
        g.connect(s1.id, 0, fbm.id, 0, NODE_REGISTRY)
        with self.assertRaises(NodeGraphError):
            g.connect(s2.id, 0, fbm.id, 0, NODE_REGISTRY)

    def test_cycle_rejected(self):
        g = NodeGraph()
        w1 = g.add_node("domain_warp")
        w2 = g.add_node("domain_warp")
        g.connect(w1.id, 0, w2.id, 0, NODE_REGISTRY)  # w1 → w2
        with self.assertRaises(NodeGraphError):
            g.connect(w2.id, 0, w1.id, 0, NODE_REGISTRY)  # w2 → w1 成环

    def test_three_node_cycle_rejected(self):
        """三节点环检测:有 a→b→c 时,连 c→a 必被拒(会闭环)。"""
        g = NodeGraph()
        a = g.add_node("domain_warp")
        b = g.add_node("domain_warp")
        c = g.add_node("domain_warp")
        g.connect(a.id, 0, b.id, 0, NODE_REGISTRY)
        g.connect(b.id, 0, c.id, 0, NODE_REGISTRY)
        # can_connect 语义:out→in 会成环当 out 已在 in 的下游里
        # 此时 downstream(a)={b,c},若再连 c→a(c=out,a=in),则 out=c 不在
        # downstream(a)={b,c} 中吗?c 在!所以必须被拒
        with self.assertRaises(NodeGraphError):
            g.connect(c.id, 0, a.id, 0, NODE_REGISTRY)

    def test_self_connect_rejected(self):
        g = NodeGraph()
        w = g.add_node("domain_warp")
        with self.assertRaises(NodeGraphError):
            g.connect(w.id, 0, w.id, 0, NODE_REGISTRY)

    def test_serialize_roundtrip(self):
        g = default_graph()
        fbm = [n for n in g.nodes.values() if n.type_id == "noise_fbm"][0]
        fbm.params["scale"] = 7.5
        fbm.pos = (100, 200)
        d = g.to_dict()
        g2 = NodeGraph.from_dict(d)
        self.assertEqual(g2.to_dict(), d)
        fbm2 = [n for n in g2.nodes.values() if n.type_id == "noise_fbm"][0]
        self.assertEqual(fbm2.params["scale"], 7.5)
        self.assertEqual(fbm2.pos, (100, 200))

    def test_disconnect_input(self):
        g = default_graph()
        out = [n for n in g.nodes.values() if n.type_id == "output"][0]
        self.assertEqual(len(g.connections), 2)
        g.disconnect_input(out.id, 0)
        self.assertEqual(len(g.connections), 1)

    def test_from_dict_rejects_unknown_node_and_dangling_connection(self):
        with self.assertRaises(NodeGraphError):
            NodeGraph.from_dict({
                "nodes": [{"id": "n0", "type": "missing", "pos": [0, 0]}],
                "connections": [],
            }, NODE_REGISTRY)
        with self.assertRaises(NodeGraphError):
            NodeGraph.from_dict({
                "nodes": [{"id": "n0", "type": "output", "pos": [0, 0]}],
                "connections": [["n9", 0, "n0", 0]],
            }, NODE_REGISTRY)

    def test_from_dict_rejects_duplicate_ids_and_invalid_ports(self):
        with self.assertRaises(NodeGraphError):
            NodeGraph.from_dict({
                "nodes": [
                    {"id": "n0", "type": "output", "pos": [0, 0]},
                    {"id": "n0", "type": "output", "pos": [1, 1]},
                ],
                "connections": [],
            }, NODE_REGISTRY)
        with self.assertRaises(NodeGraphError):
            NodeGraph.from_dict({
                "nodes": [
                    {"id": "n0", "type": "noise_fbm", "pos": [0, 0]},
                    {"id": "n1", "type": "output", "pos": [1, 1]},
                ],
                "connections": [["n0", 9, "n1", 0]],
            }, NODE_REGISTRY)


class GraphEvalTests(unittest.TestCase):
    def test_default_graph_evaluates(self):
        g = default_graph()
        field = eval_output(g)
        self.assertEqual(field.shape, (32, 64))
        self.assertFalse(np.isnan(field).any())

    def test_no_output_node_raises(self):
        g = NodeGraph()
        g.add_node("noise_fbm")
        with self.assertRaises(NodeGraphError):
            eval_output(g)

    def test_math_scalar_add(self):
        g = NodeGraph()
        m = g.add_node("math", params={"op": "add", "scalar": 0.25})
        out = g.add_node("output")
        g.connect(m.id, 0, out.id, 0, NODE_REGISTRY)
        field = eval_output(g)
        np.testing.assert_allclose(field, 0.25, atol=1e-6)

    def test_blend_screen_amount(self):
        g = NodeGraph()
        # 叠加输入 = 常量 1 场(screen(0, 255) = 1)
        one = g.add_node("math", params={"op": "add", "scalar": 1.0})
        b = g.add_node("blend", params={"mode": "screen", "amount": 0.6})
        out = g.add_node("output")
        g.connect(one.id, 0, b.id, 1, NODE_REGISTRY)  # B(叠加)
        g.connect(b.id, 0, out.id, 0, NODE_REGISTRY)
        # base=0, blend=1 → screen=1 → out = 0*0.4 + 1*0.6 = 0.6
        field = eval_output(g)
        np.testing.assert_allclose(field, 0.6, atol=1e-6)

    def test_remap_linear(self):
        g = NodeGraph()
        r = g.add_node("remap", params={
            "in_lo": -1.0, "in_hi": 1.0,
            "out_lo": 0.0, "out_hi": 1.0, "clamp": True,
        })
        out = g.add_node("output")
        g.connect(r.id, 0, out.id, 0, NODE_REGISTRY)
        # 输入未连接 = 0 → 映射到 0.5
        field = eval_output(g)
        np.testing.assert_allclose(field, 0.5, atol=1e-6)

    def test_adjust_contrast_clips(self):
        g = NodeGraph()
        m = g.add_node("math", params={"op": "add", "scalar": 1.0})
        a = g.add_node("adjust", params={"brightness": 0.0, "contrast": 2.0, "gamma": 1.0})
        out = g.add_node("output")
        g.connect(m.id, 0, a.id, 0, NODE_REGISTRY)
        g.connect(a.id, 0, out.id, 0, NODE_REGISTRY)
        # 1.0 → (1-0.5)*2+0.5 = 1.5 → clip 1.0
        field = eval_output(g)
        np.testing.assert_allclose(field, 1.0, atol=1e-6)

    def test_domain_warp_shape(self):
        g = NodeGraph()
        src = g.add_node("coord_source")
        warp = g.add_node("domain_warp")
        fbm = g.add_node("noise_fbm")
        out = g.add_node("output")
        g.connect(src.id, 0, warp.id, 0, NODE_REGISTRY)
        g.connect(warp.id, 0, fbm.id, 0, NODE_REGISTRY)
        g.connect(fbm.id, 0, out.id, 0, NODE_REGISTRY)
        field = eval_output(g)
        self.assertEqual(field.shape, (32, 64))
        self.assertFalse(np.isnan(field).any())

    def test_texture_node_with_real_image(self):
        with tempfile.TemporaryDirectory() as td:
            from PIL import Image
            path = os.path.join(td, "n.png")
            Image.new("L", (64, 64), 128).save(path)

            def load(p):
                arr = np.array(Image.open(p).convert("RGB"))
                return arr.astype(np.float32) / 255.0

            g = NodeGraph()
            tex = g.add_node("noise_texture", params={
                "path": path, "channel": 3, "scale": 1.0,
                "tile": True, "brightness": 0.0, "contrast": 1.0,
            })
            out = g.add_node("output")
            g.connect(tex.id, 0, out.id, 0, NODE_REGISTRY)
            ev = GraphEvaluator(g, make_ctx(), NODE_REGISTRY)
            # 灰色 128/255 ≈ 0.502
            field = ev.eval_output("output", 0)
            self.assertEqual(field.shape, (32, 64))
            np.testing.assert_allclose(field, 128 / 255.0, atol=0.02)

    def test_eval_cycle_guard(self):
        g = NodeGraph()
        a = g.add_node("math")
        b = g.add_node("math")
        out = g.add_node("output")
        # 手工构造环(绕过 connect 校验)
        g.connections.append((a.id, 0, b.id, 0))
        g.connections.append((b.id, 0, a.id, 0))
        g.connections.append((a.id, 0, out.id, 0))
        with self.assertRaises(NodeGraphError):
            eval_output(g)

    def test_unknown_node_type_raises(self):
        with self.assertRaises(KeyError):
            get_node_def("nope_xyz")

    def test_every_registered_node_has_def(self):
        for tid in NODE_REGISTRY:
            nd = get_node_def(tid)
            self.assertTrue(nd.label)
            self.assertTrue(nd.category)
            self.assertTrue(callable(nd.eval))

    def test_perlin_seed_changes_output(self):
        def make(seed):
            graph = NodeGraph()
            node = graph.add_node("noise_perlin", params={
                "scale": 3.8, "seed": seed,
            })
            output = graph.add_node("output")
            graph.connect(node.id, 0, output.id, 0, NODE_REGISTRY)
            return eval_output(graph)

        first = make(1)
        second = make(2)
        self.assertGreater(float(np.max(np.abs(first - second))), 1e-4)


class NodeEditorUiTests(unittest.TestCase):
    """节点编辑器对话框(headless)"""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        from src.ui.skybox_noise.node_editor import NodeEditorDialog
        return NodeEditorDialog(default_graph())

    def test_dialog_creates(self):
        dlg = self._dialog()
        self.assertIsNotNone(dlg)
        self.assertGreater(len(dlg._scene.items()), 0)
        dlg.close()

    def test_add_node_via_lib(self):
        dlg = self._dialog()
        before = len(dlg.graph.nodes)
        dlg._add_node("noise_perlin")
        self.assertEqual(len(dlg.graph.nodes), before + 1)
        self.assertIsNotNone(dlg._selected_node_id)
        dlg.close()

    def test_set_param_and_undo(self):
        dlg = self._dialog()
        fbm = [n for n in dlg.graph.nodes.values() if n.type_id == "noise_fbm"][0]
        dlg._select_node(fbm.id)
        dlg._set_param(fbm, "scale", 9.5, commit=True)
        self.assertEqual(dlg.graph.nodes[fbm.id].params["scale"], 9.5)
        dlg.undo()
        self.assertEqual(dlg.graph.nodes[fbm.id].params["scale"], 3.8)
        dlg.redo()
        self.assertEqual(dlg.graph.nodes[fbm.id].params["scale"], 9.5)
        dlg.close()

    def test_connect_via_ports(self):
        dlg = self._dialog()
        warp = dlg.graph.add_node("domain_warp", pos=(500, 200))
        dlg._rebuild_scene()
        fbm = [n for n in dlg.graph.nodes.values() if n.type_id == "noise_fbm"][0]
        # 把原 fbm 的坐标输入断开,换成 warp → fbm。
        # 快照式撤销只回滚"入栈的状态":绕过 UI 的直接改动需手动入栈,
        # 这样 undo 才能回到「刚断开」这一步,而不是构造时的初始图。
        dlg.graph.disconnect_input(fbm.id, 0)
        dlg._push_state()
        out_port = dlg._find_port(warp.id, 0, False)
        in_port = dlg._find_port(fbm.id, 0, True)
        self.assertIsNotNone(out_port)
        self.assertIsNotNone(in_port)
        dlg.connect_nodes(out_port, in_port)
        self.assertEqual(dlg.graph.output_of(fbm.id, 0), (warp.id, 0))
        dlg.undo()
        self.assertIsNone(dlg.graph.output_of(fbm.id, 0))
        dlg.redo()
        self.assertEqual(dlg.graph.output_of(fbm.id, 0), (warp.id, 0))
        dlg.close()

    def test_visible_port_center_is_hit_testable(self):
        dlg = self._dialog()
        fbm = next(
            node for node in dlg.graph.nodes.values()
            if node.type_id == "noise_fbm"
        )
        port = dlg._find_port(fbm.id, 0, True)
        self.assertIsNotNone(port)
        self.assertIs(dlg._scene._port_at(port.scene_pos(), True), port)
        self.assertNotEqual(port.scene_pos(), port.node_item.scenePos())
        dlg.close()

    def test_mouse_click_selects_node_and_updates_properties(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from src.ui.skybox_noise.node_editor import _NodeItem

        dlg = self._dialog()
        dlg.show()
        self.app.processEvents()
        target = next(
            item for item in dlg._scene.items()
            if isinstance(item, _NodeItem)
            and item.node.type_id == "noise_fbm"
        )
        scene_point = target.mapToScene(target.boundingRect().center())
        viewport_point = dlg._view.mapFromScene(scene_point)
        QTest.mouseClick(
            dlg._view.viewport(), Qt.MouseButton.LeftButton,
            pos=viewport_point,
        )
        self.app.processEvents()
        self.assertEqual(dlg._selected_node_id, target.node.id)
        self.assertIn("FBM", dlg._props_title.text())
        dlg.close()

    def test_delete_selected_removes_connections(self):
        dlg = self._dialog()
        fbm = [n for n in dlg.graph.nodes.values() if n.type_id == "noise_fbm"][0]
        n_conn = len(dlg.graph.connections)
        dlg._select_node(fbm.id)
        dlg._delete_selected()
        self.assertNotIn(fbm.id, dlg.graph.nodes)
        self.assertLess(len(dlg.graph.connections), n_conn)
        dlg.close()

    def test_preview_evaluates(self):
        dlg = self._dialog()
        dlg._refresh_preview()
        self.assertIsNotNone(dlg._preview_lbl._pixmap)
        dlg.close()


if __name__ == "__main__":
    unittest.main()

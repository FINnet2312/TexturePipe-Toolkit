"""节点图数据模型 + 求值引擎(Skybox 自定义噪声)。

图结构:
- 节点(Node):type_id + 参数 + 画布坐标
- 端口(Port):输出/输入,分两类:
    PORT_COORD — HxWx3 球面坐标(域扭曲/噪声源的坐标流)
    PORT_FIELD — HxW 单通道标量场(噪声值/混合/后处理)
- 连线(connection):(out_node, out_port, in_node, in_port)

求值:GraphEvaluator 从输出节点回溯,拓扑递归 + 记忆化。
连线时即拒绝:类型不匹配 / 输入端口重复连接 / 成环。
"""
from __future__ import annotations

import math

import numpy as np

PORT_COORD = "coord"   # HxWx3 球面坐标
PORT_FIELD = "field"   # HxW 单通道标量场

ALL_PORT_KINDS = (PORT_COORD, PORT_FIELD)


class Port:
    __slots__ = ("name", "kind")

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind


class Node:
    """图中的一个节点实例。"""

    __slots__ = ("id", "type_id", "pos", "params")

    def __init__(self, node_id: str, type_id: str, pos=(0, 0),
                 params: dict | None = None):
        self.id = node_id
        self.type_id = type_id
        self.pos = tuple(pos)
        self.params = dict(params or {})


class NodeGraphError(Exception):
    """节点图结构或求值错误。"""


class NodeGraph:
    """节点图:节点集合 + 连线集合。"""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        # 连线: (out_node_id, out_port_idx, in_node_id, in_port_idx)
        self.connections: list[tuple[str, int, str, int]] = []
        self._next_id = 0

    # -- 节点 ----------------------------------------------------------
    def new_id(self) -> str:
        nid = f"n{self._next_id}"
        self._next_id += 1
        return nid

    def add_node(self, type_id: str, pos=(0, 0), params: dict | None = None) -> Node:
        node = Node(self.new_id(), type_id, pos, params)
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str) -> None:
        if node_id not in self.nodes:
            return
        del self.nodes[node_id]
        self.connections = [
            c for c in self.connections
            if c[0] != node_id and c[2] != node_id
        ]

    def get_node(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise NodeGraphError(f"节点不存在: {node_id}")
        return self.nodes[node_id]

    # -- 连线 ----------------------------------------------------------
    def output_of(self, in_node_id: str, in_port_idx: int):
        """返回 (src_node_id, src_port_idx);未连接返回 None。"""
        for (o, oi, i, ii) in self.connections:
            if i == in_node_id and ii == in_port_idx:
                return (o, oi)
        return None

    def downstream(self, node_id: str) -> set:
        """从 node_id 出发沿连线方向可达的节点集合(不含自身)。"""
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            n = stack.pop()
            for (o, _oi, i, _ii) in self.connections:
                if o == n and i not in seen:
                    seen.add(i)
                    stack.append(i)
        return seen

    def can_connect(self, out_node_id: str, out_port_idx: int,
                    in_node_id: str, in_port_idx: int,
                    node_defs) -> tuple[bool, str]:
        """校验一组连线是否合法,返回 (ok, 错误原因)。"""
        if out_node_id == in_node_id:
            return False, "不能连回自己"
        if out_node_id not in self.nodes or in_node_id not in self.nodes:
            return False, "节点不存在"
        out_def = node_defs[self.nodes[out_node_id].type_id]
        in_def = node_defs[self.nodes[in_node_id].type_id]
        if out_port_idx >= len(out_def.outputs) or in_port_idx >= len(in_def.inputs):
            return False, "端口越界"
        if out_def.outputs[out_port_idx].kind != in_def.inputs[in_port_idx].kind:
            return False, "端口类型不匹配"
        if self.output_of(in_node_id, in_port_idx) is not None:
            return False, "该输入端口已有连线"
        # 成环判定:in 的下游已能到达 out,则 out→in 会闭合
        if out_node_id in self.downstream(in_node_id):
            return False, "连接会形成环路"
        return True, "ok"

    def connect(self, out_node_id: str, out_port_idx: int,
                in_node_id: str, in_port_idx: int, node_defs) -> bool:
        ok, reason = self.can_connect(
            out_node_id, out_port_idx, in_node_id, in_port_idx, node_defs)
        if not ok:
            raise NodeGraphError(reason)
        self.connections.append(
            (out_node_id, out_port_idx, in_node_id, in_port_idx))
        return True

    def disconnect(self, out_node_id: str, out_port_idx: int,
                   in_node_id: str, in_port_idx: int) -> None:
        self.connections = [
            c for c in self.connections
            if not (c == (out_node_id, out_port_idx, in_node_id, in_port_idx))
        ]

    def disconnect_input(self, in_node_id: str, in_port_idx: int) -> None:
        """断开某输入端口的所有连线(UI 重连时用)。"""
        self.connections = [
            c for c in self.connections
            if not (c[2] == in_node_id and c[3] == in_port_idx)
        ]

    # -- 序列化 --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "nodes": [
                {
                    "id": n.id, "type": n.type_id,
                    "pos": [float(n.pos[0]), float(n.pos[1])],
                    "params": dict(n.params),
                }
                for n in self.nodes.values()
            ],
            "connections": [list(c) for c in self.connections],
        }

    @classmethod
    def from_dict(cls, d: dict, node_defs=None) -> "NodeGraph":
        """从 JSON 兼容字典恢复并验证图结构。

        ``node_defs`` 传入注册表时还会验证节点类型、端口类型、重复输入和
        环路。文件加载与 worker 求值必须传入注册表；纯模型 round-trip 可
        省略它。
        """
        if not isinstance(d, dict):
            raise NodeGraphError("节点图根对象必须是 JSON object")
        raw_nodes = d.get("nodes", [])
        raw_connections = d.get("connections", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_connections, list):
            raise NodeGraphError("nodes 和 connections 必须是数组")
        g = cls()
        for nd in raw_nodes:
            if not isinstance(nd, dict):
                raise NodeGraphError("节点条目必须是 object")
            if "id" not in nd or "type" not in nd:
                raise NodeGraphError("节点缺少 id 或 type")
            node_id = str(nd["id"])
            if not node_id or node_id in g.nodes:
                raise NodeGraphError(f"节点 ID 重复或为空: {node_id!r}")
            type_id = str(nd["type"])
            if node_defs is not None and type_id not in node_defs:
                raise NodeGraphError(f"未知节点类型: {type_id}")
            pos = nd.get("pos", (0, 0))
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                raise NodeGraphError(f"节点 {node_id} 的 pos 必须是两个数字")
            try:
                pos = (float(pos[0]), float(pos[1]))
            except (TypeError, ValueError) as exc:
                raise NodeGraphError(f"节点 {node_id} 的 pos 不是数字") from exc
            if not all(math.isfinite(value) for value in pos):
                raise NodeGraphError(f"节点 {node_id} 的 pos 不能是 NaN/Inf")
            params = nd.get("params") or {}
            if not isinstance(params, dict):
                raise NodeGraphError(f"节点 {node_id} 的 params 必须是 object")
            node = Node(node_id, type_id, pos, params)
            g.nodes[node.id] = node
            try:
                g._next_id = max(g._next_id, int(node.id[1:]) + 1)
            except (ValueError, IndexError):
                pass
        seen_connections = set()
        for c in raw_connections:
            if not isinstance(c, (list, tuple)) or len(c) != 4:
                raise NodeGraphError("每条连接必须包含四个字段")
            try:
                connection = (str(c[0]), int(c[1]), str(c[2]), int(c[3]))
            except (TypeError, ValueError) as exc:
                raise NodeGraphError(f"非法连接: {c!r}") from exc
            if connection in seen_connections:
                raise NodeGraphError(f"重复连接: {connection!r}")
            if connection[0] not in g.nodes or connection[2] not in g.nodes:
                raise NodeGraphError(f"连接引用不存在的节点: {connection!r}")
            if connection[1] < 0 or connection[3] < 0:
                raise NodeGraphError(f"连接端口不能为负数: {connection!r}")
            if node_defs is None:
                g.connections.append(connection)
            else:
                try:
                    g.connect(*connection, node_defs)
                except (KeyError, IndexError, NodeGraphError) as exc:
                    raise NodeGraphError(f"非法连接 {connection!r}: {exc}") from exc
            seen_connections.add(connection)
        return g


class GraphEvaluator:
    """从输出节点回溯求值,带记忆化与循环保护。

    ctx: 渲染上下文,提供:
        - "xyz": HxWx3 球面坐标
        - "uv":  HxWx2 UV 坐标
        - "load_texture": callable(path) -> float32 [0,1] HxWx3
    """

    def __init__(self, graph: NodeGraph, ctx: dict, node_defs: dict):
        self.graph = graph
        self.ctx = ctx
        self.node_defs = node_defs
        self.memo: dict[str, list] = {}
        self.stack: set[str] = set()

    def output_of(self, in_node_id: str, in_port_idx: int):
        return self.graph.output_of(in_node_id, in_port_idx)

    def eval_node(self, node_id: str) -> list:
        if node_id in self.memo:
            return self.memo[node_id]
        if node_id in self.stack:
            raise NodeGraphError("检测到循环依赖")
        node = self.graph.get_node(node_id)
        try:
            node_def = self.node_defs[node.type_id]
        except KeyError as exc:
            raise NodeGraphError(f"未知节点类型: {node.type_id}") from exc
        self.stack.add(node_id)
        inputs = []
        for idx in range(len(node_def.inputs)):
            src = self.output_of(node_id, idx)
            if src is not None:
                out_vals = self.eval_node(src[0])
                inputs.append(out_vals[src[1]])
            else:
                inputs.append(None)
        # 合并默认参数:缺的补默认,已有的保留(不改原节点)
        merged = dict(node_def.default_params())
        merged.update(node.params)
        outputs = node_def.eval(merged, inputs, self.ctx)
        if not isinstance(outputs, (list, tuple)):
            outputs = [outputs]
        self.stack.discard(node_id)
        self.memo[node_id] = list(outputs)
        return self.memo[node_id]

    def eval_output(self, type_id: str = "output", port_idx: int = 0) -> np.ndarray:
        """求值并返回指定类型节点的第 port_idx 个输出(默认找 output 节点)。"""
        for nid, node in self.graph.nodes.items():
            if node.type_id == type_id:
                vals = self.eval_node(nid)
                return vals[port_idx]
        raise NodeGraphError("图中没有输出节点")


__all__ = [
    "NodeGraph", "NodeGraphError", "GraphEvaluator",
    "Port", "Node", "PORT_COORD", "PORT_FIELD",
]

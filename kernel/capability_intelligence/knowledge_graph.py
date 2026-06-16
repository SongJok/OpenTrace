"""CapabilityKnowledgeGraph — 能力间关系图。

构建 CapabilityRelation 有向图，编码依赖、互补、替代与冲突；
支持拓扑排序、路径查找、替代链与提示格式导出。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from kernel.capability_intelligence.profile import CapabilityProfile, CapabilityRelation

# ── 种子关系：将 profiler._SEED_DATA 中的隐式知识形式化 ──
# 每个元组：(from_cap, to_cap, relation_type, strength, description)

_SEED_RELATIONS: list[tuple[str, str, str, float, str]] = [
    ("data.analysis", "data.query", "depends_on", 0.95, "数据分析依赖数据查询的前置结果"),
    ("chart.generate", "data.query", "depends_on", 0.90, "图表生成依赖前置数据查询"),
    ("chart.generate", "python.execute", "depends_on", 0.60, "图表生成可依赖 Python 数据处理"),
    ("entity.resolution", "data.query", "complements", 0.70, "实体消歧提升数据查询精度"),
    ("web.search", "rag.retrieve", "complements", 0.60, "外部搜索补充内部文档检索"),
    ("memory.retrieve", "rag.retrieve", "complements", 0.50, "历史记忆补充文档检索"),
    ("web.search", "rag.retrieve", "substitutes", 0.50, "联网搜索可部分替代文档检索"),
    ("rag.retrieve", "web.search", "substitutes", 0.40, "文档检索可部分替代联网搜索"),
    ("python.execute", "data.analysis", "substitutes", 0.70, "Python 可执行自定义统计分析"),
    ("python.execute", "chart.generate", "substitutes", 0.50, "Python 可生成数据图表"),
    ("tool.calculator", "python.execute", "substitutes", 0.60, "简单计算器可替代 Python 数值运算"),
    ("tool.calculator", "python.execute", "conflicts_with", 0.30, "简单计算不应触发 Python 执行"),
    ("vision.analyze", "chart.generate", "depends_on", 0.50, "图表分析依赖图表生成"),
    ("rag.retrieve", "memory.retrieve", "substitutes", 0.60, "文档检索可补充历史记忆不足"),
    ("web.search", "tool.weather", "substitutes", 0.40, "联网搜索可获取天气信息"),
]


@dataclass
class TopologicalOrder:
    """有序执行层。同一层内的节点可并行执行。"""

    layers: list[list[str]] = field(default_factory=list)
    total_dependencies: int = 0


class CapabilityKnowledgeGraph:
    """构建与查询 CapabilityRelation 对象图。

    支持依赖查询、互补/替代查询、拓扑排序、路径查找与提示格式导出。
    """

    def __init__(self) -> None:
        self._relations: dict[tuple[str, str, str], CapabilityRelation] = {}
        # from_cap -> [(to_cap, relation_type, strength), ...]
        self._adjacency: dict[str, list[tuple[str, str, float]]] = {}
        self._built = False

    def build(self, profiles: dict[str, CapabilityProfile]) -> None:
        """从种子关系构建图。profiles 参数为未来动态关系发现预留，
        但种子关系是 Phase 2 的主要来源。"""
        if self._built:
            return

        for from_cap, to_cap, rel_type, strength, desc in _SEED_RELATIONS:
            self.add_relation(CapabilityRelation(
                from_cap=from_cap,
                to_cap=to_cap,
                relation_type=rel_type,
                strength=strength,
                description=desc,
            ))

        self._built = True

    def add_relation(self, rel: CapabilityRelation) -> None:
        key = (rel.from_cap, rel.to_cap, rel.relation_type)
        self._relations[key] = rel
        self._adjacency.setdefault(rel.from_cap, []).append(
            (rel.to_cap, rel.relation_type, rel.strength)
        )

    # ── 查询方法 ─────────────────────────────────────────────────────

    def depends_on(self, capability: str) -> list[str]:
        """`capability` 所依赖的能力列表。"""
        result: list[str] = []
        for (frm, to, rtype), rel in self._relations.items():
            if frm == capability and rtype == "depends_on":
                result.append(to)
        return sorted(result, key=lambda c: self._dep_strength(capability, c), reverse=True)

    def depended_by(self, capability: str) -> list[str]:
        """依赖于 `capability` 的能力列表。"""
        result: list[str] = []
        for (frm, to, rtype), rel in self._relations.items():
            if to == capability and rtype == "depends_on":
                result.append(frm)
        return result

    def complements(self, capability: str) -> list[str]:
        return self._related_by_type(capability, "complements")

    def substitutes_for(self, capability: str) -> list[str]:
        return self._related_by_type(capability, "substitutes")

    def conflicts_with(self, capability: str) -> list[str]:
        return self._related_by_type(capability, "conflicts_with")

    def _related_by_type(self, capability: str, rel_type: str) -> list[str]:
        result: list[str] = []
        for (frm, to, rtype), rel in self._relations.items():
            if rtype == rel_type:
                if frm == capability:
                    result.append(to)
                elif to == capability:
                    result.append(frm)
        return sorted(set(result))

    def _dep_strength(self, from_cap: str, to_cap: str) -> float:
        for (frm, to, rtype), rel in self._relations.items():
            if frm == from_cap and to == to_cap and rtype == "depends_on":
                return rel.strength
        return 0.0

    # ── 拓扑排序 ──────────────────────────────────────────────────

    def topological_order(self, capabilities: list[str]) -> TopologicalOrder:
        """生成尊重 depends_on 边的拓扑排序。

        同一层内的能力无相互依赖，可并行执行。返回 TopologicalOrder，
        层按先执行到后执行排序。
        """
        cap_set = set(capabilities)
        # 构建入度映射（仅针对请求集合内的边）
        in_degree: dict[str, int] = {c: 0 for c in capabilities}
        adj: dict[str, list[str]] = {c: [] for c in capabilities}

        for (frm, to, rtype), rel in self._relations.items():
            if rtype == "depends_on" and frm in cap_set and to in cap_set:
                adj[to].append(frm)
                in_degree[frm] = in_degree.get(frm, 0) + 1

        # Kahn 算法
        queue: deque[str] = deque(c for c in capabilities if in_degree.get(c, 0) == 0)
        layers: list[list[str]] = []
        visited: set[str] = set()
        dep_count = 0

        while queue:
            layer: list[str] = []
            for _ in range(len(queue)):
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                layer.append(node)
                for neighbor in adj.get(node, []):
                    in_degree[neighbor] -= 1
                    dep_count += 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
            if layer:
                layers.append(layer)

        # 剩余节点（环路或断连）— 作为独立层添加
        remaining = [c for c in capabilities if c not in visited]
        for c in remaining:
            layers.append([c])

        return TopologicalOrder(layers=layers, total_dependencies=dep_count)

    # ── 路径查找 ──────────────────────────────────────────────────

    def find_path(
        self,
        from_cap: str,
        to_cap: str,
        relation_types: list[str] | None = None,
    ) -> list[list[str]]:
        """查找从 from_cap 到 to_cap 的所有路径，可按关系类型过滤。
        基于 BFS，返回最多 5 条最短路径。"""
        allowed = set(relation_types) if relation_types else {"depends_on", "complements", "substitutes"}

        # 广度优先搜索
        paths: list[list[str]] = []
        queue: deque[tuple[str, list[str]]] = deque()
        queue.append((from_cap, [from_cap]))
        visited_paths: set[tuple[str, ...]] = set()

        while queue and len(paths) < 5:
            node, path = queue.popleft()
            if len(path) > 6:  # 最大路径长度
                continue

            neighbors = self._adjacency.get(node, [])
            for neighbor, rtype, _ in neighbors:
                if rtype not in allowed:
                    continue
                if neighbor in path:
                    continue
                new_path = path + [neighbor]
                key = tuple(new_path)
                if key in visited_paths:
                    continue
                visited_paths.add(key)

                if neighbor == to_cap:
                    paths.append(new_path)
                else:
                    queue.append((neighbor, new_path))

        return paths

    def find_substitute_path(
        self, target: str, unavailable: set[str] | None = None
    ) -> tuple[str, list[str]] | None:
        """为 `target` 查找替代链，避开 `unavailable` 中的能力。

        返回 (最终替代能力, 链路)，链路为从推荐替代到目标的替代路径，
        若无替代则返回 None。
        """
        skip = unavailable or set()
        skip.add(target)

        # 直接替代
        direct = self.substitutes_for(target)
        for sub in direct:
            if sub not in skip:
                return (sub, [sub])

        # 两跳：查找替代的替代
        for sub in direct:
            if sub in skip:
                continue
            second_hop = self.substitutes_for(sub)
            for sub2 in second_hop:
                if sub2 not in skip and sub2 != target:
                    return (sub2, [sub2, sub])

        return None

    # ── 导出 ────────────────────────────────────────────────────────────

    def export_for_prompt(self) -> str:
        """为 LLM 提示导出关键关系的紧凑文本摘要。

        按 relation_type 分组，每条边以单行形式列出。
        """
        if not self._relations:
            return ""

        grouped: dict[str, list[str]] = {"depends_on": [], "complements": [], "substitutes": []}
        for (frm, to, rtype), rel in self._relations.items():
            if rtype in grouped:
                line = f"  {frm} → {to}"
                if rel.description:
                    line += f"（{rel.description}）"
                grouped[rtype].append(line)

        parts: list[str] = []
        for rtype, label in [("depends_on", "依赖关系"), ("complements", "互补关系"), ("substitutes", "替代关系")]:
            if grouped[rtype]:
                parts.append(f"{label}:")
                parts.extend(grouped[rtype])

        return "\n".join(parts) if parts else ""

    @property
    def is_built(self) -> bool:
        return self._built

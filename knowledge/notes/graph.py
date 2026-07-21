"""
Knowledge Graph - 知识图谱

管理笔记之间的关系网络，支持：
1. 双向链接管理
2. 关系路径发现
3. 聚类分析
4. 中心性计算
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from infra.observability.logger import get_logger

from .models import (
    KnowledgeNote,
    BiDirectionalLink,
    NoteRelation,
    GraphNode,
    GraphEdge,
)

logger = get_logger(__name__)


@dataclass
class GraphStats:
    """图谱统计"""
    total_nodes: int = 0
    total_edges: int = 0
    avg_degree: float = 0.0
    density: float = 0.0
    connected_components: int = 0
    largest_component_size: int = 0


class KnowledgeGraph:
    """
    知识图谱
    
    管理笔记网络的构建和分析
    """

    def __init__(self, workspace_id: Optional[str] = None):
        self.workspace_id = workspace_id
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: Dict[str, GraphEdge] = {}
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)
        self.backlinks: Dict[str, Set[str]] = defaultdict(set)

    def add_note(self, note: KnowledgeNote) -> GraphNode:
        """添加笔记到图谱"""
        # 计算节点大小（基于连接数）
        outgoing = len(note.outgoing_links)
        incoming = len(note.incoming_links)
        size = 1.0 + 0.5 * (outgoing + incoming)

        # 根据类型确定颜色
        color_map = {
            "note": "#4A90D9",
            "concept": "#E74C3C",
            "fact": "#2ECC71",
            "procedure": "#F39C12",
            "insight": "#9B59B6",
        }
        color = color_map.get(note.note_type, "#4A90D9")

        node = GraphNode(
            id=note.id,
            label=note.title or note.id[:8],
            node_type="note",
            size=min(size, 5.0),
            color=color,
            metadata={
                "title": note.title,
                "tags": list(note.tags),
                "status": note.status,
                "type": note.note_type,
            }
        )

        self.nodes[note.id] = node
        return node

    def add_link(self, link: BiDirectionalLink) -> Optional[GraphEdge]:
        """添加链接到图谱"""
        edge_id = f"{link.source_note_id}-{link.target_note_id}"

        if edge_id in self.edges:
            return self.edges[edge_id]

        # 检查节点是否存在
        if link.source_note_id not in self.nodes:
            logger.warning(f"Source node not found: {link.source_note_id}")
            return None

        if link.target_note_id not in self.nodes:
            logger.warning(f"Target node not found: {link.target_note_id}")
            return None

        edge = GraphEdge(
            id=edge_id,
            source=link.source_note_id,
            target=link.target_note_id,
            edge_type=link.link_type,
            label=None
        )

        self.edges[edge_id] = edge
        self.adjacency[link.source_note_id].add(link.target_note_id)
        self.backlinks[link.target_note_id].add(link.source_note_id)

        return edge

    def build_from_notes(self, notes: List[KnowledgeNote]) -> "KnowledgeGraph":
        """从笔记列表构建图谱"""
        for note in notes:
            self.add_note(note)

        for note in notes:
            for link in note.outgoing_links:
                self.add_link(link)

        return self

    def get_neighbors(self, node_id: str) -> List[str]:
        """获取邻居节点"""
        return list(self.adjacency.get(node_id, set()))

    def get_backlinks(self, node_id: str) -> List[str]:
        """获取反向链接节点"""
        return list(self.backlinks.get(node_id, set()))

    def get_shortest_path(
        self,
        start_id: str,
        end_id: str
    ) -> Optional[List[str]]:
        """计算最短路径（BFS）"""
        if start_id not in self.nodes or end_id not in self.nodes:
            return None

        visited = {start_id}
        queue = [(start_id, [start_id])]

        while queue:
            current, path = queue.pop(0)

            if current == end_id:
                return path

            for neighbor in self.adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def find_clusters(self) -> Dict[str, List[str]]:
        """发现社区/聚类"""
        # 简单的连通分量检测
        visited = set()
        clusters = {}
        cluster_id = 0

        for node_id in self.nodes:
            if node_id not in visited:
                component = self._bfs_component(node_id, visited)
                if len(component) > 1:
                    clusters[f"cluster_{cluster_id}"] = list(component)
                    cluster_id += 1

        return clusters

    def _bfs_component(self, start: str, visited: Set[str]) -> Set[str]:
        """BFS查找连通分量"""
        component = {start}
        queue = [start]
        visited.add(start)

        while queue:
            current = queue.pop(0)
            for neighbor in self.adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)

        return component

    def calculate_centrality(self) -> Dict[str, float]:
        """计算节点中心性（简化版）"""
        centrality = {}

        for node_id in self.nodes:
            # 基于度的中心性
            degree = len(self.adjacency[node_id]) + len(self.backlinks[node_id])
            centrality[node_id] = degree

        # 归一化
        max_centrality = max(centrality.values()) if centrality else 1
        for node_id in centrality:
            centrality[node_id] /= max_centrality

        return centrality

    def get_hubs(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """获取中心节点（Hub）"""
        degrees = [
            (node_id, len(self.adjacency[node_id]))
            for node_id in self.nodes
        ]
        degrees.sort(key=lambda x: x[1], reverse=True)
        return degrees[:top_n]

    def get_orphans(self) -> List[str]:
        """获取孤立节点（没有任何链接）"""
        orphans = []
        for node_id in self.nodes:
            if not self.adjacency[node_id] and not self.backlinks[node_id]:
                orphans.append(node_id)
        return orphans

    def get_stats(self) -> GraphStats:
        """获取图谱统计"""
        stats = GraphStats()
        stats.total_nodes = len(self.nodes)
        stats.total_edges = len(self.edges)

        if stats.total_nodes > 0:
            total_degree = sum(len(self.adjacency[n]) for n in self.nodes)
            stats.avg_degree = total_degree / stats.total_nodes

        # 计算连通分量
        visited = set()
        components = 0
        max_component = 0

        for node_id in self.nodes:
            if node_id not in visited:
                component = self._bfs_component(node_id, visited)
                components += 1
                max_component = max(max_component, len(component))

        stats.connected_components = components
        stats.largest_component_size = max_component

        return stats

    def to_dict(self) -> Dict:
        """导出为字典格式"""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "type": n.node_type,
                    "x": n.x,
                    "y": n.y,
                    "size": n.size,
                    "color": n.color,
                    "metadata": n.metadata,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "id": e.id,
                    "source": e.source,
                    "target": e.target,
                    "type": e.edge_type,
                    "weight": e.weight,
                    "label": e.label,
                }
                for e in self.edges.values()
            ],
            "stats": {
                "total_nodes": len(self.nodes),
                "total_edges": len(self.edges),
            }
        }

    def to_cytoscape(self) -> Dict:
        """导出为Cytoscape.js格式"""
        return {
            "nodes": [
                {
                    "data": {
                        "id": n.id,
                        "label": n.label,
                        "type": n.node_type,
                        "size": n.size,
                        "color": n.color,
                        **n.metadata
                    }
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "data": {
                        "id": e.id,
                        "source": e.source,
                        "target": e.target,
                        "type": e.edge_type,
                        "weight": e.weight,
                        "label": e.label,
                    }
                }
                for e in self.edges.values()
            ]
        }

    def to_d3(self) -> Dict:
        """导出为D3.js力导向图格式"""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "name": n.label,
                    "group": n.metadata.get("type", "note"),
                    "val": n.size,
                    "color": n.color,
                }
                for n in self.nodes.values()
            ],
            "links": [
                {
                    "source": e.source,
                    "target": e.target,
                    "value": e.weight,
                }
                for e in self.edges.values()
            ]
        }

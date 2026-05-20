"""
JoinAgent — determines safe join paths between tables needed for a query.

Uses table_relationships (Knowledge Layer) as primary source,
falls back to TableRelationshipGraph (BFS + heuristic column similarity).
Entirely deterministic — no LLM.
"""
from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class JoinAgent(BaseAgent):
    """Construct safe join paths between tables referenced in the query.

    Priority:
    1. table_relationships from Knowledge Layer (pre-verified)
    2. TableRelationshipGraph FK paths (database declared)
    3. TableRelationshipGraph heuristic inference (column similarity)
    """

    def __init__(self) -> None:
        super().__init__("data_join")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            join_paths = await self._resolve_joins(ctx)
            warnings = self._check_amplification_risks(join_paths)
            ctx.join_paths = join_paths

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"found {len(join_paths)} join paths" + (
                    f" ({len(warnings)} warnings)" if warnings else ""
                ),
                confidence=self._join_confidence(join_paths),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="join_resolver",
                    source_type="data_cognition",
                    payload={
                        "join_paths": join_paths,
                        "warnings": warnings,
                    },
                    credibility=0.88,
                    relevance=0.9,
                )],
                agent_trace={"warnings": warnings} if warnings else None,
            )
        except Exception as exc:
            ctx.join_paths = []
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="join resolution failed",
                confidence=0.0,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _resolve_joins(self, ctx: CognitiveContext) -> list[dict]:
        involved_tables = self._get_involved_tables(ctx)
        if len(involved_tables) < 2:
            return []

        # Collect relationships from knowledge layer
        paths: list[dict] = []
        knowledge_rel = ctx.matched_relationships or []

        # Build a set of known table pairs from knowledge layer
        known_pairs: set[str] = set()
        for rel in knowledge_rel:
            known_pairs.add(f"{rel['left_table']}:{rel['right_table']}")
            known_pairs.add(f"{rel['right_table']}:{rel['left_table']}")

        # For each pair of involved tables, check knowledge layer first
        for i, table_a in enumerate(involved_tables):
            for table_b in involved_tables[i + 1:]:
                pair_key = f"{table_a}:{table_b}"
                reverse_key = f"{table_b}:{table_a}"

                if pair_key in known_pairs or reverse_key in known_pairs:
                    for rel in knowledge_rel:
                        if (
                            (rel["left_table"] == table_a and rel["right_table"] == table_b)
                            or (rel["left_table"] == table_b and rel["right_table"] == table_a)
                        ):
                            paths.append({
                                "path": f"{table_a} {rel['join_type']} JOIN {table_b} ON {table_a}.{rel['left_column']} = {table_b}.{rel['right_column']}",
                                "type": rel.get("join_type", "LEFT"),
                                "cardinality": rel.get("cardinality"),
                                "amplification_risk": rel.get("amplification_risk", "low"),
                                "confidence": 0.95 if rel.get("is_verified") else 0.75,
                                "source": "table_relationships",
                            })
                            break
                else:
                    # Fallback to TableRelationshipGraph
                    graph_path = await self._graph_fallback(ctx, table_a, table_b)
                    if graph_path:
                        paths.append(graph_path)

        return paths

    async def _graph_fallback(
        self, ctx: CognitiveContext, table_a: str, table_b: str
    ) -> dict | None:
        """Use TableRelationshipGraph for FK + heuristic join inference."""
        from kernel.data_cognition.table_graph import TableRelationshipGraph

        graph = TableRelationshipGraph()
        # Register columns for heuristic matching
        for table_name, columns in ctx.table_columns.items():
            graph.register_columns(table_name, columns)

        # Also register any knowledge layer FKs
        if ctx.matched_relationships:
            for rel in ctx.matched_relationships:
                if rel.get("is_verified"):
                    graph.register_fk(
                        left_table=rel["left_table"],
                        right_table=rel["right_table"],
                        left_key=rel["left_column"],
                        right_key=rel["right_column"],
                    )

        path = graph.find_join_path(table_a, table_b)
        if path:
            steps = []
            for step in path:
                steps.append(
                    f"{step.left_table}.{step.left_column} = {step.right_table}.{step.right_column}"
                )
            return {
                "path": " JOIN ".join(steps),
                "type": "LEFT",
                "cardinality": None,
                "amplification_risk": "medium",
                "confidence": 0.65,
                "source": "table_graph_heuristic",
            }
        return None

    def _get_involved_tables(self, ctx: CognitiveContext) -> list[str]:
        """Extract table names from entities or table_names list."""
        tables: list[str] = []
        if ctx.entities:
            for e in ctx.entities:
                t = e.get("mapped_table") or ""
                if t and t not in tables:
                    tables.append(t)
        if not tables:
            tables = ctx.table_names
        return tables

    def _check_amplification_risks(self, paths: list[dict]) -> list[str]:
        """Flag high-risk joins."""
        warnings: list[str] = []
        for p in paths:
            if p.get("amplification_risk") in ("high", "critical"):
                warnings.append(
                    f"Join amplification risk ({p['amplification_risk']}): {p.get('path', '')}"
                )
        return warnings

    def _join_confidence(self, paths: list[dict]) -> float:
        if not paths:
            return 0.5
        avg = sum(p.get("confidence", 0.5) for p in paths) / len(paths)
        return min(avg, 0.95)

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any

from agents.base import AgentResult, TaskMessage
from agents.registry import AgentRegistry
from kernel.dag_plan import DagNode, DagPlan


@dataclass
class DagExecutionResult:
    results: list[AgentResult]
    node_map: dict[str, AgentResult]


class DagScheduler:
    def __init__(self, registry: AgentRegistry, timeout_sec: int = 30) -> None:
        self.registry = registry
        self.timeout_sec = timeout_sec

    async def execute(self, plan: DagPlan, event_cb: Any | None = None) -> DagExecutionResult:
        pending = {n.node_id: n for n in plan.nodes}
        completed: dict[str, AgentResult] = {}
        results: list[AgentResult] = []
        inflight: dict[str, asyncio.Task[AgentResult]] = {}
        sem = asyncio.Semaphore(max(1, len(plan.nodes)))

        async def run_node(node: DagNode) -> AgentResult:
            async with sem:
                started_at = monotonic()
                if event_cb is not None:
                    await event_cb(
                        {
                            "type": "dag_node_start",
                            "data": {
                                "node_id": node.node_id,
                                "agent_type": node.agent_type,
                                "depends_on": node.depends_on,
                                "started_at_ms": int(started_at * 1000),
                            },
                        }
                    )
                params = dict(node.params or {})
                if plan.speculative_execution:
                    params.setdefault("speculative", True)
                msg = TaskMessage(
                    task_id=node.node_id,
                    agent_type=node.agent_type,
                    query=node.query,
                    params=params,
                    session_id=str(params.get("session_id", "") or "") or None,
                    user_id=str(params.get("user_id", "") or "") or None,
                )
                agent = self.registry.get_agent(node.agent_type)
                result = await asyncio.wait_for(agent.execute(msg), timeout=self.timeout_sec)
                duration_ms = int((monotonic() - started_at) * 1000)
                result.metadata = {
                    **(result.metadata or {}),
                    "dag": {
                        "duration_ms": duration_ms,
                        "started_at_ms": int(started_at * 1000),
                        "node_id": node.node_id,
                    },
                }
                return result

        while pending or inflight:
            launched = False
            for node_id, node in list(pending.items()):
                if all(dep in completed for dep in node.depends_on):
                    inflight[node_id] = asyncio.create_task(run_node(node))
                    pending.pop(node_id)
                    launched = True

            if not inflight:
                if not launched:
                    break
                continue

            done, _ = await asyncio.wait(inflight.values(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                node_id = next((nid for nid, t in inflight.items() if t is task), None)
                if node_id is None:
                    continue
                inflight.pop(node_id, None)
                try:
                    result = task.result()
                except Exception as exc:  # noqa: BLE001
                    result = AgentResult(
                        task_id=node_id,
                        agent_type="unknown",
                        status="error",
                        content="",
                        error=str(exc),
                        metadata={"dag": {"duration_ms": 0, "node_id": node_id}},
                    )
                completed[node_id] = result
                results.append(result)
                if event_cb is not None:
                    duration_ms = int(
                        ((result.metadata or {}).get("dag", {}) or {}).get("duration_ms", 0) or 0
                    )
                    await event_cb(
                        {
                            "type": "dag_node_complete",
                            "data": {
                                "node_id": node_id,
                                "agent_type": result.agent_type,
                                "status": result.status,
                                "duration_ms": duration_ms,
                                "preview": str(result.content or "")[:200],
                            },
                        }
                    )

        for node_id, node in pending.items():
            results.append(
                AgentResult(
                    task_id=node_id,
                    agent_type=node.agent_type,
                    status="skipped",
                    content="",
                    error="unresolved_dependencies",
                )
            )
        return DagExecutionResult(results=results, node_map=completed)

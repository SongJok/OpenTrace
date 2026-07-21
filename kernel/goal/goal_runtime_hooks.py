"""目标生命周期 + 认知运行时状态钩子（供 CognitiveExecutive 各阶段使用）。"""

from __future__ import annotations

from typing import Any

from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.runtime.cognitive_state.store import get_or_create_runtime_state


class GoalRuntimeHooks:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._root_goal = self._resolve_root_goal()

    @classmethod
    def from_context(cls, ctx: Any) -> GoalRuntimeHooks | None:
        rt = (getattr(ctx, "metadata", None) or {}).get("runtime_task")
        if rt is None and not (getattr(ctx, "metadata", None) or {}).get("goal_graph"):
            return None
        return cls(ctx)

    def _resolve_root_goal(self) -> Any | None:
        rt = (self.ctx.metadata or {}).get("runtime_task")
        if rt is not None and getattr(rt, "goal", None):
            return rt.goal
        return None

    def _cognitive_state(self) -> Any:
        return get_or_create_runtime_state(
            request_id=str(getattr(self.ctx, "request_id", "") or ""),
            session_id=str(getattr(self.ctx, "session_id", "") or ""),
            goal_id=str(getattr(self._root_goal, "goal_id", "") or ""),
        )

    def on_phase(self, phase: str, note: str = "") -> None:
        st = self._cognitive_state()
        st.advance_phase(phase, note)
        self.ctx.metadata = self.ctx.metadata or {}
        self.ctx.metadata["cognitive_runtime_state"] = {
            "phase": st.phase,
            "goal_id": st.goal_id,
        }
        mapping = {
            "plan": GoalLifecycleState.PROJECTED,
            "execute": GoalLifecycleState.EXECUTING,
            "evidence": GoalLifecycleState.EVIDENCE_COLLECTED,
            "fusion": GoalLifecycleState.FUSED,
            "critic": GoalLifecycleState.FUSED,
            "complete": GoalLifecycleState.COMPLETED,
            "failed": GoalLifecycleState.FAILED,
        }
        if self._root_goal and phase in mapping:
            transition_goal_state(self._root_goal, mapping[phase])

    def record_evidence_ids(self, evidence_objects: list[Any]) -> None:
        st = self._cognitive_state()
        for i, ev in enumerate(evidence_objects or []):
            eid = getattr(ev, "evidence_id", None) or getattr(ev, "id", None) or f"ev:{i}"
            st.evidence_ids.append(str(eid))
        try:
            from memory.fabric.router_singleton import get_memory_fabric_router

            router = get_memory_fabric_router()
            sid = str(getattr(self.ctx, "session_id", "") or "")
            gid = str(getattr(self._root_goal, "goal_id", "") or st.goal_id)
            for eid in st.evidence_ids[-len(evidence_objects or []) :]:
                router.bind(
                    f"{sid}:{eid}",
                    goal_id=gid,
                    evidence_id=eid,
                    salience=0.65,
                    metadata={"session_id": sid, "request_id": getattr(self.ctx, "request_id", "")},
                )
        except Exception:
            pass

    def snapshot_metrics(self, **metrics: float) -> None:
        st = self._cognitive_state()
        st.metrics.update(metrics)
        self.ctx.metadata = self.ctx.metadata or {}
        self.ctx.metadata["cognitive_runtime_state"] = {
            "phase": st.phase,
            "goal_id": st.goal_id,
            "evidence_count": len(st.evidence_ids),
            "metrics": dict(st.metrics),
        }
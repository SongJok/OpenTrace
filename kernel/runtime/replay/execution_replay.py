"""
执行回放 — 回放已记录的执行追踪。

使用 PromptSnapshots 重新执行先前记录的认知管线
并比较结果。这支持：
- 回归测试：代码更改是否改变了行为？
- 调试：以更多日志回放失败的执行
- 审计：证明系统具体做了什么
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .deterministic_trace import DeterministicTrace
from .prompt_snapshot import PromptSnapshot

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ReplayResult:
    """回放执行追踪的结果。"""
    original_trace_id: str = ""
    replay_trace_id: str = ""
    successful: bool = False
    matched: bool = False  # 输出是否与原始匹配
    total_llm_calls: int = 0
    matched_llm_calls: int = 0
    divergences: list[dict[str, Any]] = field(default_factory=list)
    replay_duration_ms: int = 0
    error: str = ""


class ExecutionReplay:
    """回放先前记录的认知执行。

    从 DeterministicTrace 中获取 PromptSnapshots，用相同输入
    重新执行每个 LLM 调用，并比较输出。

    注意：即使 temperature=0.0，由于基础设施的非确定性，
    LLM 输出在调用间可能略有差异。此回放系统捕获
    这些偏差以供分析。
    """

    def __init__(self, prompt_store: Any = None) -> None:
        self._prompt_store = prompt_store

    async def replay(
        self,
        original_trace: DeterministicTrace,
        snapshot_filter: str | None = None,  # 可选：仅回放特定阶段
        compare_outputs: bool = True,
    ) -> ReplayResult:
        """回放执行追踪。

        Args:
            original_trace: 要回放的追踪。
            snapshot_filter: 如果设置，仅回放此阶段的快照。
            compare_outputs: 如果为 True，比较回放输出与原始输出。

        Returns:
            包含匹配/不匹配详情的 ReplayResult。
        """
        from .deterministic_trace import DeterministicTrace, TraceEvent, TraceEventType

        if self._prompt_store is None:
            from kernel.runtime.replay.prompt_snapshot import prompt_snapshot_store
            self._prompt_store = prompt_snapshot_store

        # 获取此会话的快照
        session_id = original_trace.session_id
        snapshots = self._prompt_store.get_by_session(session_id)

        if snapshot_filter:
            snapshots = [s for s in snapshots if s.phase == snapshot_filter]

        if not snapshots:
            return ReplayResult(
                original_trace_id=original_trace.trace_id,
                error="No prompt snapshots found for replay",
            )

        # 为回放创建新追踪
        import time
        start_time = time.time()

        replay_trace = DeterministicTrace(
            request_id=original_trace.request_id,
            session_id=f"{session_id}_replay",
        )

        divergences: list[dict[str, Any]] = []
        matched_count = 0
        total_count = 0

        for snap in snapshots:
            if snap.error:
                continue  # 跳过原始失败的调用

            total_count += 1
            try:
                from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

                gw = get_model_gateway()

                # 回放 LLM 调用
                role = LLMRole.QUERY
                try:
                    role = LLMRole(snap.model_role) if snap.model_role else LLMRole.QUERY
                except ValueError:
                    pass

                replay_start = time.time()
                resp = await gw.complete(
                    [
                        LLMMessage(role="system", content=snap.system_prompt),
                        LLMMessage(role="user", content=snap.user_prompt),
                    ],
                    role=role,
                    temperature=snap.temperature,
                    max_tokens=snap.max_tokens,
                )
                replay_latency = int((time.time() - replay_start) * 1000)

                replayed_output = (resp.content or "").strip()

                # 记录到回放追踪
                replay_trace.add_event(TraceEvent(
                    event_type=TraceEventType.LLM_CALL,
                    phase=f"replay_{snap.phase}",
                    data={
                        "original_snapshot_id": snap.snapshot_id,
                        "model_role": snap.model_role,
                    },
                    duration_ms=replay_latency,
                ))

                # 比较输出
                if compare_outputs:
                    original_output = snap.response.strip()
                    if replayed_output == original_output:
                        matched_count += 1
                    else:
                        divergences.append({
                            "snapshot_id": snap.snapshot_id,
                            "phase": snap.phase,
                            "original_length": len(original_output),
                            "replay_length": len(replayed_output),
                            "original_preview": original_output[:200],
                            "replay_preview": replayed_output[:200],
                        })

            except Exception as exc:
                replay_trace.add_event(TraceEvent(
                    event_type=TraceEventType.ERROR,
                    phase=f"replay_{snap.phase}",
                    data={"error": str(exc), "snapshot_id": snap.snapshot_id},
                ))
                logger.warning("Replay LLM call failed", phase=snap.phase, error=str(exc))

        replay_trace.ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        total_duration = int((time.time() - start_time) * 1000)
        replay_trace.total_duration_ms = total_duration

        result = ReplayResult(
            original_trace_id=original_trace.trace_id,
            replay_trace_id=replay_trace.trace_id,
            successful=len(divergences) == 0 or not compare_outputs,
            matched=matched_count == total_count,
            total_llm_calls=total_count,
            matched_llm_calls=matched_count,
            divergences=divergences,
            replay_duration_ms=total_duration,
        )

        logger.info(
            "ExecutionReplay complete",
            matched=f"{matched_count}/{total_count}",
            divergences=len(divergences),
            duration_ms=total_duration,
        )

        return result

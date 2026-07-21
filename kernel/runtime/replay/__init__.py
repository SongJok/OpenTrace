"""
Deterministic Replay System — Audit, debug, and replay cognitive executions.

Enterprise AI systems MUST be auditable. The replay system provides:
- prompt_snapshot: Capture every LLM prompt + response for audit
- runtime_snapshot: Full RuntimeContext snapshot at decision points
- execution_replay: Replay a recorded execution trace deterministically
- deterministic_trace: Structured trace for debugging and compliance
"""

from kernel.runtime.replay.deterministic_trace import (
    DeterministicTrace,
    TraceEvent,
    TraceEventType,
)
from kernel.runtime.replay.execution_replay import (
    ExecutionReplay,
    ReplayResult,
)
from kernel.runtime.replay.prompt_snapshot import (
    PromptSnapshot,
    PromptSnapshotStore,
    prompt_snapshot_store,
)
from kernel.runtime.replay.runtime_snapshot import (
    RuntimeSnapshot,
    RuntimeSnapshotStore,
    runtime_snapshot_store,
)

__all__ = [
    "PromptSnapshot",
    "PromptSnapshotStore",
    "prompt_snapshot_store",
    "RuntimeSnapshot",
    "RuntimeSnapshotStore",
    "runtime_snapshot_store",
    "ExecutionReplay",
    "ReplayResult",
    "DeterministicTrace",
    "TraceEvent",
    "TraceEventType",
]

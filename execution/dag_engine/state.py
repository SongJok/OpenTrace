"""
StateManager — Redis-backed checkpoint persistence for DAG resume.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from execution.dag_engine.graph import Task, TaskStatus
from infra.cache.redis_client import get_memory_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)

CHECKPOINT_KEY = "opentrace:dag:checkpoint:{dag_id}"
CHECKPOINT_TTL = 24 * 3600  # 24 hours


class StateManager:
    """
    Persists DAG execution state to Redis so a crashed run can resume.

    Checkpoint format:
    {
      "dag_id": str,
      "ts": float,
      "completed": [task_id, ...],
      "results": {task_id: serialized_result, ...},
      "task_statuses": {task_id: status, ...}
    }
    """

    async def save(
        self,
        dag_id: str,
        tasks: dict[str, Task],
        results: dict[str, Any],
        completed: set[str],
    ) -> None:
        try:
            r = await get_memory_redis()
            key = CHECKPOINT_KEY.format(dag_id=dag_id)
            payload = json.dumps({
                "dag_id": dag_id,
                "ts": time.time(),
                "completed": list(completed),
                "results": {
                    k: _safe_serialize(v)
                    for k, v in results.items()
                    if not k.startswith("__err_")
                },
                "task_statuses": {
                    tid: t.status.value
                    for tid, t in tasks.items()
                },
            })
            await r.setex(key, CHECKPOINT_TTL, payload)
            logger.debug("DAG checkpoint saved", dag_id=dag_id, completed=len(completed))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Checkpoint save failed", dag_id=dag_id, error=str(exc))

    async def load(self, dag_id: str) -> Optional[dict[str, Any]]:
        try:
            r = await get_memory_redis()
            key = CHECKPOINT_KEY.format(dag_id=dag_id)
            raw = await r.get(key)
            if raw:
                data = json.loads(raw)
                logger.info("DAG checkpoint loaded", dag_id=dag_id,
                            completed=len(data.get("completed", [])))
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Checkpoint load failed", dag_id=dag_id, error=str(exc))
        return None

    async def delete(self, dag_id: str) -> None:
        try:
            r = await get_memory_redis()
            await r.delete(CHECKPOINT_KEY.format(dag_id=dag_id))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Checkpoint delete failed", dag_id=dag_id, error=str(exc))

    def restore_task_statuses(
        self,
        tasks: dict[str, Task],
        checkpoint: dict[str, Any],
    ) -> tuple[set[str], dict[str, Any]]:
        """Apply a checkpoint to a task map. Returns (completed_set, results_dict)."""
        completed: set[str] = set(checkpoint.get("completed", []))
        results: dict[str, Any] = dict(checkpoint.get("results", {}))
        statuses: dict[str, str] = checkpoint.get("task_statuses", {})

        for tid, status_str in statuses.items():
            if tid in tasks:
                tasks[tid].status = TaskStatus(status_str)

        return completed, results


def _safe_serialize(value: Any) -> Any:
    """Best-effort serialization for checkpoint storage."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, dict)):
        return value
    return str(value)


state_manager = StateManager()

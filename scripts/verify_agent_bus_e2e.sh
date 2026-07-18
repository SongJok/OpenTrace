#!/usr/bin/env bash
# AgentMessageBus 与 Responses Stream 是独立通道；本脚本直接验证前者。
set -euo pipefail

echo "=== Agent Bus E2E Verify ==="
docker compose exec -T agent-worker python - <<'PY'
import asyncio
import uuid

from infra.message_bus.agent_bus import AgentMessageBus, AgentTaskEnvelope


async def main():
    bus = AgentMessageBus()
    if bus.mode != "stream":
        raise SystemExit(f"FAIL: 此验收需要 stream 模式，当前为 {bus.mode}")
    task_id = f"verify-{uuid.uuid4().hex}"
    await bus.publish_task(
        AgentTaskEnvelope(
            task_id=task_id,
            agent_type="tool",
            query="现在几点？",
            params={},
            session_id="agent-bus-e2e",
            user_id="system-verify",
        )
    )
    result = await bus.wait_for_result(task_id, timeout_sec=45)
    if result.get("status") != "success" or not str(result.get("content") or "").strip():
        raise SystemExit(f"FAIL: Agent Bus 返回异常: {result}")
    print(f"PASS: agent={result.get('agent_type')} content={result['content'][:100]}")


asyncio.run(main())
PY

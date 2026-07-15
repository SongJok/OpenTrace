import pytest

from kernel.tools.function_calling.executor import ToolExecutor, ToolStatus


@pytest.mark.asyncio
async def test_executor_can_disable_retries_for_side_effecting_tools() -> None:
    calls = 0

    async def write_once() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("transport outcome unknown")

    executor = ToolExecutor()
    executor.register_tool("write_once", write_once)
    result = await executor.execute(
        [{"name": "write_once", "parameters": {}}],
        max_retries=0,
    )

    assert calls == 1
    assert result[0].status == ToolStatus.FAILED


@pytest.mark.asyncio
async def test_executor_keeps_bounded_retries_for_read_tools() -> None:
    calls = 0

    async def flaky_read() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise RuntimeError("temporary")
        return "ok"

    executor = ToolExecutor()
    executor.register_tool("flaky_read", flaky_read)
    result = await executor.execute(
        [{"name": "flaky_read", "parameters": {}}],
        max_retries=1,
    )

    assert calls == 2
    assert result[0].status == ToolStatus.COMPLETED
    assert result[0].result == "ok"

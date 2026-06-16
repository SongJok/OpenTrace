"""TMS bridge + compression."""

from __future__ import annotations

import pytest

from memory.fabric.tms_bridge import run_session_memory_maintenance


@pytest.mark.asyncio
async def test_tms_bridge_runs():
    mems = [{"id": f"m{i}", "confidence": 0.3} for i in range(5)]
    out = await run_session_memory_maintenance(mems, max_active=128)
    assert "compression_plan" in out
    assert "tms_report" in out
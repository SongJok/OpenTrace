"""Fixture-driven multi-turn regression (no live LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/multi_turn_scenarios.json"


def _load_scenarios() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return list(data.get("scenarios") or [])


@pytest.mark.parametrize("scenario", _load_scenarios(), ids=lambda s: s.get("id", "case"))
@pytest.mark.asyncio
async def test_multi_turn_fixture_scenario(scenario: dict) -> None:
    from kernel.multi_turn_resolution import resolve_multi_turn_query

    force = scenario.get("force_mode")
    conv_state = None
    if scenario.get("prior_plan") or scenario.get("prior_results"):
        from kernel.conversation_state import ConversationState

        conv_state = ConversationState(session_id="fixture-session")
        conv_state.last_plan = scenario.get("prior_plan")
        conv_state.last_results = scenario.get("prior_results")

    mtr = await resolve_multi_turn_query(
        str(scenario.get("user_query") or ""),
        conversation_state=conv_state,
        force_mode=force,
    )
    expect_applied = scenario.get("expect_applied")
    if expect_applied is not None:
        assert mtr.applied is bool(expect_applied), (
            f"applied={mtr.applied} resolved={mtr.resolved_query!r}"
        )
    for sub in scenario.get("expect_substrings") or []:
        assert sub in (mtr.resolved_query or ""), mtr.resolved_query
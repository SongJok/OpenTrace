"""Fixture-driven multi-turn scenarios (DST + resolve_multi_turn_query)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/multi_turn_scenarios.json"


def _load_scenarios() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return list(data.get("scenarios") or [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    _load_scenarios(),
    ids=[s.get("id", "scenario") for s in _load_scenarios()],
)
async def test_multi_turn_fixture_scenario(scenario: dict) -> None:
    kind = str(scenario.get("kind") or "resolve")

    if kind == "dst_track":
        from kernel.dialogue_state_tracker import DialogueStateTracker

        dst = DialogueStateTracker()
        state = await dst.track(
            str(scenario.get("query") or ""),
            previous_plan=scenario.get("previous_plan"),
            previous_results=scenario.get("previous_results"),
        )
        if scenario.get("expect_turn_type"):
            assert state.turn_type == scenario["expect_turn_type"]
        sub = scenario.get("expect_substring")
        if sub:
            assert sub in state.resolved_query
        return

    if kind == "reference":
        from kernel.conversation_state import ConversationState
        from kernel.reference_resolver import ReferenceResolver

        raw = scenario.get("conv") or {}
        conv = ConversationState(
            session_id=str(raw.get("session_id") or "s1"),
            last_user_goal=str(raw.get("last_user_goal") or ""),
            active_domain=str(raw.get("active_domain") or ""),
        )
        resolver = ReferenceResolver()
        result = await resolver.resolve_with_llm(str(scenario.get("query") or ""), conv)
        min_conf = float(scenario.get("min_confidence", 0.5))
        assert result.confidence >= min_conf
        return

    from kernel.multi_turn_resolution import resolve_multi_turn_query

    query = str(scenario.get("query") or "")
    force_mode = scenario.get("force_mode")
    out = await resolve_multi_turn_query(query, force_mode=force_mode)

    expect_applied = scenario.get("expect_applied")
    if expect_applied is not None:
        assert out.applied is bool(expect_applied)

    if force_mode:
        assert out.resolved_query == query.strip() or not query.strip()
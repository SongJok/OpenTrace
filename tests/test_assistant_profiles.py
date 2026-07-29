"""内置助手角色的补齐、校验与提示词合约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gateway.api_gateway.routers.agent_resources import AssistantProfilePayload, _seed_profiles
from infra.assistant_profiles import (
    BUILT_IN_ASSISTANT_PROFILES,
    PERSONALITY_INSTRUCTIONS,
    personality_instruction,
)
from infra.storage.models import AssistantProfile


class _RowsResult:
    def __init__(self, rows: list[AssistantProfile]) -> None:
        self._rows = rows

    def scalars(self) -> _RowsResult:
        return self

    def all(self) -> list[AssistantProfile]:
        return self._rows


class _ProfileDB:
    def __init__(self, rows: list[AssistantProfile]) -> None:
        self.rows = rows
        self.added: list[AssistantProfile] = []
        self.commits = 0

    async def execute(self, _statement: object) -> _RowsResult:
        return _RowsResult(self.rows)

    def add(self, row: AssistantProfile) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


def _profile(name: str, personality: str, *, built_in: bool = True) -> AssistantProfile:
    return AssistantProfile(
        id=f"profile-{personality}",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        name=name,
        personality=personality,
        built_in=built_in,
        is_default=personality == "none",
    )


def test_all_six_personalities_are_accepted_and_unknown_value_is_rejected() -> None:
    assert [name for name, _ in BUILT_IN_ASSISTANT_PROFILES] == [
        "默认",
        "友好",
        "务实",
        "可爱",
        "浪漫",
        "搞笑",
    ]
    for _name, personality in BUILT_IN_ASSISTANT_PROFILES:
        assert (
            AssistantProfilePayload(name="测试", personality=personality).personality == personality
        )

    with pytest.raises(ValidationError):
        AssistantProfilePayload(name="测试", personality="unknown")


def test_each_personality_has_a_distinct_runtime_instruction_and_safe_fallback() -> None:
    prompts = [personality_instruction(value) for _name, value in BUILT_IN_ASSISTANT_PROFILES]

    assert len(prompts) == len(set(prompts)) == 6
    assert "可爱" in PERSONALITY_INSTRUCTIONS["cute"]
    assert "浪漫" in PERSONALITY_INSTRUCTIONS["romantic"]
    assert "幽默" in PERSONALITY_INSTRUCTIONS["funny"]
    assert "严肃" in PERSONALITY_INSTRUCTIONS["cute"]
    assert "准确" in PERSONALITY_INSTRUCTIONS["romantic"]
    assert "专业" in PERSONALITY_INSTRUCTIONS["funny"]
    assert personality_instruction("unknown") == PERSONALITY_INSTRUCTIONS["none"]


@pytest.mark.asyncio
async def test_existing_users_receive_only_the_three_missing_built_in_profiles() -> None:
    existing = [
        _profile(name, personality) for name, personality in BUILT_IN_ASSISTANT_PROFILES[:3]
    ]
    db = _ProfileDB(existing)

    await _seed_profiles(
        db, SimpleNamespace(id="user-1"), tenant_id="tenant-1", workspace_id="workspace-1"
    )

    assert [(row.name, row.personality) for row in db.added] == list(
        BUILT_IN_ASSISTANT_PROFILES[3:]
    )
    assert all(row.built_in for row in db.added)
    assert not any(row.is_default for row in db.added)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_profile_seeding_is_idempotent_after_all_roles_exist() -> None:
    existing = [_profile(name, personality) for name, personality in BUILT_IN_ASSISTANT_PROFILES]
    db = _ProfileDB(existing)

    await _seed_profiles(
        db, SimpleNamespace(id="user-1"), tenant_id="tenant-1", workspace_id="workspace-1"
    )

    assert db.added == []
    assert db.commits == 0

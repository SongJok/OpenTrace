from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.api_gateway.routers.skills import (
    SkillSessionBindingRequest,
    bind_session_skills,
    get_session_skills,
)


@pytest.mark.asyncio
async def test_binding_is_persisted_on_owned_session():
    session = SimpleNamespace(enabled_skills=[], disabled_skills=[])
    result = Mock()
    result.scalar_one_or_none.return_value = session
    db = AsyncMock()
    db.execute.return_value = result

    response = await bind_session_skills(
        SkillSessionBindingRequest(
            session_id="s1",
            enabled_skills=["b", "a", "a"],
            disabled_skills=["old"],
        ),
        current_user=SimpleNamespace(id="u1"),
        db=db,
    )

    assert session.enabled_skills == ["a", "b"]
    assert session.disabled_skills == ["old"]
    assert response["enabled_skills"] == ["a", "b"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_binding_is_loaded_from_database_session():
    session = SimpleNamespace(enabled_skills=["a"], disabled_skills=["old"])
    result = Mock()
    result.scalar_one_or_none.return_value = session
    db = AsyncMock()
    db.execute.return_value = result

    response = await get_session_skills(
        "s1",
        current_user=SimpleNamespace(id="u1"),
        db=db,
    )

    assert response == {
        "session_id": "s1",
        "enabled_skills": ["a"],
        "disabled_skills": ["old"],
    }


def test_skill_binding_migration_is_chained():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic/versions/20260711_chat_session_skills.py"
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20260710_data_sources_tenant"' in source
    assert 'if "enabled_skills" not in columns' in source
    assert 'if "disabled_skills" not in columns' in source

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import httpx
import pytest

from infra.storage.models import SkillCatalogEntry, UserSkillInstallation
from skills import catalog
from skills.store import marketplace as marketplace_module


class _FakeAsyncClient:
    def __init__(self, handler: Callable[[str, dict[str, str]], httpx.Response]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str], **_kwargs: Any) -> httpx.Response:
        self.calls.append((url, headers))
        return self.handler(url, headers)


def _response(status: int, url: str, *, content: bytes = b"", headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        content=content,
        headers=headers,
        request=httpx.Request("GET", url),
    )


def _entry() -> SimpleNamespace:
    return SimpleNamespace(
        github_owner="majiayu000",
        github_repo="claude-skill-registry",
        skill_path="skills/data/debugging-agent",
    )


def test_github_api_token_is_server_side_authorization_only() -> None:
    assert "Authorization" not in catalog._github_api_headers()
    headers = catalog._github_api_headers("test-token")
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


@pytest.mark.asyncio
async def test_public_install_uses_raw_source_without_rest_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    markdown = b"---\nname: debugging-agent\n---\n# Debugging Agent\n"

    def handler(url: str, _headers: dict[str, str]) -> httpx.Response:
        assert url == (
            "https://raw.githubusercontent.com/majiayu000/claude-skill-registry/HEAD/"
            "skills/data/debugging-agent/SKILL.md"
        )
        return _response(200, url, content=markdown)

    client = _FakeAsyncClient(handler)
    monkeypatch.setattr(catalog.settings, "skillhub_github_token", "")
    monkeypatch.setattr(catalog.settings, "skillhub_github_raw_fallback_enabled", True)
    monkeypatch.setattr(catalog.httpx, "AsyncClient", lambda **_kwargs: client)

    content, revision = await catalog._fetch_skill_markdown(_entry())

    assert content == markdown.decode()
    assert revision == hashlib.sha256(markdown).hexdigest()
    assert len(client.calls) == 1
    assert "Authorization" not in client.calls[0][1]


@pytest.mark.asyncio
async def test_authenticated_rate_limit_falls_back_to_raw_source(monkeypatch: pytest.MonkeyPatch) -> None:
    markdown = b"---\nname: debugging-agent\n---\n# Installed after fallback\n"

    def handler(url: str, headers: dict[str, str]) -> httpx.Response:
        if url.startswith("https://api.github.com/"):
            assert headers["Authorization"] == "Bearer test-token"
            return _response(
                403,
                url,
                content=b'{"message":"API rate limit exceeded"}',
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "2000000000"},
            )
        assert url.startswith("https://raw.githubusercontent.com/")
        assert "Authorization" not in headers
        return _response(200, url, content=markdown)

    client = _FakeAsyncClient(handler)
    monkeypatch.setattr(catalog.settings, "skillhub_github_token", "test-token")
    monkeypatch.setattr(catalog.settings, "skillhub_github_raw_fallback_enabled", True)
    monkeypatch.setattr(catalog.httpx, "AsyncClient", lambda **_kwargs: client)

    content, revision = await catalog._fetch_skill_markdown(_entry())

    assert content == markdown.decode()
    assert revision == hashlib.sha256(markdown).hexdigest()
    assert [url.split("/", 3)[2] for url, _headers in client.calls] == [
        "api.github.com",
        "raw.githubusercontent.com",
    ]


def test_compose_shares_installed_skills_between_api_and_worker() -> None:
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text()
    assert compose.count("skills_data:/app/skills/installed") == 2
    assert "skills_data:" in compose


@pytest.mark.asyncio
async def test_catalog_loop_retries_quickly_after_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    delays: list[int] = []

    async def fake_sync() -> dict[str, int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError('catalog table is not ready')
        return {"popular": 30, "recent": 30, "stored": 50}

    async def fake_sleep(seconds: int) -> None:
        delays.append(seconds)
        if len(delays) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(catalog.settings, "skillhub_sync_enabled", True)
    monkeypatch.setattr(catalog.settings, "skillhub_sync_interval_seconds", 21600)
    monkeypatch.setattr(catalog.settings, "skillhub_sync_retry_seconds", 60)
    monkeypatch.setattr(catalog, "sync_skillhub_catalog", fake_sync)
    monkeypatch.setattr(catalog.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await catalog.skillhub_sync_loop()

    assert attempts == 2
    assert delays == [60, 21600]


@pytest.mark.asyncio
async def test_catalog_sync_is_append_only_and_preserves_platform_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SkillCatalogEntry(
        id="catalog-1",
        external_id="owner/repo/skill",
        provider="skillhub-palebluedot",
        name="skill",
        description="old",
        github_owner="owner",
        github_repo="repo",
        skill_path="skills/skill",
        status="disabled",
        source_metadata={"platform_note": "暂不适合平台", "platform_disabled_by": "admin-1"},
    )

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def execute(self, _statement: Any) -> None:
            return None

        async def scalar(self, _statement: Any) -> SkillCatalogEntry:
            return row

        def add(self, _row: SkillCatalogEntry) -> None:
            raise AssertionError("existing disabled row must be updated, not recreated")

        async def commit(self) -> None:
            return None

    async def fake_fetch(_sort: str, _limit: int) -> list[dict[str, Any]]:
        return [{
            "id": "owner/repo/skill",
            "name": "skill-v2",
            "description": "new",
            "githubOwner": "owner",
            "githubRepo": "repo",
            "skillPath": "skills/skill",
            "securityStatus": "pass",
        }]

    monkeypatch.setattr(catalog, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(catalog, "_fetch_catalog", fake_fetch)

    result = await catalog.sync_skillhub_catalog(limit=30)

    assert row.status == "disabled"
    assert row.name == "skill-v2"
    assert row.source_metadata["platform_note"] == "暂不适合平台"
    assert result["added"] == 0
    assert result["preserved_disabled"] == 1


@pytest.mark.asyncio
async def test_reviewed_skill_can_be_installed_and_executed_as_instruction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry = SkillCatalogEntry(
        id="catalog-debugging-agent",
        external_id="majiayu000/claude-skill-registry/debugging-agent",
        provider="skillhub-palebluedot",
        name="debugging-agent",
        description="Diagnose software failures",
        github_owner="majiayu000",
        github_repo="claude-skill-registry",
        skill_path="skills/data/debugging-agent",
        version="1.0.0",
        security_status="pass",
        security_score=100,
        status="active",
    )
    added: list[UserSkillInstallation] = []

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, _model: Any, catalog_id: str) -> SkillCatalogEntry | None:
            return entry if catalog_id == entry.id else None

        async def scalar(self, _statement: Any) -> None:
            return None

        def add(self, row: UserSkillInstallation) -> None:
            added.append(row)

        async def commit(self) -> None:
            return None

    markdown = "---\nname: debugging-agent\n---\n# Debugging Agent\nInspect evidence before proposing a fix.\n"

    async def fake_fetch(_entry: SkillCatalogEntry) -> tuple[str, str]:
        return markdown, hashlib.sha256(markdown.encode()).hexdigest()

    monkeypatch.setattr(catalog, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(catalog, "_fetch_skill_markdown", fake_fetch)
    monkeypatch.setattr(marketplace_module, "INSTALLED_DIR", tmp_path / "installed")
    marketplace_module.INSTALLED_DIR.mkdir(parents=True)

    installed = await catalog.install_catalog_skill(
        catalog_id=entry.id,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    assert installed["installed"] is True
    assert installed["installed_skill_id"].startswith("acct-")
    assert len(added) == 1
    assert added[0].status == "installed"
    outcome = catalog.marketplace.test_skill(installed["installed_skill_id"], {"query": "定位服务报错"})
    assert outcome["success"] is True
    assert outcome["output"]["trust"] == "user_enabled_instruction_skill"
    assert "Inspect evidence" in outcome["output"]["instructions"]

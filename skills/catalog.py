"""SkillHub 目录同步、本地镜像与账户级安全安装。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import select, update

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import SkillCatalogEntry, UserSkillInstallation
from skills.local_store import LocalSkillArtifact, local_skill_store
from skills.store.marketplace import marketplace

logger = get_logger(__name__)
_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]{1,255}$")
_CJK = re.compile(r"[\u3400-\u9fff]")
_MAX_SKILL_MARKDOWN_BYTES = 2_000_000
_GITHUB_API_VERSION = "2022-11-28"
_LOCAL_METADATA_KEYS = {
    "local_path",
    "local_revision",
    "local_sha256",
    "local_cached_at",
    "local_status",
    "local_sync_error",
}


@dataclass(frozen=True)
class _CatalogDownload:
    artifact: LocalSkillArtifact | None
    error: str = ""


def _catalog_item(
    row: SkillCatalogEntry, installed: UserSkillInstallation | None = None
) -> dict[str, Any]:
    metadata = dict(row.source_metadata or {})
    local_available = local_skill_store.catalog_available(metadata)
    return {
        "id": row.id,
        "external_id": row.external_id,
        "name": row.name,
        "description": row.description,
        "github_owner": row.github_owner,
        "github_repo": row.github_repo,
        "skill_path": row.skill_path,
        "version": row.version,
        "license": row.license,
        "github_stars": row.github_stars,
        "download_count": row.download_count,
        "security_score": row.security_score,
        "security_status": row.security_status,
        "ai_score": row.ai_score,
        "review_status": row.review_status,
        "is_verified": row.is_verified,
        "rank_popular": row.rank_popular,
        "rank_recent": row.rank_recent,
        "status": row.status,
        "platform_disabled": row.status != "active",
        "platform_note": str(metadata.get("platform_note") or ""),
        "source_url": (
            f"https://github.com/{row.github_owner}/{row.github_repo}/tree/HEAD/{row.skill_path}"
        ),
        "local_available": local_available,
        "local_revision": str(metadata.get("local_revision") or "") or None,
        "local_cached_at": str(metadata.get("local_cached_at") or "") or None,
        "installed": installed is not None and installed.status == "installed",
        "installation_id": installed.id if installed else None,
        "installed_skill_id": installed.installed_skill_id if installed else None,
    }


def _localized_description(item: dict[str, Any]) -> str:
    """优先采用上游中文文案，否则生成稳定的中文能力说明。"""

    raw_i18n = item.get("i18n")
    i18n: dict[str, Any] = raw_i18n if isinstance(raw_i18n, dict) else {}
    raw_zh = i18n.get("zh-CN")
    zh: dict[str, Any] = raw_zh if isinstance(raw_zh, dict) else {}
    candidates = (
        item.get("descriptionZh"),
        item.get("description_zh"),
        zh.get("description"),
        item.get("description"),
    )
    for value in candidates:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text and _CJK.search(text):
            return text[:20000]

    name = re.sub(r"[-_]+", " ", str(item.get("name") or "通用")).strip()
    original = re.sub(r"\s+", " ", str(item.get("description") or "")).strip()
    signal = f"{name} {original}".lower()
    capabilities = (
        (r"debug|diagnos|error|incident|troubleshoot", "软件调试、故障诊断与问题定位"),
        (r"sql|database|data|metric|analytics?|finance", "数据查询、指标分析与结果解读"),
        (r"document|pdf|docx|word|resume|office", "文档阅读、整理、转换与办公处理"),
        (r"search|research|browser|web", "信息搜索、资料研究与证据整理"),
        (r"code|developer|program|api|git|test", "软件开发、代码分析与工程协作"),
        (r"write|content|image|video|audio|voice", "内容创作、多媒体处理与表达优化"),
        (r"workflow|automation|agent|schedule", "自动化工作流设计与任务执行"),
    )
    for pattern, capability in capabilities:
        if re.search(pattern, signal):
            return f"用于{capability}，提供结构化的方法、步骤和操作指导。"
    return f"用于处理与“{name or '该能力'}”相关的专业任务，提供结构化的方法、步骤和操作指导。"


async def _fetch_catalog(sort: str, limit: int) -> list[dict[str, Any]]:
    base = str(settings.skillhub_catalog_url).rstrip("/")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, trust_env=False) as client:
        response = await client.get(f"{base}/api/skills", params={"limit": limit, "sort": sort})
        response.raise_for_status()
        payload = response.json()
    rows = payload.get("skills") if isinstance(payload, dict) else None
    return [item for item in (rows or []) if isinstance(item, dict)]


async def _download_catalog_skill(
    *, external_id: str, item: dict[str, Any], semaphore: asyncio.Semaphore
) -> _CatalogDownload:
    source = type(
        "CatalogSkillSource",
        (),
        {
            "github_owner": str(item.get("githubOwner") or ""),
            "github_repo": str(item.get("githubRepo") or ""),
            "skill_path": str(item.get("skillPath") or ""),
        },
    )()
    try:
        async with semaphore:
            content, revision = await _fetch_skill_markdown(source)
        artifact = local_skill_store.write_catalog_skill(
            external_id=external_id,
            content=content,
            source_revision=revision or hashlib.sha256(content.encode("utf-8")).hexdigest(),
            metadata={
                "provider": "skillhub-palebluedot",
                "name": str(item.get("name") or external_id.rsplit("/", 1)[-1]),
                "description": _localized_description(item),
                "github_owner": source.github_owner,
                "github_repo": source.github_repo,
                "skill_path": source.skill_path,
            },
        )
        return _CatalogDownload(artifact=artifact)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skillhub_local_mirror_download_failed", external_id=external_id, error=str(exc)
        )
        return _CatalogDownload(artifact=None, error=str(exc)[:2000])


async def sync_skillhub_catalog(*, limit: int | None = None) -> dict[str, int]:
    """抓取目录并在提交索引前把 Skill 内容镜像到本地共享存储。"""

    size = max(1, min(int(limit or settings.skillhub_catalog_size), 100))
    popular, recent = await asyncio.gather(
        _fetch_catalog("downloads", size), _fetch_catalog("recent", size)
    )
    indexed: dict[str, dict[str, Any]] = {}
    ranks: dict[str, dict[str, int]] = {}
    for label, rows in (("popular", popular), ("recent", recent)):
        for rank, item in enumerate(rows, start=1):
            external_id = str(item.get("id") or "").strip()
            if not external_id:
                continue
            indexed[external_id] = {**indexed.get(external_id, {}), **item}
            ranks.setdefault(external_id, {})[label] = rank

    semaphore = asyncio.Semaphore(max(1, int(settings.skillhub_sync_download_concurrency)))
    download_results = await asyncio.gather(
        *(
            _download_catalog_skill(external_id=external_id, item=item, semaphore=semaphore)
            for external_id, item in indexed.items()
        )
    )
    downloads = dict(zip(indexed, download_results, strict=True))

    now = datetime.now(UTC)
    added = 0
    updated = 0
    downloaded = 0
    failed = 0
    preserved_local = 0
    preserved_disabled = 0
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(SkillCatalogEntry)
            .where(SkillCatalogEntry.provider == "skillhub-palebluedot")
            .values(rank_popular=None, rank_recent=None)
        )
        for external_id, item in indexed.items():
            row = await db.scalar(
                select(SkillCatalogEntry).where(SkillCatalogEntry.external_id == external_id)
            )
            if row is None:
                row = SkillCatalogEntry(id=str(uuid.uuid4()), external_id=external_id)
                db.add(row)
                row.status = "active"
                added += 1
            else:
                updated += 1
                if row.status != "active":
                    preserved_disabled += 1

            previous_metadata = dict(row.source_metadata or {})
            governance = {
                key: value
                for key, value in previous_metadata.items()
                if key.startswith("platform_")
            }
            previous_local = {
                key: previous_metadata[key]
                for key in _LOCAL_METADATA_KEYS
                if key in previous_metadata
            }
            original_description = str(item.get("description") or "")[:20000]
            row.provider = "skillhub-palebluedot"
            row.name = str(item.get("name") or external_id.rsplit("/", 1)[-1])[:255]
            row.description = _localized_description(item)
            row.github_owner = str(item.get("githubOwner") or "")[:255]
            row.github_repo = str(item.get("githubRepo") or "")[:255]
            row.skill_path = str(item.get("skillPath") or "")[:1024]
            row.version = str(item.get("version") or "")[:128] or None
            row.license = str(item.get("license") or "")[:128] or None
            row.github_stars = int(item.get("githubStars") or 0)
            row.download_count = int(item.get("downloadCount") or 0)
            row.security_score = (
                int(item["securityScore"]) if item.get("securityScore") is not None else None
            )
            row.security_status = str(item.get("securityStatus") or "unknown")[:32]
            row.ai_score = int(item["aiScore"]) if item.get("aiScore") is not None else None
            row.review_status = str(item.get("reviewStatus") or "unknown")[:32]
            row.is_verified = bool(item.get("isVerified"))
            row.rank_popular = ranks.get(external_id, {}).get("popular")
            row.rank_recent = ranks.get(external_id, {}).get("recent")

            metadata = {
                **item,
                **governance,
                "description_original": original_description,
            }
            result = downloads[external_id]
            if result.artifact is not None:
                downloaded += 1
                metadata.update(
                    {
                        "local_path": result.artifact.relative_path,
                        "local_revision": result.artifact.source_revision,
                        "local_sha256": result.artifact.content_sha256,
                        "local_cached_at": result.artifact.cached_at,
                        "local_status": "ready",
                        "local_sync_error": "",
                    }
                )
            elif local_skill_store.catalog_available(previous_local):
                preserved_local += 1
                metadata.update(previous_local)
                metadata["local_status"] = "ready"
                metadata["local_sync_error"] = result.error
            else:
                failed += 1
                metadata.update(
                    {
                        "local_status": "failed",
                        "local_sync_error": result.error,
                    }
                )
            row.source_metadata = metadata
            row.synced_at = now
        await db.commit()
    return {
        "popular": len(popular),
        "recent": len(recent),
        "stored": len(indexed),
        "added": added,
        "updated": updated,
        "downloaded": downloaded,
        "failed": failed,
        "preserved_local": preserved_local,
        "preserved_disabled": preserved_disabled,
    }


def _github_api_headers(token: str = "") -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OpenTrace-SkillHub",
        "X-GitHub-Api-Version": _GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _decode_skill_markdown(raw: bytes) -> tuple[str, str]:
    if not raw or len(raw) > _MAX_SKILL_MARKDOWN_BYTES:
        raise ValueError("invalid_skill_md")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("skill_md_must_be_utf8") from exc
    if not content.strip():
        raise ValueError("invalid_skill_md")
    return content, hashlib.sha256(raw).hexdigest()


async def _fetch_skill_from_github_api(
    client: httpx.AsyncClient,
    *,
    owner: str,
    repo: str,
    skill_file: str,
    token: str,
) -> tuple[str, str | None]:
    url = (
        f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
        f"/contents/{quote(skill_file, safe='/')}"
    )
    response = await client.get(url, headers=_github_api_headers(token))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise ValueError("skill_md_not_found")
    encoded = str(payload.get("content") or "")
    if len(encoded) > (_MAX_SKILL_MARKDOWN_BYTES * 2):
        raise ValueError("invalid_skill_md")
    try:
        raw = base64.b64decode(encoded)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid_skill_md_encoding") from exc
    content, digest = _decode_skill_markdown(raw)
    return content, str(payload.get("sha") or "") or digest


async def _fetch_skill_from_github_raw(
    client: httpx.AsyncClient, *, owner: str, repo: str, skill_file: str
) -> tuple[str, str]:
    url = (
        f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/HEAD/"
        f"{quote(skill_file, safe='/')}"
    )
    response = await client.get(
        url,
        headers={"Accept": "text/plain", "User-Agent": "OpenTrace-SkillHub"},
    )
    response.raise_for_status()
    return _decode_skill_markdown(response.content)


def _github_fallback_allowed(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {401, 403, 408, 429} or exc.response.status_code >= 500
    return False


async def _fetch_skill_markdown(entry: Any) -> tuple[str, str | None]:
    if not _SAFE_PART.fullmatch(entry.github_owner) or not _SAFE_PART.fullmatch(entry.github_repo):
        raise ValueError("invalid_github_repository")
    path = entry.skill_path.strip("/")
    if ".." in path.split("/") or len(path) > 900:
        raise ValueError("invalid_skill_path")
    skill_file = f"{path}/SKILL.md" if path and path != "." else "SKILL.md"
    token = str(settings.skillhub_github_token or "").strip()
    timeout = max(3.0, float(settings.skillhub_github_timeout_seconds))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        raw_error: httpx.HTTPError | None = None
        if not token and settings.skillhub_github_raw_fallback_enabled:
            try:
                return await _fetch_skill_from_github_raw(
                    client,
                    owner=entry.github_owner,
                    repo=entry.github_repo,
                    skill_file=skill_file,
                )
            except httpx.HTTPError as raw_exc:
                raw_error = raw_exc
                logger.warning(
                    "skillhub_github_raw_fallback_failed",
                    repository=f"{entry.github_owner}/{entry.github_repo}",
                    status=getattr(getattr(raw_exc, "response", None), "status_code", None),
                )

        try:
            return await _fetch_skill_from_github_api(
                client,
                owner=entry.github_owner,
                repo=entry.github_repo,
                skill_file=skill_file,
                token=token,
            )
        except httpx.HTTPError as api_exc:
            if not settings.skillhub_github_raw_fallback_enabled or not _github_fallback_allowed(
                api_exc
            ):
                raise
            if raw_error is not None:
                raise raw_error from api_exc
            response = getattr(api_exc, "response", None)
            logger.warning(
                "skillhub_github_api_fallback",
                repository=f"{entry.github_owner}/{entry.github_repo}",
                status=getattr(response, "status_code", None),
                rate_limit_remaining=getattr(response, "headers", {}).get("x-ratelimit-remaining"),
                rate_limit_reset=getattr(response, "headers", {}).get("x-ratelimit-reset"),
            )
            return await _fetch_skill_from_github_raw(
                client,
                owner=entry.github_owner,
                repo=entry.github_repo,
                skill_file=skill_file,
            )


async def install_catalog_skill(
    *, catalog_id: str, user_id: str, tenant_id: str, workspace_id: str
) -> dict[str, Any]:
    """只从本地镜像安装，用户请求链路不得访问 GitHub 或外部 SkillHub。"""

    async with AsyncSessionLocal() as db:
        entry = await db.get(SkillCatalogEntry, catalog_id)
        if entry is None or entry.status != "active":
            raise ValueError("catalog_skill_not_found")
        minimum = int(settings.skillhub_min_security_score)
        if entry.security_status != "pass" or (entry.security_score or 0) < minimum:
            raise PermissionError("skill_security_review_not_passed")
        existing = await db.scalar(
            select(UserSkillInstallation).where(
                UserSkillInstallation.user_id == user_id,
                UserSkillInstallation.tenant_id == tenant_id,
                UserSkillInstallation.workspace_id == workspace_id,
                UserSkillInstallation.catalog_skill_id == catalog_id,
            )
        )
        content, revision = local_skill_store.read_catalog_skill(dict(entry.source_metadata or {}))
        digest = hashlib.sha256(
            f"{user_id}:{tenant_id}:{workspace_id}:{entry.external_id}".encode()
        ).hexdigest()[:12]
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", entry.name).strip("-")[:70] or "skill"
        version = re.sub(r"[^A-Za-z0-9_.+-]+", "-", entry.version or "latest")[:40]
        installed_skill_id = f"acct-{digest}-{slug}@{version}"
        installed = marketplace.install_instructional(
            skill_id=installed_skill_id,
            name=entry.name,
            version=version,
            description=entry.description,
            instructions=content,
            source={
                "provider": entry.provider,
                "external_id": entry.external_id,
                "revision": revision,
                "delivery": "local_mirror",
            },
        )
        row = existing or UserSkillInstallation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            catalog_skill_id=catalog_id,
            installed_skill_id=installed_skill_id,
        )
        if existing is None:
            db.add(row)
        row.installed_skill_id = installed_skill_id
        row.status = "installed"
        row.source_revision = revision
        row.error = None
        row.manifest_snapshot = {
            "name": installed.name,
            "version": installed.version,
            "description": installed.description,
            "external_id": entry.external_id,
            "security_score": entry.security_score,
            "ai_score": entry.ai_score,
            "delivery": "local_mirror",
        }
        await db.commit()
        return _catalog_item(entry, row)


def _seconds_until_next_sync(now: datetime | None = None) -> int:
    try:
        timezone = ZoneInfo(str(settings.skillhub_sync_timezone or "Asia/Shanghai"))
    except ZoneInfoNotFoundError:
        logger.warning(
            "skillhub_sync_timezone_invalid", timezone=str(settings.skillhub_sync_timezone)
        )
        timezone = ZoneInfo("Asia/Shanghai")
    current = now or datetime.now(timezone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone)
    else:
        current = current.astimezone(timezone)
    hour = min(23, max(0, int(settings.skillhub_sync_hour)))
    minute = min(59, max(0, int(settings.skillhub_sync_minute)))
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return max(1, math.ceil((target - current).total_seconds()))


async def skillhub_sync_loop() -> None:
    retry_interval = max(5, int(settings.skillhub_sync_retry_seconds))
    while True:
        try:
            if settings.skillhub_sync_enabled:
                await sync_skillhub_catalog()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("skillhub_sync_failed", error=str(exc))
            await asyncio.sleep(retry_interval)
            continue
        await asyncio.sleep(_seconds_until_next_sync())

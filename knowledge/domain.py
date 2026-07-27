"""Stable vocabulary shared by ingestion, retrieval, governance and APIs."""

from __future__ import annotations

from enum import StrEnum


class KnowledgeStatus(StrEnum):
    DRAFT = "draft"
    COMPILING = "compiling"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    STALE = "stale"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    ERROR = "error"


class KnowledgeAuthority(StrEnum):
    OFFICIAL = "official"
    APPROVED = "approved"
    VERIFIED = "verified"
    INFERRED = "inferred"
    CONTEXTUAL = "contextual"
    USER_MEMORY = "user_memory"
    EXTERNAL = "external"


class KnowledgeType(StrEnum):
    OVERVIEW = "overview"
    CONCEPT = "concept"
    ENTITY = "entity"
    FACT = "fact"
    PROCEDURE = "procedure"
    POLICY = "policy"
    QUESTION = "question"
    CASE = "case"
    METRIC = "metric"
    TERM = "term"


class KnowledgeDisclosureStage(StrEnum):
    HOT = "hot"
    SUMMARY = "summary"
    PAGE = "page"
    CLAIM = "claim"
    RELATION = "relation"
    SOURCE_EVIDENCE = "source_evidence"


class KnowledgeReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"


KNOWLEDGE_COMPILER_VERSION = "knowledge_compiler_v1"
KNOWLEDGE_QUERY_PLAN_VERSION = "knowledge_query_plan_v1"
KNOWLEDGE_EVIDENCE_VERSION = "knowledge_evidence_object_v1"
KNOWLEDGE_RULESET_VERSION = "knowledge_ruleset_v1"


def source_is_withdrawn(
    *,
    status: str | None,
    sync_status: str | None,
    deleted_at: object | None,
) -> bool:
    """撤回是持久化治理状态，后台补偿任务不得自动重新激活来源。"""

    return bool(
        deleted_at is not None
        or sync_status == "deleted"
        or status == KnowledgeStatus.DEPRECATED.value
    )


def source_status_during_refresh(
    active_version_id: str | None,
    fallback: KnowledgeStatus,
) -> str:
    """重编译期间保留上一已发布版本的在线可见性。"""
    if active_version_id:
        return KnowledgeStatus.PUBLISHED.value
    return fallback.value

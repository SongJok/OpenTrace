"""Metadata-layer rule resolution for deterministic knowledge compilation."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import KnowledgeRule
from knowledge.domain import KNOWLEDGE_RULESET_VERSION


async def active_rule_version(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    rule_key: str = "knowledge_compiler",
) -> str:
    row = await active_rule(db, tenant_id=tenant_id, workspace_id=workspace_id, rule_key=rule_key)
    return f"{rule_key}_v{row.version}" if row else KNOWLEDGE_RULESET_VERSION


async def active_rule(
    db: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    rule_key: str = "knowledge_compiler",
) -> KnowledgeRule | None:
    base = (
        KnowledgeRule.tenant_id == tenant_id,
        KnowledgeRule.workspace_id == workspace_id,
        KnowledgeRule.rule_key == rule_key,
        KnowledgeRule.status == "approved",
    )
    return await db.scalar(select(KnowledgeRule).where(*base).order_by(desc(KnowledgeRule.version)))


def validate_compiled_payload(
    rule: KnowledgeRule | None,
    *,
    pages: list[dict],
    claims: list[dict],
    relations: list[dict],
) -> None:
    """Apply the approved metadata schema without requiring a JSONSchema package.

    Rules can declare ``required_page_fields``, ``required_claim_fields``,
    ``required_relation_fields`` and ``allowed_page_types`` in ``schema_json``.
    Empty/default rules preserve the compiler's built-in contract.
    """
    schema = (rule.schema_json if rule is not None else {}) or {}
    checks = (
        ("pages", pages, schema.get("required_page_fields", [])),
        ("claims", claims, schema.get("required_claim_fields", [])),
        ("relations", relations, schema.get("required_relation_fields", [])),
    )
    for label, items, required in checks:
        for field in required or []:
            if any(not item.get(field) for item in items):
                raise ValueError(f"knowledge_rule_missing_{label}_field:{field}")
    allowed_types = set(schema.get("allowed_page_types") or [])
    if allowed_types and any(item.get("page_type") not in allowed_types for item in pages):
        raise ValueError("knowledge_rule_invalid_page_type")

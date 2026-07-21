"""Add governed knowledge orchestration storage."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260713_knowledge_orchestration"
down_revision = "20260712_connector_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "knowledge_sources" not in tables:
        op.create_table(
            "knowledge_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), nullable=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("source_type", sa.String(64), nullable=False, server_default="document"),
            sa.Column("external_ref", sa.String(512), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("authority", sa.String(32), nullable=False, server_default="contextual"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("active_version_id", sa.String(36), nullable=True),
            sa.Column("source_metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("tenant_id", "workspace_id", "document_id", name="uq_knowledge_source_document_scope"),
        )
        op.create_index("ix_knowledge_sources_document_id", "knowledge_sources", ["document_id"])
        op.create_index("ix_knowledge_sources_owner_id", "knowledge_sources", ["owner_id"])
        op.create_index("ix_knowledge_sources_tenant_id", "knowledge_sources", ["tenant_id"])
        op.create_index("ix_knowledge_sources_workspace_id", "knowledge_sources", ["workspace_id"])
        op.create_index("ix_knowledge_sources_content_hash", "knowledge_sources", ["content_hash"])
        op.create_index("ix_knowledge_sources_status", "knowledge_sources", ["status"])
    if "knowledge_source_versions" not in tables:
        op.create_table(
            "knowledge_source_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_id", sa.String(36), sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("compiler_version", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("raw_metadata", sa.JSON(), nullable=False),
            sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("source_id", "version_number", name="uq_knowledge_source_version"),
        )
        op.create_index("ix_knowledge_source_versions_source_id", "knowledge_source_versions", ["source_id"])
        op.create_index("ix_knowledge_source_versions_content_hash", "knowledge_source_versions", ["content_hash"])
        op.create_index("ix_knowledge_source_versions_status", "knowledge_source_versions", ["status"])
    if "knowledge_pages" not in tables:
        op.create_table(
            "knowledge_pages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_version_id", sa.String(36), sa.ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("page_type", sa.String(32), nullable=False, server_default="overview"),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("schema_name", sa.String(128), nullable=False, server_default="knowledge_page_v1"),
            sa.Column("authority", sa.String(32), nullable=False, server_default="contextual"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("page_metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("source_version_id", "slug", name="uq_knowledge_page_version_slug"),
        )
        for column in ("source_version_id", "owner_id", "tenant_id", "workspace_id", "page_type", "status"):
            op.create_index(f"ix_knowledge_pages_{column}", "knowledge_pages", [column])
    if "knowledge_claims" not in tables:
        op.create_table(
            "knowledge_claims",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_version_id", sa.String(36), sa.ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("page_id", sa.String(36), sa.ForeignKey("knowledge_pages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("claim_type", sa.String(32), nullable=False, server_default="fact"),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("normalized_text", sa.Text(), nullable=False),
            sa.Column("claim_hash", sa.String(64), nullable=False),
            sa.Column("evidence_chunk_id", sa.String(36), nullable=True),
            sa.Column("evidence_start", sa.Integer(), nullable=True),
            sa.Column("evidence_end", sa.Integer(), nullable=True),
            sa.Column("authority", sa.String(32), nullable=False, server_default="contextual"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
            sa.Column("claim_metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("page_id", "claim_hash", name="uq_knowledge_claim_page_hash"),
        )
        for column in ("source_version_id", "page_id", "owner_id", "tenant_id", "workspace_id", "claim_type", "claim_hash", "evidence_chunk_id", "status"):
            op.create_index(f"ix_knowledge_claims_{column}", "knowledge_claims", [column])
    if "knowledge_relations" not in tables:
        op.create_table(
            "knowledge_relations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_version_id", sa.String(36), sa.ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("source_page_id", sa.String(36), sa.ForeignKey("knowledge_pages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_page_id", sa.String(36), sa.ForeignKey("knowledge_pages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("relation_type", sa.String(64), nullable=False),
            sa.Column("authority", sa.String(32), nullable=False, server_default="contextual"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("relation_metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("source_page_id", "target_page_id", "relation_type", name="uq_knowledge_relation"),
        )
        for column in ("source_version_id", "owner_id", "tenant_id", "workspace_id", "source_page_id", "target_page_id", "relation_type", "status"):
            op.create_index(f"ix_knowledge_relations_{column}", "knowledge_relations", [column])
    if "knowledge_compilation_jobs" not in tables:
        op.create_table(
            "knowledge_compilation_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("source_id", sa.String(36), nullable=False),
            sa.Column("source_version_id", sa.String(36), nullable=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("compiler_version", sa.String(64), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("result_metadata", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        for column in ("source_id", "source_version_id", "owner_id", "tenant_id", "workspace_id", "status"):
            op.create_index(f"ix_knowledge_compilation_jobs_{column}", "knowledge_compilation_jobs", [column])
    if "knowledge_lint_issues" not in tables:
        op.create_table(
            "knowledge_lint_issues",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("issue_key", sa.String(128), nullable=False),
            sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", sa.String(36), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "workspace_id", "issue_key", name="uq_knowledge_lint_issue_scope"),
        )
        for column in ("owner_id", "tenant_id", "workspace_id", "severity", "code", "resource_id", "status"):
            op.create_index(f"ix_knowledge_lint_issues_{column}", "knowledge_lint_issues", [column])
    if "knowledge_feedback" not in tables:
        op.create_table(
            "knowledge_feedback",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("session_id", sa.String(36), nullable=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("target_type", sa.String(64), nullable=False),
            sa.Column("target_id", sa.String(36), nullable=False),
            sa.Column("feedback_type", sa.String(32), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("correction", sa.Text(), nullable=True),
            sa.Column("feedback_metadata", sa.JSON(), nullable=False),
            sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        for column in ("session_id", "user_id", "tenant_id", "workspace_id", "target_type", "target_id", "feedback_type"):
            op.create_index(f"ix_knowledge_feedback_{column}", "knowledge_feedback", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "knowledge_feedback",
        "knowledge_lint_issues",
        "knowledge_compilation_jobs",
        "knowledge_relations",
        "knowledge_claims",
        "knowledge_pages",
        "knowledge_source_versions",
        "knowledge_sources",
    ):
        if table in inspector.get_table_names():
            op.drop_table(table)

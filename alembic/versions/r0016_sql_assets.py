"""SQL 资产、查询草案与候选执行账本

Revision ID: r0016_sql_assets
Revises: r0015_enterprise_workbench_templates
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0016_sql_assets"
down_revision = "r0015_enterprise_workbench_templates"
branch_labels = None
depends_on = None


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "sql_asset_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column(
            "data_source_id",
            sa.String(36),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False, server_default="text/plain"),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("dialect", sa.String(32), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False, server_default="sqlglot-v1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="parsed"),
        sa.Column("statement_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_report", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "content_sha256",
            name="uq_sql_asset_source_scope_hash",
        ),
    )
    op.create_table(
        "sql_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("sql_asset_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column(
            "data_source_id",
            sa.String(36),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("statement_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("normalized_sql", sa.Text(), nullable=False),
        sa.Column("sql_hash", sa.String(64), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("statement_type", sa.String(64), nullable=False),
        sa.Column("executable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("dialect", sa.String(32), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("columns", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("lineage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("validation_report", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("schema_fingerprint", sa.String(64), nullable=True),
        sa.Column("source_start_line", sa.Integer(), nullable=True),
        sa.Column("source_end_line", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("source_id", "statement_index", name="uq_sql_asset_source_statement"),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "sql_hash",
            name="uq_sql_asset_scope_hash",
        ),
    )
    op.create_table(
        "sql_query_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("response_id", sa.String(64), nullable=True),
        sa.Column(
            "data_source_id",
            sa.String(36),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("group_type", sa.String(20), nullable=False, server_default="alternative"),
        sa.Column("status", sa.String(32), nullable=False, server_default="awaiting_confirmation"),
        sa.Column("dialect", sa.String(32), nullable=False),
        sa.Column("schema_fingerprint", sa.String(64), nullable=True),
        sa.Column(
            "selected_candidate_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("execution_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "sql_query_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "draft_id",
            sa.String(36),
            sa.ForeignKey("sql_query_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("sql_hash", sa.String(64), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("tables", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("columns", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("assumptions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("validation_report", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("result_rows", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("draft_id", "position", name="uq_sql_query_candidate_position"),
        sa.UniqueConstraint("draft_id", "sql_hash", name="uq_sql_query_candidate_hash"),
    )

    indexes = {
        "sql_asset_sources": (
            "user_id",
            "tenant_id",
            "workspace_id",
            "project_id",
            "data_source_id",
            "status",
        ),
        "sql_assets": (
            "source_id",
            "user_id",
            "tenant_id",
            "workspace_id",
            "project_id",
            "data_source_id",
            "sql_hash",
            "asset_type",
            "status",
        ),
        "sql_query_drafts": (
            "user_id",
            "tenant_id",
            "workspace_id",
            "project_id",
            "conversation_id",
            "response_id",
            "data_source_id",
            "status",
        ),
        "sql_query_candidates": ("draft_id",),
    }
    for table, columns in indexes.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_index(
        "ix_sql_assets_retrieval_scope",
        "sql_assets",
        ["tenant_id", "workspace_id", "data_source_id", "status"],
    )
    op.create_index(
        "ix_sql_query_drafts_scope_created",
        "sql_query_drafts",
        ["user_id", "tenant_id", "workspace_id", "created_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        for table in ("sql_asset_sources", "sql_assets", "sql_query_drafts"):
            op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(
                f"""CREATE POLICY "{table}_scope_isolation" ON "{table}"
                    USING (
                        current_setting('app.service_role', true) = 'worker'
                        OR (
                            tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                            AND workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')
                        )
                    )
                    WITH CHECK (
                        current_setting('app.service_role', true) = 'worker'
                        OR (
                            tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                            AND workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')
                        )
                    )"""
            )
        op.execute('ALTER TABLE "sql_query_candidates" ENABLE ROW LEVEL SECURITY')
        op.execute(
            """CREATE POLICY "sql_query_candidates_draft_scope_isolation"
               ON "sql_query_candidates"
               USING (
                   current_setting('app.service_role', true) = 'worker'
                   OR EXISTS (
                       SELECT 1 FROM sql_query_drafts d
                       WHERE d.id = sql_query_candidates.draft_id
                         AND d.tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                         AND d.workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')
                   )
               )"""
        )


def downgrade() -> None:
    op.drop_table("sql_query_candidates")
    op.drop_table("sql_query_drafts")
    op.drop_table("sql_assets")
    op.drop_table("sql_asset_sources")

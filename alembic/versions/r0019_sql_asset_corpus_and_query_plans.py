"""sql_asset_corpus_and_query_plans

Revision ID: r0019_sql_asset_corpus_and_query_plans
Revises: r0018_data_knowledge
Create Date: 2026-08-08 15:49:43.619687
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0019_sql_asset_corpus_and_query_plans"
down_revision = "r0018_data_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sql_assets",
        sa.Column("structure_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sql_assets",
        sa.Column("corpus_role", sa.String(length=20), nullable=False, server_default="retrieval"),
    )
    op.add_column(
        "sql_assets",
        sa.Column(
            "quality_status", sa.String(length=20), nullable=False, server_default="unverified"
        ),
    )
    op.add_column("sql_assets", sa.Column("domain", sa.String(length=100), nullable=True))
    op.add_column("sql_assets", sa.Column("owner", sa.String(length=255), nullable=True))
    op.add_column(
        "sql_assets",
        sa.Column("risk_flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "sql_assets",
        sa.Column(
            "verification_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "sql_assets", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sql_assets",
        sa.Column("retrieval_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE sql_assets SET structure_hash = sql_hash WHERE structure_hash IS NULL")
    op.alter_column("sql_assets", "structure_hash", nullable=False)
    op.execute(
        "UPDATE sql_assets SET quality_status = 'verified', last_verified_at = approved_at "
        "WHERE status = 'published' AND executable = true"
    )
    op.execute(
        "UPDATE sql_assets SET corpus_role = 'quarantine' "
        "WHERE executable = false OR asset_type <> 'query'"
    )
    for column in ("structure_hash", "corpus_role", "quality_status", "domain"):
        op.create_index(f"ix_sql_assets_{column}", "sql_assets", [column], unique=False)

    op.add_column(
        "sql_query_drafts",
        sa.Column("output_mode", sa.String(length=24), nullable=False, server_default="sql_only"),
    )
    op.add_column(
        "sql_query_drafts",
        sa.Column("query_plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.add_column(
        "sql_query_drafts",
        sa.Column("clarification", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )


def downgrade() -> None:
    for column in ("clarification", "query_plan", "output_mode"):
        op.drop_column("sql_query_drafts", column)
    for column in ("domain", "quality_status", "corpus_role", "structure_hash"):
        op.drop_index(f"ix_sql_assets_{column}", table_name="sql_assets")
    for column in (
        "retrieval_count",
        "last_verified_at",
        "verification_metadata",
        "risk_flags",
        "owner",
        "domain",
        "quality_status",
        "corpus_role",
        "structure_hash",
    ):
        op.drop_column("sql_assets", column)

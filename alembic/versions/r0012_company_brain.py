"""Add the deployment-scoped company brain and versioned COMPANY.md source ledger.

Revision ID: r0012_company_brain
Revises: r0011_user_custom_models
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0012_company_brain"
down_revision = "r0011_user_custom_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "user_memories" in tables:
        memory_columns = {column["name"] for column in inspector.get_columns("user_memories")}
        if "personal_category" not in memory_columns:
            op.add_column(
                "user_memories",
                sa.Column(
                    "personal_category", sa.String(30), nullable=False, server_default="profile"
                ),
            )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_user_memories_personal_category "
            "ON user_memories (personal_category)"
        )
    if "memory_candidates" in tables:
        candidate_columns = {
            column["name"] for column in inspector.get_columns("memory_candidates")
        }
        if "personal_category" not in candidate_columns:
            op.add_column(
                "memory_candidates",
                sa.Column(
                    "personal_category", sa.String(30), nullable=False, server_default="profile"
                ),
            )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memory_candidates_personal_category "
            "ON memory_candidates (personal_category)"
        )
    if "company_profiles" not in tables:
        op.create_table(
            "company_profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("singleton_key", sa.String(20), nullable=False, server_default="primary"),
            sa.Column("legal_name", sa.String(255), nullable=False),
            sa.Column("short_name", sa.String(32), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("current_version_id", sa.String(36), nullable=True),
            sa.Column("last_maintenance_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_daily_maintenance_date", sa.String(10), nullable=True),
            sa.Column(
                "created_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("singleton_key", name="uq_company_profiles_singleton"),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_company_profiles_current_version_id "
        "ON company_profiles (current_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_company_profiles_last_daily_maintenance_date "
        "ON company_profiles (last_daily_maintenance_date)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_company_profiles_created_by "
        "ON company_profiles (created_by)"
    )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "company_brain_sources" not in tables:
        op.create_table(
            "company_brain_sources",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "company_id",
                sa.String(36),
                sa.ForeignKey("company_profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("folder", sa.String(20), nullable=False),
            sa.Column("memory_tier", sa.String(20), nullable=False),
            sa.Column("source_type", sa.String(20), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("source_content", sa.Text(), nullable=False),
            sa.Column("processed_content", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("salience", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("source_response_id", sa.String(64), nullable=True),
            sa.Column(
                "created_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    for column in (
        "company_id",
        "folder",
        "memory_tier",
        "source_type",
        "status",
        "active",
        "source_response_id",
        "created_by",
    ):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_company_brain_sources_{column} "
            f"ON company_brain_sources ({column})"
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "company_brain_versions" not in tables:
        op.create_table(
            "company_brain_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "company_id",
                sa.String(36),
                sa.ForeignKey("company_profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("long_term_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("medium_term_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("short_term_chars", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("trigger", sa.String(32), nullable=False, server_default="manual"),
            sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "created_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "published_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("company_id", "version", name="uq_company_brain_version"),
        )
    for column in ("company_id", "status", "created_by", "published_by", "published_at"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_company_brain_versions_{column} "
            f"ON company_brain_versions ({column})"
        )


def downgrade() -> None:
    op.drop_table("company_brain_versions")
    op.drop_table("company_brain_sources")
    op.drop_table("company_profiles")
    op.drop_column("memory_candidates", "personal_category")
    op.drop_column("user_memories", "personal_category")

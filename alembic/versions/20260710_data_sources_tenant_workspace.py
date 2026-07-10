"""Add tenant and workspace scope to data sources."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260710_data_sources_tenant"
down_revision = "20260613_documents_tenant"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {column["name"] for column in inspector.get_columns(table)}
    except Exception:
        return set()


def _index_exists(inspector: sa.Inspector, table: str, name: str) -> bool:
    try:
        return any(index.get("name") == name for index in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "data_sources" not in inspector.get_table_names():
        return

    columns = _column_names(inspector, "data_sources")
    if "tenant_id" not in columns:
        op.add_column(
            "data_sources",
            sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default="default"),
        )
    if "workspace_id" not in columns:
        op.add_column(
            "data_sources",
            sa.Column("workspace_id", sa.String(length=128), nullable=False, server_default="default"),
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "data_sources", "ix_data_sources_tenant_id"):
        op.create_index("ix_data_sources_tenant_id", "data_sources", ["tenant_id"], unique=False)
    if not _index_exists(inspector, "data_sources", "ix_data_sources_scope_owner"):
        op.create_index(
            "ix_data_sources_scope_owner",
            "data_sources",
            ["tenant_id", "workspace_id", "user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "data_sources" not in inspector.get_table_names():
        return
    if _index_exists(inspector, "data_sources", "ix_data_sources_scope_owner"):
        op.drop_index("ix_data_sources_scope_owner", table_name="data_sources")
    if _index_exists(inspector, "data_sources", "ix_data_sources_tenant_id"):
        op.drop_index("ix_data_sources_tenant_id", table_name="data_sources")
    columns = _column_names(inspector, "data_sources")
    if "workspace_id" in columns:
        op.drop_column("data_sources", "workspace_id")
    if "tenant_id" in columns:
        op.drop_column("data_sources", "tenant_id")

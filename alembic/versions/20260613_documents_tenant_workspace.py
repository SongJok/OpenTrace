"""documents.tenant_id + workspace_id columns and indexes (RAG scope)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260613_documents_tenant"
down_revision = "20260611_billing_invoice"
branch_labels = None
depends_on = None


def _col_names(insp: sa.Inspector, table: str) -> set[str]:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _index_exists(insp: sa.Inspector, table: str, name: str) -> bool:
    try:
        return any(ix.get("name") == name for ix in insp.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "documents" not in insp.get_table_names():
        return
    cols = _col_names(insp, "documents")
    if "tenant_id" not in cols:
        op.add_column(
            "documents",
            sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default="default"),
        )
    if "workspace_id" not in cols:
        op.add_column(
            "documents",
            sa.Column("workspace_id", sa.String(length=128), nullable=False, server_default="default"),
        )
    insp = sa.inspect(bind)
    if not _index_exists(insp, "documents", "ix_documents_tenant_id"):
        op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"], unique=False)
    if not _index_exists(insp, "documents", "ix_documents_tenant_workspace"):
        op.create_index(
            "ix_documents_tenant_workspace",
            "documents",
            ["tenant_id", "workspace_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "documents" not in insp.get_table_names():
        return
    if _index_exists(insp, "documents", "ix_documents_tenant_workspace"):
        op.drop_index("ix_documents_tenant_workspace", table_name="documents")
    if _index_exists(insp, "documents", "ix_documents_tenant_id"):
        op.drop_index("ix_documents_tenant_id", table_name="documents")
    cols = _col_names(insp, "documents")
    if "workspace_id" in cols:
        op.drop_column("documents", "workspace_id")
    if "tenant_id" in cols:
        op.drop_column("documents", "tenant_id")
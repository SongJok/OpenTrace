"""Enterprise tenant tables and chat_sessions tenant columns."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260606_enterprise_tenant"
down_revision = "20260406_chat_session_stage1"
branch_labels = None
depends_on = None


def _column_names(insp: sa.Inspector, table: str) -> set[str]:
    try:
        return {c.get("name") for c in insp.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "tenants" not in insp.get_table_names():
        op.create_table(
            "tenants",
            sa.Column("tenant_id", sa.String(128), primary_key=True),
            sa.Column("name", sa.String(255), server_default=""),
            sa.Column("tier", sa.String(64), server_default="standard"),
            sa.Column("data_residency", sa.String(64), server_default="global"),
            sa.Column("metadata_json", sa.JSON(), server_default="{}"),
        )
    if "chat_sessions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chat_sessions")}
        if "tenant_id" not in cols:
            op.add_column(
                "chat_sessions",
                sa.Column("tenant_id", sa.String(128), server_default="default", nullable=False),
            )
        if "org_id" not in cols:
            op.add_column(
                "chat_sessions",
                sa.Column("org_id", sa.String(128), server_default="default", nullable=False),
            )
        if "workspace_id" not in cols:
            op.add_column(
                "chat_sessions",
                sa.Column("workspace_id", sa.String(128), server_default="default", nullable=False),
            )


def downgrade() -> None:
    pass
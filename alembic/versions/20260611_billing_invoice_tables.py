"""Billing ledger + invoice line items (enterprise reconciliation)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260611_billing_invoice"
down_revision = "20260610_merge_heads"
branch_labels = None
depends_on = None


def _table_exists(insp: sa.Inspector, table: str) -> bool:
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        if _table_exists(insp, "billing_ledger"):
            insp.get_columns("billing_ledger")
    except Exception:
        pass

    if not _table_exists(insp, "billing_ledger"):
        op.create_table(
            "billing_ledger",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
            sa.Column("org_id", sa.String(128), nullable=True),
            sa.Column("workspace_id", sa.String(128), nullable=True),
            sa.Column("session_id", sa.String(128), nullable=True),
            sa.Column("goal_id", sa.String(128), nullable=True),
            sa.Column("capability_type", sa.String(128), nullable=True),
            sa.Column("cost_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("metadata_json", JSONB if bind.dialect.name == "postgresql" else sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )
        op.create_index("ix_billing_ledger_tenant_created", "billing_ledger", ["tenant_id", "created_at"])

    if not _table_exists(insp, "billing_invoices"):
        op.create_table(
            "billing_invoices",
            sa.Column("invoice_id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, index=True),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("total_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("line_items_json", JSONB if bind.dialect.name == "postgresql" else sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _table_exists(insp, "billing_invoices"):
        op.drop_table("billing_invoices")
    if _table_exists(insp, "billing_ledger"):
        op.drop_index("ix_billing_ledger_tenant_created", table_name="billing_ledger")
        op.drop_table("billing_ledger")
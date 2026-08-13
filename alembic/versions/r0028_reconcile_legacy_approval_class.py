"""reconcile legacy runtime approval class column

Revision ID: r0028_reconcile_legacy_approval_class
Revises: r0027_add_data_agent_run_purpose
Create Date: 2026-08-13 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0028_reconcile_legacy_approval_class"
down_revision = "r0027_add_data_agent_run_purpose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("response_approvals")}
    if "operation_class_legacy" not in columns:
        return
    if "operation_class" not in columns:
        op.add_column(
            "response_approvals",
            sa.Column(
                "operation_class",
                sa.String(length=32),
                nullable=False,
                server_default="write",
            ),
        )
    op.execute(
        sa.text(
            "UPDATE response_approvals SET operation_class = operation_class_legacy "
            "WHERE operation_class = 'write' "
            "AND operation_class_legacy IS NOT NULL "
            "AND operation_class_legacy <> 'write'"
        )
    )
    op.drop_column("response_approvals", "operation_class_legacy")


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("response_approvals")}
    if "operation_class" not in columns or "operation_class_legacy" in columns:
        return
    op.add_column(
        "response_approvals",
        sa.Column(
            "operation_class_legacy",
            sa.String(length=32),
            nullable=False,
            server_default="write",
        ),
    )
    op.execute(sa.text("UPDATE response_approvals SET operation_class_legacy = operation_class"))

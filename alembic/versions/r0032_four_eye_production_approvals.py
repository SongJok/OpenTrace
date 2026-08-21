"""高风险生产操作四眼审批事实

Revision ID: r0032_four_eye_production_approvals
Revises: r0031_production_asset_sync_runtime
Create Date: 2026-08-20 18:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0032_four_eye_production_approvals"
down_revision = "r0031_production_asset_sync_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "response_approvals",
        sa.Column("required_approvals", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "response_approvals",
        sa.Column(
            "approval_decisions",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.create_check_constraint(
        "ck_response_approval_required_count",
        "response_approvals",
        "required_approvals BETWEEN 1 AND 2",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_response_approval_required_count",
        "response_approvals",
        type_="check",
    )
    op.drop_column("response_approvals", "approval_decisions")
    op.drop_column("response_approvals", "required_approvals")

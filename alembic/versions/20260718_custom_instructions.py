"""Add explicit, scoped custom instructions separate from learned memory."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260718_custom_instructions"
down_revision = "20260717_response_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_custom_instructions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("workspace_id", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("about_user", sa.Text(), nullable=False, server_default=""),
        sa.Column("response_style", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("user_id", "tenant_id", "workspace_id", name="uq_custom_instruction_scope"),
    )
    op.create_index("ix_custom_instructions_user_id", "user_custom_instructions", ["user_id"])
    op.create_index("ix_custom_instructions_tenant_id", "user_custom_instructions", ["tenant_id"])
    op.create_index("ix_custom_instructions_workspace_id", "user_custom_instructions", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("user_custom_instructions")

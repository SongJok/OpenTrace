"""Add encrypted, tenant-scoped connector credential storage."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260712_connector_credentials"
down_revision = "20260711_chat_session_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "connector_credentials" in inspector.get_table_names():
        return
    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=False),
        sa.Column("credential_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            "provider",
            name="uq_connector_credential_scope_provider",
        ),
    )
    op.create_index("ix_connector_credentials_user_id", "connector_credentials", ["user_id"])
    op.create_index("ix_connector_credentials_tenant_id", "connector_credentials", ["tenant_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "connector_credentials" not in inspector.get_table_names():
        return
    op.drop_index("ix_connector_credentials_tenant_id", table_name="connector_credentials")
    op.drop_index("ix_connector_credentials_user_id", table_name="connector_credentials")
    op.drop_table("connector_credentials")

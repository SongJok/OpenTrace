"""add redis shadow kv table

Revision ID: 20260401_redis_shadow
Revises:
Create Date: 2026-04-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260401_redis_shadow"
down_revision = "20260400_core_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "redis_shadow_kv" not in tables:
        op.create_table(
            "redis_shadow_kv",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("redis_db", sa.Integer(), nullable=False),
            sa.Column("redis_key", sa.String(length=255), nullable=False),
            sa.Column("data_type", sa.String(length=20), nullable=False, server_default="string"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("expire_at_ts", sa.Float(), nullable=True),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("redis_db", "redis_key", name="uq_redis_shadow_db_key"),
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("redis_shadow_kv")} if "redis_shadow_kv" in set(inspector.get_table_names()) else set()
    if "ix_redis_shadow_kv_redis_db" not in indexes:
        op.create_index("ix_redis_shadow_kv_redis_db", "redis_shadow_kv", ["redis_db"], unique=False)
    if "ix_redis_shadow_kv_redis_key" not in indexes:
        op.create_index("ix_redis_shadow_kv_redis_key", "redis_shadow_kv", ["redis_key"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "redis_shadow_kv" not in set(inspector.get_table_names()):
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("redis_shadow_kv")}
    if "ix_redis_shadow_kv_redis_key" in indexes:
        op.drop_index("ix_redis_shadow_kv_redis_key", table_name="redis_shadow_kv")
    if "ix_redis_shadow_kv_redis_db" in indexes:
        op.drop_index("ix_redis_shadow_kv_redis_db", table_name="redis_shadow_kv")

    op.drop_table("redis_shadow_kv")

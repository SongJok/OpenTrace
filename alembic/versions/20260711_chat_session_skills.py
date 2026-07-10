"""Persist per-session skill bindings for multi-replica runtimes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260711_chat_session_skills"
down_revision = "20260710_data_sources_tenant"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {column["name"] for column in inspector.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_sessions" not in inspector.get_table_names():
        return

    columns = _column_names(inspector, "chat_sessions")
    if "enabled_skills" not in columns:
        op.add_column(
            "chat_sessions",
            sa.Column(
                "enabled_skills",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
    if "disabled_skills" not in columns:
        op.add_column(
            "chat_sessions",
            sa.Column(
                "disabled_skills",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chat_sessions" not in inspector.get_table_names():
        return
    columns = _column_names(inspector, "chat_sessions")
    if "disabled_skills" in columns:
        op.drop_column("chat_sessions", "disabled_skills")
    if "enabled_skills" in columns:
        op.drop_column("chat_sessions", "enabled_skills")

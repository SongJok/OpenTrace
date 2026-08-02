"""Add governed calendar memory lifecycle and append-only revisions.

Revision ID: r0013_calendar_memory_lifecycle
Revises: r0012_company_brain
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0013_calendar_memory_lifecycle"
down_revision = "r0012_company_brain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("calendar_events")}
    if "revision" not in columns:
        op.add_column(
            "calendar_events",
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        )
    if "cancelled_at" not in columns:
        op.add_column(
            "calendar_events",
            sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        )

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "calendar_event_revisions" not in tables:
        op.create_table(
            "calendar_event_revisions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "event_id",
                sa.String(36),
                sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("workspace_id", sa.String(128), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("changed_fields", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("source_response_id", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("event_id", "revision", name="uq_calendar_event_revision"),
        )
    for columns, suffix in (
        (("event_id",), "event_id"),
        (("user_id", "tenant_id", "workspace_id", "created_at"), "scope_created"),
        (("action",), "action"),
        (("source_response_id",), "source_response_id"),
    ):
        op.create_index(
            f"ix_calendar_event_revisions_{suffix}",
            "calendar_event_revisions",
            list(columns),
            unique=False,
            if_not_exists=True,
        )

    op.execute(
        "UPDATE calendar_events SET cancelled_at = updated_at "
        "WHERE status = 'cancelled' AND cancelled_at IS NULL"
    )
    op.execute(
        """
        INSERT INTO calendar_event_revisions (
            id, event_id, user_id, tenant_id, workspace_id, revision, action,
            snapshot, changed_fields, source, source_response_id, created_at
        )
        SELECT
            'legacy-' || substring(md5(event.id), 1, 29),
            event.id,
            event.user_id,
            event.tenant_id,
            event.workspace_id,
            event.revision,
            CASE WHEN event.status = 'cancelled' THEN 'cancelled' ELSE 'imported' END,
            json_build_object(
                'id', event.id,
                'title', event.title,
                'description', event.description,
                'location', event.location,
                'event_type', event.event_type,
                'start_at', event.start_at,
                'end_at', event.end_at,
                'timezone', event.timezone,
                'all_day', event.all_day,
                'recurrence_rule', event.recurrence_rule,
                'reminder_minutes', event.reminder_minutes,
                'status', event.status,
                'source', event.source,
                'source_response_id', event.source_response_id,
                'revision', event.revision,
                'cancelled_at', event.cancelled_at
            ),
            '["imported"]'::json,
            event.source,
            event.source_response_id,
            COALESCE(event.updated_at, event.created_at, now())
        FROM calendar_events AS event
        ON CONFLICT (event_id, revision) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("calendar_event_revisions")
    op.drop_column("calendar_events", "cancelled_at")
    op.drop_column("calendar_events", "revision")

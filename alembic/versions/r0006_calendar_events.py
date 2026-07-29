"""Add scoped personal calendar events.

Revision ID: r0006_calendar_events
Revises: r0005_user_model_settings
"""

from __future__ import annotations

from alembic import op

revision = "r0006_calendar_events"
down_revision = "r0005_user_model_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.calendar_events (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
            workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            title VARCHAR(255) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            location VARCHAR(512) NOT NULL DEFAULT '',
            event_type VARCHAR(32) NOT NULL DEFAULT 'event',
            start_at TIMESTAMP WITH TIME ZONE NOT NULL,
            end_at TIMESTAMP WITH TIME ZONE NOT NULL,
            timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
            all_day BOOLEAN NOT NULL DEFAULT FALSE,
            recurrence_rule VARCHAR(512),
            reminder_minutes JSON NOT NULL DEFAULT '[15]'::json,
            status VARCHAR(20) NOT NULL DEFAULT 'confirmed',
            source VARCHAR(20) NOT NULL DEFAULT 'manual',
            source_response_id VARCHAR(64),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_scope_time "
        "ON public.calendar_events (user_id, tenant_id, workspace_id, start_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_status_time "
        "ON public.calendar_events (status, start_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.calendar_reminder_deliveries (
            id VARCHAR(36) PRIMARY KEY,
            event_id VARCHAR(36) NOT NULL REFERENCES public.calendar_events(id) ON DELETE CASCADE,
            occurrence_start TIMESTAMP WITH TIME ZONE NOT NULL,
            reminder_minutes INTEGER NOT NULL,
            delivered_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_calendar_reminder_delivery
                UNIQUE (event_id, occurrence_start, reminder_minutes)
        )
    """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_reminder_event "
        "ON public.calendar_reminder_deliveries (event_id, occurrence_start)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.calendar_reminder_deliveries")
    op.execute("DROP TABLE IF EXISTS public.calendar_events")

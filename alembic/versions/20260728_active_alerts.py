"""Add active data alert rules and events.

Revision ID: 20260728_active_alerts
Revises: 20260727_project_knowledge_scope
"""

from __future__ import annotations

from alembic import op

revision = "20260728_active_alerts"
down_revision = "20260727_project_knowledge_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.alert_rules (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
            workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            project_id VARCHAR(36),
            data_source_id VARCHAR(36) NOT NULL,
            name VARCHAR(255) NOT NULL,
            question TEXT NOT NULL,
            metric_column VARCHAR(255),
            aggregation VARCHAR(20) NOT NULL DEFAULT 'first',
            operator VARCHAR(24) NOT NULL DEFAULT 'gt',
            threshold DOUBLE PRECISION NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'warning',
            rrule VARCHAR(512) NOT NULL,
            timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            cooldown_seconds INTEGER NOT NULL DEFAULT 3600,
            last_value DOUBLE PRECISION,
            last_state VARCHAR(20) NOT NULL DEFAULT 'unknown',
            last_error TEXT,
            last_run_at TIMESTAMP WITH TIME ZONE,
            last_triggered_at TIMESTAMP WITH TIME ZONE,
            next_run_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_rules_due ON public.alert_rules (status, next_run_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_rules_scope ON public.alert_rules (user_id, tenant_id, workspace_id, project_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.alert_events (
            id VARCHAR(36) PRIMARY KEY,
            rule_id VARCHAR(36) NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            state VARCHAR(20) NOT NULL DEFAULT 'triggered',
            severity VARCHAR(20) NOT NULL DEFAULT 'warning',
            value DOUBLE PRECISION,
            threshold DOUBLE PRECISION,
            summary TEXT NOT NULL,
            evidence JSON NOT NULL DEFAULT '{}',
            acknowledged_by VARCHAR(36),
            acknowledged_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_events_rule_created ON public.alert_events (rule_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alert_events_user_state ON public.alert_events (user_id, state)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.alert_events")
    op.execute("DROP TABLE IF EXISTS public.alert_rules")

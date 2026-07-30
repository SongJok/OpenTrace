"""memory_quality_cleanup

Revision ID: r0008_memory_quality_cleanup
Revises: r0007_enterprise_cognition
Create Date: 2026-07-30 11:20:02.970262
"""

from __future__ import annotations

from alembic import op

revision = "r0008_memory_quality_cleanup"
down_revision = "r0007_enterprise_cognition"
branch_labels = None
depends_on = None

_QUARANTINE_METADATA = (
    '{"quality_quarantined":{"reason":"legacy_assistant_transcript",' '"migrated_at":"2026-07-30"}}'
)


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE public.user_memories
        SET enabled = false,
            status = 'rejected',
            metadata_json = '{_QUARANTINE_METADATA}',
            updated_at = now()
        WHERE enabled IS TRUE
          AND status = 'active'
          AND kind = 'fact'
          AND memory_key IS NULL
          AND source_response_id IS NULL
          AND content ~* E'^\\s*Q\\s*[:：]'
          AND content ~* E'\\n\\s*A\\s*[:：]'
          AND (
              content ILIKE '%Cognitive Kernel%'
              OR content ILIKE '%认知内核%'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE public.user_memories
        SET enabled = true,
            status = 'active',
            metadata_json = NULL,
            updated_at = now()
        WHERE enabled IS FALSE
          AND status = 'rejected'
          AND metadata_json = '{_QUARANTINE_METADATA}'
        """
    )

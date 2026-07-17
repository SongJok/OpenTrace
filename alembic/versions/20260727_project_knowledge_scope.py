"""Scope documents and compiled knowledge to Projects.

Revision ID: 20260727_project_knowledge_scope
Revises: 20260726_user_memory_score
"""

from __future__ import annotations

from alembic import op

revision = "20260727_project_knowledge_scope"
down_revision = "20260726_user_memory_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("documents", "knowledge_sources", "knowledge_compilation_jobs"):
        op.execute(
            f"ALTER TABLE public.{table} ADD COLUMN IF NOT EXISTS project_id VARCHAR(36)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_project_id "
            f"ON public.{table} (project_id)"
        )


def downgrade() -> None:
    for table in ("knowledge_compilation_jobs", "knowledge_sources", "documents"):
        op.execute(f"DROP INDEX IF EXISTS public.ix_{table}_project_id")
        op.execute(f"ALTER TABLE public.{table} DROP COLUMN IF EXISTS project_id")

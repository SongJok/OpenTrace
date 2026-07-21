"""Unify chat attachments with governed knowledge asset lifecycle."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260716_chat_knowledge_assets"
down_revision = "20260715_knowledge_metadata_metacognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("attachments")}
    if "scope" not in columns:
        op.add_column("attachments", sa.Column("scope", sa.String(20), nullable=False, server_default="session"))
    if "ingest_status" not in columns:
        op.add_column("attachments", sa.Column("ingest_status", sa.String(32), nullable=False, server_default="temporary"))
    if "promoted_document_id" not in columns:
        op.add_column("attachments", sa.Column("promoted_document_id", sa.String(36), nullable=True))
    if "asset_metadata" not in columns:
        op.add_column("attachments", sa.Column("asset_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("attachments")}
    if "ix_attachments_ingest_status" not in existing_indexes:
        op.create_index("ix_attachments_ingest_status", "attachments", ["ingest_status"])
    if "ix_attachments_promoted_document_id" not in existing_indexes:
        op.create_index("ix_attachments_promoted_document_id", "attachments", ["promoted_document_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_promoted_document_id", table_name="attachments")
    op.drop_index("ix_attachments_ingest_status", table_name="attachments")
    op.drop_column("attachments", "asset_metadata")
    op.drop_column("attachments", "promoted_document_id")
    op.drop_column("attachments", "ingest_status")
    op.drop_column("attachments", "scope")

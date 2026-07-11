"""Add search indexes for governed knowledge and document evidence."""

from __future__ import annotations

from alembic import op

revision = "20260714_knowledge_search_indexes"
down_revision = "20260713_knowledge_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extensions are already available in the pgvector image, while the
    # guards keep local installations and repeated upgrades idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_pages_scope_status "
        "ON knowledge_pages (tenant_id, workspace_id, status, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_claims_scope_status "
        "ON knowledge_claims (tenant_id, workspace_id, status, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_relations_scope_status "
        "ON knowledge_relations (tenant_id, workspace_id, status, relation_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_pages_title_trgm "
        "ON knowledge_pages USING gin (title gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_claims_text_trgm "
        "ON knowledge_claims USING gin (text gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_pages_search_tsv "
        "ON knowledge_pages USING gin "
        "(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, '')))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_claims_search_tsv "
        "ON knowledge_claims USING gin "
        "(to_tsvector('simple', coalesce(text, '') || ' ' || coalesce(normalized_text, '')))"
    )

    # The column is optional on legacy databases.  If a deployment still has
    # the JSON/Text fallback, the guarded block leaves lexical retrieval intact.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'document_chunks' AND column_name = 'embedding_vector') "
        "AND EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN "
        "EXECUTE 'CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding_vector vector_cosine_ops)'; "
        "END IF; END $$"
    )


def downgrade() -> None:
    for index in (
        "ix_document_chunks_embedding_hnsw",
        "ix_knowledge_claims_search_tsv",
        "ix_knowledge_pages_search_tsv",
        "ix_knowledge_claims_text_trgm",
        "ix_knowledge_pages_title_trgm",
        "ix_knowledge_relations_scope_status",
        "ix_knowledge_claims_scope_status",
        "ix_knowledge_pages_scope_status",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")

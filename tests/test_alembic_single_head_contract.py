"""Alembic must have a single head after merge revision."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic" / "versions"


def test_alembic_migrations_are_not_gitignored():
    gitignore_lines = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "alembic/versions/*.py" not in gitignore_lines


def test_alembic_version_column_is_widened_before_long_revision_ids():
    widening = (VERSIONS / "20260416_widen_alembic_version.py").read_text(encoding="utf-8")
    first_long_revision = (VERSIONS / "20260417_document_chunks_pgvector.py").read_text(
        encoding="utf-8"
    )
    provided_schema = (ROOT / "scripts/sql/provided_schema.sql").read_text(encoding="utf-8")

    assert 'revision = "20260416_version_num_128"' in widening
    assert "type_=sa.String(length=128)" in widening
    assert 'down_revision = "20260416_version_num_128"' in first_long_revision
    assert "version_num varchar(128) NOT NULL" in provided_schema


def test_legacy_text_embeddings_are_normalized_before_vector_indexing():
    search_indexes = (VERSIONS / "20260714_knowledge_search_indexes.py").read_text(
        encoding="utf-8"
    )
    normalization = (VERSIONS / "20260725_normalize_vector_columns.py").read_text(
        encoding="utf-8"
    )

    assert "udt_name = 'vector'" in search_indexes
    assert 'down_revision = "20260724_chatgpt_runtime_completion"' in normalization
    assert "TYPE vector({VECTOR_DIMENSIONS})" in normalization
    assert "vector_dims(embedding_vector::vector)" in normalization
    assert "ix_document_chunks_embedding_hnsw" in normalization


def test_user_memory_score_is_added_after_existing_runtime_migrations():
    migration = (VERSIONS / "20260726_add_user_memory_score.py").read_text(
        encoding="utf-8"
    )
    database = (ROOT / "infra/storage/database.py").read_text(encoding="utf-8")

    assert 'down_revision = "20260725_vector_columns"' in migration
    assert "ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION" in migration
    assert '"user_memories": {' in database
    assert '"score",' in database


def test_alembic_single_head():
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip() and "(head)" in ln]
    assert len(lines) == 1, f"expected 1 head, got {lines!r}: {proc.stdout}"

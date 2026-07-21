from pathlib import Path

from infra.storage.models import DataSourceSchema

ROOT = Path(__file__).resolve().parents[1]


def test_data_source_schema_orm_columns_have_migration_coverage() -> None:
    migration_text = (ROOT / "alembic/versions/20260730_data_source_schema_embedding.py").read_text(
        encoding="utf-8"
    )
    orm_columns = set(DataSourceSchema.__table__.columns.keys())

    assert "embedding" in orm_columns
    assert "ADD COLUMN IF NOT EXISTS embedding TEXT" in migration_text

"""数据知识标注与 SQL 资产结构化元数据

Revision ID: r0018_data_knowledge
Revises: r0017_sql_asset_governance
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0018_data_knowledge"
down_revision = "r0017_sql_asset_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sql_assets",
        sa.Column(
            "knowledge_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )

    op.add_column(
        "schema_metadata",
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "schema_metadata",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "schema_metadata",
        sa.Column(
            "annotation_source", sa.String(length=32), nullable=False, server_default="inferred"
        ),
    )
    op.add_column(
        "schema_metadata",
        sa.Column("annotation_confidence", sa.Float(), nullable=False, server_default="0.5"),
    )
    op.add_column(
        "schema_metadata",
        sa.Column(
            "annotation_status", sa.String(length=20), nullable=False, server_default="suggested"
        ),
    )
    op.add_column(
        "schema_metadata",
        sa.Column(
            "suggested_changes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column(
        "schema_metadata",
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.add_column(
        "schema_metadata", sa.Column("schema_fingerprint", sa.String(length=64), nullable=True)
    )
    op.add_column("schema_metadata", sa.Column("created_by", sa.String(length=36), nullable=True))
    op.add_column("schema_metadata", sa.Column("approved_by", sa.String(length=36), nullable=True))
    op.add_column(
        "schema_metadata", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_schema_metadata_annotation_status",
        "schema_metadata",
        ["annotation_status"],
        unique=False,
    )

    op.create_table(
        "schema_table_metadata",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("business_name", sa.String(length=255), nullable=True),
        sa.Column("business_description", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column(
            "annotation_source", sa.String(length=32), nullable=False, server_default="inferred"
        ),
        sa.Column("annotation_confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column(
            "annotation_status", sa.String(length=20), nullable=False, server_default="suggested"
        ),
        sa.Column(
            "suggested_changes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("data_source_id", "table_name", name="uq_schema_table_meta_ds_table"),
    )
    op.create_index(
        "ix_schema_table_metadata_data_source_id",
        "schema_table_metadata",
        ["data_source_id"],
        unique=False,
    )
    op.create_index(
        "ix_schema_table_metadata_annotation_status",
        "schema_table_metadata",
        ["annotation_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_schema_table_metadata_annotation_status", table_name="schema_table_metadata")
    op.drop_index("ix_schema_table_metadata_data_source_id", table_name="schema_table_metadata")
    op.drop_table("schema_table_metadata")

    op.drop_index("ix_schema_metadata_annotation_status", table_name="schema_metadata")
    for column in (
        "approved_at",
        "approved_by",
        "created_by",
        "schema_fingerprint",
        "source_refs",
        "suggested_changes",
        "annotation_status",
        "annotation_confidence",
        "annotation_source",
        "tags",
        "aliases",
    ):
        op.drop_column("schema_metadata", column)
    op.drop_column("sql_assets", "knowledge_metadata")

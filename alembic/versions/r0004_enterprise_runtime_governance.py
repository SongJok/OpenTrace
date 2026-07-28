"""Enterprise runtime governance: RLS, object storage metadata and deletion controls."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0004_enterprise_runtime_governance"
down_revision = "r0003_enterprise_directory_and_operations"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table)}


def _add_user_token_version(inspector: sa.Inspector) -> None:
    columns = _column_names(inspector, "users")
    if "users" in inspector.get_table_names() and "token_version" not in columns:
        op.add_column(
            "users",
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
        )


def _add_attachment_columns(inspector: sa.Inspector) -> None:
    columns = _column_names(inspector, "attachments")
    additions = {
        "tenant_id": sa.Column(
            "tenant_id", sa.String(128), nullable=False, server_default="default"
        ),
        "workspace_id": sa.Column(
            "workspace_id", sa.String(128), nullable=False, server_default="default"
        ),
        "storage_backend": sa.Column(
            "storage_backend", sa.String(20), nullable=False, server_default="database"
        ),
        "object_key": sa.Column("object_key", sa.String(1024), nullable=True),
        "object_etag": sa.Column("object_etag", sa.String(128), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("attachments", column)
    if "attachments" in inspector.get_table_names():
        op.execute(
            """
            UPDATE attachments a
               SET tenant_id = s.tenant_id,
                   workspace_id = s.workspace_id
              FROM chat_sessions s
             WHERE a.session_id = s.id
               AND (a.tenant_id = 'default' OR a.workspace_id = 'default')
            """
            if inspector.bind.dialect.name == "postgresql"
            else "UPDATE attachments SET tenant_id='default', workspace_id='default'"
        )
        indexes = {index["name"] for index in inspector.get_indexes("attachments")}
        for name, columns_ in (
            ("ix_attachments_tenant_id", ["tenant_id"]),
            ("ix_attachments_workspace_id", ["workspace_id"]),
            ("uq_attachments_object_key", ["object_key"]),
        ):
            if name not in indexes:
                op.create_index(name, "attachments", columns_, unique=name.startswith("uq_"))


def _create_governance_tables(inspector: sa.Inspector) -> None:
    tables = set(inspector.get_table_names())
    if "legal_holds" not in tables:
        op.create_table(
            "legal_holds",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", sa.String(128)),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("released_by", sa.String(36)),
            sa.Column("released_at", sa.DateTime(timezone=True)),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        for column in (
            "tenant_id",
            "workspace_id",
            "resource_type",
            "resource_id",
            "status",
            "created_by",
        ):
            op.create_index(f"ix_legal_holds_{column}", "legal_holds", [column])
    if "data_deletion_jobs" not in tables:
        op.create_table(
            "data_deletion_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("workspace_id", sa.String(128)),
            sa.Column("requested_by", sa.String(36), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("phase", sa.String(32), nullable=False, server_default="grace_period"),
            sa.Column("progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("error", sa.Text()),
            sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        for column in ("tenant_id", "workspace_id", "requested_by", "status"):
            op.create_index(f"ix_data_deletion_jobs_{column}", "data_deletion_jobs", [column])
    if "revoked_tokens" not in tables:
        op.create_table(
            "revoked_tokens",
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("reason", sa.String(128), nullable=False, server_default="logout"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])
        op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])


def _enable_postgres_rls(inspector: sa.Inspector) -> None:
    if inspector.bind.dialect.name != "postgresql":
        return
    direct_tables = (
        "responses",
        "chat_sessions",
        "attachments",
        "documents",
        "data_sources",
        "projects",
        "assistant_profiles",
        "user_memories",
        "memory_candidates",
        "knowledge_spaces",
        "knowledge_documents",
        "legal_holds",
        "data_deletion_jobs",
    )
    existing = set(inspector.get_table_names())
    for table in direct_tables:
        columns = _column_names(inspector, table)
        if table not in existing or "tenant_id" not in columns:
            continue
        workspace_check = ""
        if "workspace_id" in columns:
            workspace_check = " AND workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')"
        policy = f"{table}_scope_isolation"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')
        op.execute(
            f"""CREATE POLICY "{policy}" ON "{table}"
                USING (
                    current_setting('app.service_role', true) = 'worker'
                    OR (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                        {workspace_check})
                )
                WITH CHECK (
                    current_setting('app.service_role', true) = 'worker'
                    OR (tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                        {workspace_check})
                )"""
        )
    child_tables = (
        "response_items",
        "response_events",
        "response_model_calls",
        "response_tool_executions",
        "response_approvals",
    )
    for table in child_tables:
        if table not in existing:
            continue
        policy = f"{table}_response_scope_isolation"
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS "{policy}" ON "{table}"')
        op.execute(
            f"""CREATE POLICY "{policy}" ON "{table}"
                USING (
                    current_setting('app.service_role', true) = 'worker'
                    OR EXISTS (
                        SELECT 1 FROM responses r
                         WHERE r.id = "{table}".response_id
                           AND r.tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                           AND r.workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')
                    )
                )"""
        )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _add_user_token_version(inspector)
    inspector = sa.inspect(op.get_bind())
    _add_attachment_columns(inspector)
    inspector = sa.inspect(op.get_bind())
    _create_governance_tables(inspector)
    inspector = sa.inspect(op.get_bind())
    _enable_postgres_rls(inspector)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.bind.dialect.name == "postgresql":
        direct_tables = (
            "responses",
            "chat_sessions",
            "attachments",
            "documents",
            "data_sources",
            "projects",
            "assistant_profiles",
            "user_memories",
            "memory_candidates",
            "knowledge_spaces",
            "knowledge_documents",
            "legal_holds",
            "data_deletion_jobs",
        )
        child_tables = (
            "response_items",
            "response_events",
            "response_model_calls",
            "response_tool_executions",
            "response_approvals",
        )
        existing = set(inspector.get_table_names())
        for table in direct_tables:
            if table in existing:
                op.execute(f'DROP POLICY IF EXISTS "{table}_scope_isolation" ON "{table}"')
                op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
        for table in child_tables:
            if table in existing:
                op.execute(f'DROP POLICY IF EXISTS "{table}_response_scope_isolation" ON "{table}"')
                op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    for table in ("revoked_tokens", "data_deletion_jobs", "legal_holds"):
        if table in inspector.get_table_names():
            op.drop_table(table)
    user_columns = _column_names(inspector, "users")
    if "token_version" in user_columns:
        op.drop_column("users", "token_version")
    columns = _column_names(inspector, "attachments")
    for column in ("object_etag", "object_key", "storage_backend", "workspace_id", "tenant_id"):
        if column in columns:
            op.drop_column("attachments", column)

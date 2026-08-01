"""跨 API、Agent 与后台任务复用的租户和资源授权谓词。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, and_, exists, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.models import ChatSession, DataSource, Document, ResourcePermission, User

PERMISSION_RANK = {"view": 1, "query": 2, "edit": 3, "admin": 4}


def normalized_tenant_scope(metadata: dict[str, Any] | None) -> tuple[str, str]:
    md = metadata or {}
    tenant_id = str(md.get("tenant_id") or "default").strip() or "default"
    workspace_id = str(md.get("workspace_id") or "default").strip() or "default"
    return tenant_id, workspace_id


def scoped_documents_statement(
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None,
    document_id: str | None = None,
    project_id: str | None = None,
) -> Select:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    stmt = select(Document).where(
        Document.owner_id == user_id,
        Document.tenant_id == tenant_id,
        Document.workspace_id == workspace_id,
    )
    if document_id:
        stmt = stmt.where(Document.id == document_id)
    if project_id:
        stmt = stmt.where(Document.project_id == project_id)
    return stmt


def accessible_document_predicate(
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
):
    """构造文档问答只读范围；管理员可读当前工作区全部文档，普通用户仅可读本人文档。"""

    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id or normalized_user_id == "shared":
        return false()
    requester_is_admin = exists(
        select(User.id).where(
            User.id == normalized_user_id,
            User.status == "active",
            or_(User.role == "admin", User.is_superuser.is_(True)),
        )
    )
    return and_(
        Document.tenant_id == tenant_id,
        Document.workspace_id == workspace_id,
        or_(Document.owner_id == normalized_user_id, requester_is_admin),
    )


async def load_scoped_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> ChatSession | None:
    """按完整执行主体加载会话；不存在和越权统一返回空，避免泄露会话存在性。"""

    return await db.scalar(
        select(ChatSession).where(
            ChatSession.id == conversation_id,
            ChatSession.user_id == user_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.workspace_id == workspace_id,
        )
    )


async def require_response_conversation(db: AsyncSession, *, response: Any) -> ChatSession:
    """为 Worker/Agent Loop 加载 Response 对应会话，作用域失配时立即拒绝。"""

    session = await load_scoped_conversation(
        db,
        conversation_id=response.conversation_id,
        user_id=response.user_id,
        tenant_id=response.tenant_id,
        workspace_id=response.workspace_id,
    )
    if session is None:
        raise PermissionError("conversation_scope_mismatch")
    return session


def owned_data_sources_statement(
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
    data_source_id: str | None = None,
    active_only: bool = False,
) -> Select:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    stmt = select(DataSource).where(
        DataSource.user_id == user_id,
        DataSource.tenant_id == tenant_id,
        DataSource.workspace_id == workspace_id,
    )
    if data_source_id:
        stmt = stmt.where(DataSource.id == data_source_id)
    if active_only:
        stmt = stmt.where(DataSource.status == "active")
    return stmt


def accessible_data_sources_statement(
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
    data_source_id: str | None = None,
    required_permission: str = "view",
    active_only: bool = False,
) -> Select:
    tenant_id, workspace_id = normalized_tenant_scope(tenant_metadata)
    minimum_rank = PERMISSION_RANK.get(required_permission)
    if minimum_rank is None:
        raise ValueError(f"unsupported permission: {required_permission}")
    allowed = [name for name, rank in PERMISSION_RANK.items() if rank >= minimum_rank]
    permission_exists = exists(
        select(ResourcePermission.id).where(
            ResourcePermission.subject_user_id == user_id,
            ResourcePermission.tenant_id == tenant_id,
            ResourcePermission.workspace_id == workspace_id,
            ResourcePermission.resource_type == "data_source",
            ResourcePermission.resource_id == DataSource.id,
            ResourcePermission.permission.in_(allowed),
            or_(
                ResourcePermission.expires_at.is_(None),
                ResourcePermission.expires_at > datetime.now(UTC),
            ),
        )
    )
    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.workspace_id == workspace_id,
        or_(DataSource.user_id == user_id, permission_exists),
    )
    if data_source_id:
        stmt = stmt.where(DataSource.id == data_source_id)
    if active_only:
        stmt = stmt.where(DataSource.status == "active")
    return stmt


async def get_owned_data_source(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
    data_source_id: str,
) -> DataSource | None:
    result = await db.execute(
        owned_data_sources_statement(
            user_id=user_id,
            tenant_metadata=tenant_metadata,
            data_source_id=data_source_id,
        )
    )
    return result.scalar_one_or_none()


async def get_accessible_data_source(
    db: AsyncSession,
    *,
    user_id: str,
    tenant_metadata: dict[str, Any] | None = None,
    data_source_id: str,
    required_permission: str = "view",
    active_only: bool = False,
) -> DataSource | None:
    result = await db.execute(
        accessible_data_sources_statement(
            user_id=user_id,
            tenant_metadata=tenant_metadata,
            data_source_id=data_source_id,
            required_permission=required_permission,
            active_only=active_only,
        )
    )
    return result.scalar_one_or_none()

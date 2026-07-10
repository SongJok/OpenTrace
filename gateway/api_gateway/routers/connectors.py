from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from connectors import register_builtin_connectors
from connectors.registry import connector_registry
from connectors.security import (
    ConnectorOAuthError,
    issue_connector_oauth_state,
    verify_connector_oauth_state,
)
from connectors.sdk.protocol import CredentialRef
from gateway.api_gateway.routers.auth import get_current_user
from gateway.api_gateway.resource_scope import normalized_tenant_scope
from gateway.api_gateway.tenant_middleware import build_tenant_metadata
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.security.connector_credentials import (
    decrypt_connector_credential,
    encrypt_connector_credential,
)
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import ConnectorCredential, User

router = APIRouter()


class ConnectorAuthorizeRequest(BaseModel):
    provider: str
    redirect_uri: str
    state: str = Field(default="state")


class ConnectorCallbackRequest(BaseModel):
    provider: str
    code: str
    redirect_uri: str
    state: str


class ConnectorResourceQuery(BaseModel):
    provider: str
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


async def _get_user_credential(
    db: AsyncSession,
    request: Request,
    current_user: User,
    provider: str,
) -> CredentialRef:
    tenant_md = build_tenant_metadata(request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(tenant_md)
    result = await db.execute(
        select(ConnectorCredential).where(
            ConnectorCredential.user_id == current_user.id,
            ConnectorCredential.tenant_id == tenant_id,
            ConnectorCredential.workspace_id == workspace_id,
            ConnectorCredential.provider == provider,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"connector '{provider}' not authorized")
    try:
        return decrypt_connector_credential(row.credential_encrypted)
    except Exception as exc:
        raise AppException(
            ErrorCodes.AUTH_INTERNAL_ERROR.code,
            message="connector credential is unavailable",
        ) from exc


@router.get("/connectors")
async def list_connectors(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    register_builtin_connectors()
    return {"items": connector_registry.list(), "user_id": current_user.id}


@router.post("/connectors/authorize")
async def get_authorize_url(
    http_request: Request,
    req: ConnectorAuthorizeRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    tenant_md = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(tenant_md)
    try:
        signed_state = issue_connector_oauth_state(
            user_id=current_user.id,
            provider=req.provider,
            redirect_uri=req.redirect_uri,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            client_state=req.state,
        )
    except ConnectorOAuthError as exc:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=str(exc)) from exc
    url = await connector.authorize_url(
        user_id=current_user.id,
        redirect_uri=req.redirect_uri,
        state=signed_state,
    )
    await write_audit_log(
        user_id=current_user.id,
        action="connector.authorize_url",
        resource_type="connector",
        resource_id=req.provider,
        payload={"redirect_uri": req.redirect_uri},
    )
    return {"provider": req.provider, "authorize_url": url}


@router.post("/connectors/callback")
async def connector_callback(
    http_request: Request,
    req: ConnectorCallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    tenant_md = build_tenant_metadata(http_request, user_id=current_user.id)
    tenant_id, workspace_id = normalized_tenant_scope(tenant_md)
    try:
        verify_connector_oauth_state(
            req.state,
            user_id=current_user.id,
            provider=req.provider,
            redirect_uri=req.redirect_uri,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
    except ConnectorOAuthError as exc:
        raise AppException(ErrorCodes.PERMISSION_DENIED.code, message=str(exc)) from exc
    credential = await connector.exchange_code(user_id=current_user.id, code=req.code, redirect_uri=req.redirect_uri)
    result = await db.execute(
        select(ConnectorCredential).where(
            ConnectorCredential.user_id == current_user.id,
            ConnectorCredential.tenant_id == tenant_id,
            ConnectorCredential.workspace_id == workspace_id,
            ConnectorCredential.provider == req.provider,
        )
    )
    row = result.scalar_one_or_none()
    encrypted = encrypt_connector_credential(credential)
    if row is None:
        row = ConnectorCredential(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            provider=req.provider,
            account_id=credential.account_id,
            credential_encrypted=encrypted,
            expires_at=credential.expires_at,
        )
        db.add(row)
    else:
        row.account_id = credential.account_id
        row.credential_encrypted = encrypted
        row.expires_at = credential.expires_at
    await db.commit()
    await write_audit_log(
        user_id=current_user.id,
        action="connector.callback",
        resource_type="connector",
        resource_id=req.provider,
        payload={"account_id": credential.account_id},
    )
    return {
        "provider": req.provider,
        "authorized": True,
        "account_id": credential.account_id,
    }


@router.post("/connectors/resources")
async def list_connector_resources(
    http_request: Request,
    req: ConnectorResourceQuery,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    cred = await _get_user_credential(db, http_request, current_user, req.provider)
    items = await connector.list_resources(cred, cursor=req.cursor, limit=req.limit)
    return {"provider": req.provider, "items": [item.__dict__ for item in items]}


@router.post("/connectors/sync")
async def sync_connector(
    http_request: Request,
    req: ConnectorResourceQuery,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    cred = await _get_user_credential(db, http_request, current_user, req.provider)
    result = await connector.sync(cred, cursor=req.cursor, limit=req.limit)
    await write_audit_log(
        user_id=current_user.id,
        action="connector.sync",
        resource_type="connector",
        resource_id=req.provider,
        payload={"limit": req.limit, "cursor": req.cursor},
    )
    return {
        "provider": req.provider,
        "items": [item.__dict__ for item in result.items],
        "next_cursor": result.next_cursor,
        "has_more": result.has_more,
    }

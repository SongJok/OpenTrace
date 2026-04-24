from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from connectors import register_builtin_connectors
from connectors.registry import connector_registry
from connectors.sdk.protocol import CredentialRef
from gateway.api_gateway.routers.auth import get_current_user
from infra.audit.logger import write_audit_log
from infra.errors import AppException, ErrorCodes
from infra.storage.models import User

router = APIRouter()

# P5 Step1: in-memory credential store (replace with DB/KMS in step2)
_CREDENTIALS: dict[str, dict[str, CredentialRef]] = {}


class ConnectorAuthorizeRequest(BaseModel):
    provider: str
    redirect_uri: str
    state: str = Field(default="state")


class ConnectorCallbackRequest(BaseModel):
    provider: str
    code: str
    redirect_uri: str


class ConnectorResourceQuery(BaseModel):
    provider: str
    cursor: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


def _get_user_credential(user_id: str, provider: str) -> CredentialRef:
    by_user = _CREDENTIALS.get(user_id, {})
    cred = by_user.get(provider)
    if cred is None:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message=f"connector '{provider}' not authorized")
    return cred


@router.get("/connectors")
async def list_connectors(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    register_builtin_connectors()
    return {"items": connector_registry.list(), "user_id": current_user.id}


@router.post("/connectors/authorize")
async def get_authorize_url(req: ConnectorAuthorizeRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    url = await connector.authorize_url(user_id=current_user.id, redirect_uri=req.redirect_uri, state=req.state)
    await write_audit_log(
        user_id=current_user.id,
        action="connector.authorize_url",
        resource_type="connector",
        resource_id=req.provider,
        payload={"redirect_uri": req.redirect_uri},
    )
    return {"provider": req.provider, "authorize_url": url}


@router.post("/connectors/callback")
async def connector_callback(req: ConnectorCallbackRequest, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    credential = await connector.exchange_code(user_id=current_user.id, code=req.code, redirect_uri=req.redirect_uri)
    _CREDENTIALS.setdefault(current_user.id, {})[req.provider] = credential
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
async def list_connector_resources(req: ConnectorResourceQuery, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    cred = _get_user_credential(current_user.id, req.provider)
    items = await connector.list_resources(cred, cursor=req.cursor, limit=req.limit)
    return {"provider": req.provider, "items": [item.__dict__ for item in items]}


@router.post("/connectors/sync")
async def sync_connector(req: ConnectorResourceQuery, current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    register_builtin_connectors()
    connector = connector_registry.get(req.provider)
    cred = _get_user_credential(current_user.id, req.provider)
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

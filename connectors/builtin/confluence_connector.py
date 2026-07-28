from __future__ import annotations

import base64
import urllib.parse

import httpx

from connectors.sdk.protocol import ConnectorResource, CredentialRef, SyncResult


class ConfluenceConnector:
    name = "confluence"

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    async def authorize_url(self, user_id: str, redirect_uri: str, state: str) -> str:
        del user_id
        query = urllib.parse.urlencode(
            {
                "audience": "api.atlassian.com",
                "client_id": self.client_id,
                "scope": "read:confluence-content.all read:confluence-space.summary offline_access",
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "prompt": "consent",
            }
        )
        return f"https://auth.atlassian.com/authorize?{query}"

    async def exchange_code(self, user_id: str, code: str, redirect_uri: str) -> CredentialRef:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                "https://auth.atlassian.com/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
        response.raise_for_status()
        payload = response.json()
        return CredentialRef(
            provider=self.name,
            account_id=user_id,
            access_token=str(payload["access_token"]),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_at=int(payload.get("expires_in") or 0),
        )

    async def refresh_token(self, credential: CredentialRef) -> CredentialRef:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                "https://auth.atlassian.com/oauth/token",
                json={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": credential.refresh_token,
                },
            )
        response.raise_for_status()
        payload = response.json()
        credential.access_token = str(payload["access_token"])
        credential.refresh_token = str(payload.get("refresh_token") or credential.refresh_token)
        return credential

    async def _cloud_id(self, credential: CredentialRef) -> str:
        cached = str(credential.metadata.get("cloud_id") or "")
        if cached:
            return cached
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"authorization": f"Bearer {credential.access_token}"},
            )
        response.raise_for_status()
        resources = response.json()
        if not resources:
            raise RuntimeError("Confluence 无可访问站点")
        cloud_id = str(resources[0]["id"])
        credential.metadata["cloud_id"] = cloud_id
        return cloud_id

    async def list_resources(
        self, credential: CredentialRef, cursor: str | None = None, limit: int = 20
    ) -> list[ConnectorResource]:
        cloud_id = await self._cloud_id(credential)
        url = f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/api/v2/pages"
        params = {"limit": min(limit, 100)}
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(
                url, headers={"authorization": f"Bearer {credential.access_token}"}, params=params
            )
        response.raise_for_status()
        return [
            ConnectorResource(
                id=f"page:{item['id']}",
                type="page",
                title=str(item.get("title") or item["id"]),
                metadata={"provider": self.name, "space_id": item.get("spaceId")},
                acl=[f"confluence:space:{item.get('spaceId')}"],
                version=str(item.get("version", {}).get("number", "")),
            )
            for item in response.json().get("results") or []
        ]

    async def fetch_resource(
        self, credential: CredentialRef, resource_id: str
    ) -> ConnectorResource:
        cloud_id = await self._cloud_id(credential)
        page_id = resource_id.split(":", 1)[-1]
        url = f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/api/v2/pages/{page_id}"
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(
                url,
                headers={"authorization": f"Bearer {credential.access_token}"},
                params={"body-format": "storage"},
            )
        response.raise_for_status()
        item = response.json()
        body = str(dict(item.get("body") or {}).get("storage", {}).get("value") or "")
        return ConnectorResource(
            id=f"page:{page_id}",
            type="page",
            title=str(item.get("title") or page_id),
            content=body,
            metadata={
                "provider": self.name,
                "content_sha256": base64.b16encode(
                    __import__("hashlib").sha256(body.encode()).digest()
                )
                .decode()
                .lower(),
            },
        )

    async def sync(
        self, credential: CredentialRef, cursor: str | None = None, limit: int = 20
    ) -> SyncResult:
        items = await self.list_resources(credential, cursor=cursor, limit=limit)
        return SyncResult(items=items, observed_count=len(items), checkpoint={"cursor": cursor})

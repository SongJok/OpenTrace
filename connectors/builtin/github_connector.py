from __future__ import annotations

import urllib.parse
from dataclasses import asdict

import httpx

from connectors.sdk.protocol import ConnectorResource, CredentialRef, SyncResult


class GitHubConnector:
    name = "github"

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    async def authorize_url(self, user_id: str, redirect_uri: str, state: str) -> str:
        del user_id
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id or "github-client-id",
                "redirect_uri": redirect_uri,
                "scope": "repo read:user",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def exchange_code(self, user_id: str, code: str, redirect_uri: str) -> CredentialRef:
        if not self.client_id or not self.client_secret:
            return CredentialRef(
                provider=self.name,
                account_id=user_id,
                access_token=f"gho_mock_{code}",
                metadata={"redirect_uri": redirect_uri, "development_mock": True},
            )
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"accept": "application/json"},
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error") or not payload.get("access_token"):
            raise RuntimeError("GitHub OAuth 交换失败")
        return CredentialRef(
            provider=self.name,
            account_id=user_id,
            access_token=str(payload["access_token"]),
            metadata={"scope": payload.get("scope", "")},
        )

    async def refresh_token(self, credential: CredentialRef) -> CredentialRef:
        return credential

    def _is_mock(self, credential: CredentialRef) -> bool:
        return (
            not self.client_id
            or not self.client_secret
            or credential.access_token.startswith("gho_mock_")
        )

    @staticmethod
    def _headers(credential: CredentialRef) -> dict[str, str]:
        return {
            "authorization": f"Bearer {credential.access_token}",
            "accept": "application/vnd.github+json",
            "x-github-api-version": "2022-11-28",
        }

    async def list_resources(
        self,
        credential: CredentialRef,
        cursor: str | None = None,
        limit: int = 20,
    ) -> list[ConnectorResource]:
        if self._is_mock(credential):
            return [
                ConnectorResource(
                    id="repo:opentrace",
                    type="repository",
                    title="opentrace",
                    content="mock repo resource",
                    metadata={
                        "provider": self.name,
                        "cursor": cursor,
                        "limit": limit,
                        "account_id": credential.account_id,
                    },
                    acl=["github:repo:opentrace"],
                )
            ]
        page = max(1, int(cursor or 1))
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(
                "https://api.github.com/user/repos",
                headers=self._headers(credential),
                params={
                    "visibility": "all",
                    "affiliation": "owner,collaborator,organization_member",
                    "sort": "updated",
                    "per_page": min(limit, 100),
                    "page": page,
                },
            )
        response.raise_for_status()
        return [
            ConnectorResource(
                id=f"repo:{item['full_name']}",
                type="repository",
                title=str(item["full_name"]),
                metadata={
                    "provider": self.name,
                    "private": bool(item.get("private")),
                    "default_branch": item.get("default_branch"),
                    "html_url": item.get("html_url"),
                },
                acl=[f"github:repo:{item['full_name']}"],
                version=str(item.get("updated_at") or ""),
            )
            for item in response.json()
        ]

    async def fetch_resource(
        self, credential: CredentialRef, resource_id: str
    ) -> ConnectorResource:
        if self._is_mock(credential):
            return ConnectorResource(
                id=resource_id,
                type="repository",
                title=resource_id,
                content="mock resource content",
                metadata={"provider": self.name, "account_id": credential.account_id},
            )
        full_name = resource_id.removeprefix("repo:")
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            repo_response = await client.get(
                f"https://api.github.com/repos/{full_name}", headers=self._headers(credential)
            )
            readme_response = await client.get(
                f"https://api.github.com/repos/{full_name}/readme",
                headers={**self._headers(credential), "accept": "application/vnd.github.raw+json"},
            )
        repo_response.raise_for_status()
        content = readme_response.text if readme_response.is_success else ""
        item = repo_response.json()
        return ConnectorResource(
            id=f"repo:{full_name}",
            type="repository",
            title=full_name,
            content=content,
            metadata={"provider": self.name, "default_branch": item.get("default_branch")},
            acl=[f"github:repo:{full_name}"],
            version=str(item.get("updated_at") or ""),
        )

    async def sync(
        self,
        credential: CredentialRef,
        cursor: str | None = None,
        limit: int = 20,
    ) -> SyncResult:
        items = await self.list_resources(credential, cursor=cursor, limit=limit)
        page = max(1, int(cursor or 1))
        has_more = len(items) >= min(limit, 100) and not credential.access_token.startswith(
            "gho_mock_"
        )
        next_cursor = str(page + 1) if has_more else None
        return SyncResult(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            observed_count=len(items),
            checkpoint={"page": page},
        )

    def to_public_dict(self) -> dict:
        return {"name": self.name, "client_id_configured": bool(self.client_id)}

    @staticmethod
    def credential_to_dict(credential: CredentialRef) -> dict:
        return asdict(credential)

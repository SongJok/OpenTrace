from __future__ import annotations

import urllib.parse

import httpx

from connectors.sdk.protocol import ConnectorResource, CredentialRef, SyncResult


class SlackConnector:
    name = "slack"

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    async def authorize_url(self, user_id: str, redirect_uri: str, state: str) -> str:
        del user_id
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": "channels:history,channels:read,groups:history,groups:read",
                "state": state,
            }
        )
        return f"https://slack.com/oauth/v2/authorize?{query}"

    async def exchange_code(self, user_id: str, code: str, redirect_uri: str) -> CredentialRef:
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
        payload = response.json()
        if not response.is_success or not payload.get("ok"):
            raise RuntimeError("Slack OAuth 交换失败")
        team = dict(payload.get("team") or {})
        return CredentialRef(
            provider=self.name,
            account_id=str(team.get("id") or user_id),
            access_token=str(payload["access_token"]),
            metadata={"team_name": team.get("name", "")},
        )

    async def refresh_token(self, credential: CredentialRef) -> CredentialRef:
        return credential

    async def list_resources(
        self, credential: CredentialRef, cursor: str | None = None, limit: int = 20
    ) -> list[ConnectorResource]:
        headers = {"authorization": f"Bearer {credential.access_token}"}
        params = {"limit": min(limit, 200), "cursor": cursor or "", "exclude_archived": "true"}
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(
                "https://slack.com/api/conversations.list", headers=headers, params=params
            )
        payload = response.json()
        if not response.is_success or not payload.get("ok"):
            raise RuntimeError("Slack 资源读取失败")
        return [
            ConnectorResource(
                id=f"channel:{channel['id']}",
                type="channel",
                title=str(channel.get("name") or channel["id"]),
                metadata={"provider": self.name, "is_private": bool(channel.get("is_private"))},
                acl=[f"slack:channel:{channel['id']}"],
                version=str(channel.get("updated") or ""),
            )
            for channel in payload.get("channels") or []
        ]

    async def fetch_resource(
        self, credential: CredentialRef, resource_id: str
    ) -> ConnectorResource:
        channel = resource_id.split(":", 1)[-1]
        headers = {"authorization": f"Bearer {credential.access_token}"}
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            response = await client.get(
                "https://slack.com/api/conversations.history",
                headers=headers,
                params={"channel": channel, "limit": 100},
            )
        payload = response.json()
        if not response.is_success or not payload.get("ok"):
            raise RuntimeError("Slack 内容读取失败")
        content = "\n".join(str(item.get("text") or "") for item in payload.get("messages") or [])
        return ConnectorResource(
            id=f"channel:{channel}",
            type="channel",
            title=channel,
            content=content,
            acl=[f"slack:channel:{channel}"],
            metadata={"provider": self.name},
        )

    async def sync(
        self, credential: CredentialRef, cursor: str | None = None, limit: int = 20
    ) -> SyncResult:
        items = await self.list_resources(credential, cursor=cursor, limit=limit)
        return SyncResult(items=items, observed_count=len(items), checkpoint={"cursor": cursor})

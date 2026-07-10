from __future__ import annotations

import json
import socket

import httpx
import pytest

from infra.security.outbound_url import (
    OutboundURLValidationError,
    fetch_public_webpage,
    validate_outbound_url,
)


def _public_dns(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://user:password@example.com/",
        "https://example.com:8443/internal",
    ],
)
async def test_outbound_policy_rejects_unsafe_urls(url):
    with pytest.raises(OutboundURLValidationError):
        await validate_outbound_url(url, allowed_domains=["example.com"])


@pytest.mark.asyncio
async def test_outbound_policy_rejects_dns_that_resolves_private(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))
        ],
    )
    with pytest.raises(OutboundURLValidationError, match="private or reserved"):
        await validate_outbound_url(
            "https://example.com/private",
            allowed_domains=["example.com"],
        )


@pytest.mark.asyncio
async def test_outbound_policy_requires_configured_domain(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    with pytest.raises(OutboundURLValidationError, match="allowlist"):
        await validate_outbound_url(
            "https://untrusted.example.net/",
            allowed_domains=["example.com"],
        )


@pytest.mark.asyncio
async def test_web_fetch_extracts_visible_text_with_limits(monkeypatch):
    from infra.config.settings import settings

    monkeypatch.setattr(settings, "web_fetch_enabled", True)
    monkeypatch.setattr(settings, "web_fetch_allowed_domains", "example.com")
    monkeypatch.setattr(settings, "web_fetch_max_response_bytes", 10_000)
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>Example Page</title>"
                "<script>secret()</script></head>"
                "<body><h1>Public heading</h1><p>Useful content.</p></body></html>"
            ),
            request=request,
        )

    page = await fetch_public_webpage(
        "https://example.com/article",
        transport=httpx.MockTransport(handler),
    )
    assert page["title"] == "Example Page"
    assert "Public heading" in page["content"]
    assert "secret()" not in page["content"]
    assert page["truncated"] is False


@pytest.mark.asyncio
async def test_web_fetch_revalidates_redirect_targets(monkeypatch):
    from infra.config.settings import settings

    monkeypatch.setattr(settings, "web_fetch_enabled", True)
    monkeypatch.setattr(settings, "web_fetch_allowed_domains", "example.com")
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/admin"},
            request=request,
        )

    with pytest.raises(OutboundURLValidationError):
        await fetch_public_webpage(
            "https://example.com/redirect",
            transport=httpx.MockTransport(handler),
        )


def test_web_agent_consumes_structured_search_results():
    from agents.web_agent import WebAgent

    content, metadata = WebAgent()._normalize(
        json.dumps(
            {
                "items": [
                    {
                        "title": "Current news",
                        "snippet": "Verified summary",
                        "url": "https://example.com/news",
                    }
                ]
            }
        )
    )
    assert "Current news" in content
    assert metadata["items"][0]["url"] == "https://example.com/news"


def test_managed_web_fetch_requires_allowlist():
    from infra.config.settings import Settings

    with pytest.raises(ValueError, match="WEB_FETCH_ALLOWED_DOMAINS"):
        Settings(
            app_env="production",
            app_port=14100,
            gateway_port=14100,
            app_secret_key="app-secret",
            jwt_secret="jwt-secret",
            data_secret_key="data-secret",
            web_fetch_enabled=True,
            web_fetch_allowed_domains="",
        )

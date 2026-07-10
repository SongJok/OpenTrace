"""Outbound URL validation and bounded webpage retrieval."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from infra.config.settings import settings


class OutboundURLValidationError(ValueError):
    pass


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())


def _domain_allowed(hostname: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in allowed_domains
    )


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


async def validate_outbound_url(
    url: str,
    *,
    allowed_domains: list[str] | None = None,
) -> str:
    candidate = str(url or "").strip()
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise OutboundURLValidationError("only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise OutboundURLValidationError("URL credentials are not allowed")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or hostname in {"localhost", "localhost.localdomain"}:
        raise OutboundURLValidationError("URL hostname is not allowed")
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise OutboundURLValidationError("invalid URL hostname") from exc
    if not _domain_allowed(hostname, allowed_domains or settings.web_fetch_domain_list):
        raise OutboundURLValidationError("URL hostname is not in the configured allowlist")

    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise OutboundURLValidationError("invalid URL port") from exc
    if port not in {80, 443}:
        raise OutboundURLValidationError("only ports 80 and 443 are allowed")

    try:
        literal = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise OutboundURLValidationError("private or reserved IP addresses are not allowed")
        return candidate

    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise OutboundURLValidationError("URL hostname could not be resolved") from exc
    addresses = {str(record[4][0]) for record in records if record and record[4]}
    if not addresses or not all(_is_public_address(address) for address in addresses):
        raise OutboundURLValidationError("hostname resolves to a private or reserved address")
    return candidate


def _extract_text(content: str, content_type: str) -> tuple[str, str]:
    if "html" not in content_type:
        return "", content.strip()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, flags=re.I | re.S)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    parser = _VisibleTextParser()
    parser.feed(content)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return title, text


async def fetch_public_webpage(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not settings.web_fetch_enabled:
        raise OutboundURLValidationError("web fetch is disabled by policy")

    current_url = url
    max_redirects = max(0, int(settings.web_fetch_max_redirects))
    max_bytes = max(1024, int(settings.web_fetch_max_response_bytes))
    timeout = max(0.5, float(settings.web_fetch_timeout_seconds))
    async with httpx.AsyncClient(
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
        transport=transport,
        headers={"User-Agent": "OpenTrace-WebFetch/1.0"},
    ) as client:
        for redirect_count in range(max_redirects + 1):
            await validate_outbound_url(current_url)
            async with client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location", "").strip()
                    if not location or redirect_count >= max_redirects:
                        raise OutboundURLValidationError("web fetch redirect limit exceeded")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(
                    allowed in content_type
                    for allowed in ("text/html", "text/plain", "application/json")
                ):
                    raise OutboundURLValidationError("unsupported webpage content type")

                chunks: list[bytes] = []
                total = 0
                truncated = False
                async for chunk in response.aiter_bytes():
                    remaining = max_bytes - total
                    if remaining <= 0:
                        truncated = True
                        break
                    chunks.append(chunk[:remaining])
                    total += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        truncated = True
                        break
                encoding = response.encoding or "utf-8"
                raw_text = b"".join(chunks).decode(encoding, errors="replace")
                title, visible_text = _extract_text(raw_text, content_type)
                return {
                    "url": str(response.url),
                    "title": title,
                    "content": visible_text,
                    "content_type": content_type.split(";", 1)[0],
                    "bytes_read": total,
                    "truncated": truncated,
                }
    raise OutboundURLValidationError("web fetch failed")

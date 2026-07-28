"""附件对象存储抽象，支持本地原子文件与 S3 兼容 SigV4 API。"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

from infra.config.settings import settings


@dataclass(frozen=True)
class ObjectRef:
    backend: str
    key: str
    etag: str
    size: int


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> ObjectRef: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...


def _safe_key(key: str) -> str:
    path = PurePosixPath(str(key).strip().lstrip("/"))
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("非法对象键")
    return str(path)


class LocalObjectStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve()

    def _path(self, key: str) -> Path:
        target = (self.root / _safe_key(key)).resolve()
        if self.root not in target.parents:
            raise ValueError("对象键越界")
        return target

    async def put(self, key: str, data: bytes, content_type: str) -> ObjectRef:
        del content_type
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        return ObjectRef("local", _safe_key(key), hashlib.sha256(data).hexdigest(), len(data))

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3ObjectStore:
    """最小 S3-compatible 客户端；凭据只从运行时设置读取，不落库。"""

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
        path_style: bool = True,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.path_style = path_style

    def _url(self, key: str) -> str:
        safe = quote(_safe_key(key), safe="/")
        parsed = urlparse(self.endpoint)
        if self.path_style:
            return f"{self.endpoint}/{quote(self.bucket, safe='')}/{safe}"
        return f"{parsed.scheme}://{self.bucket}.{parsed.netloc}/{safe}"

    def _signed_headers(
        self, method: str, url: str, payload_hash: str, content_type: str, now: datetime
    ) -> dict[str, str]:
        parsed = urlparse(url)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        canonical_uri = quote(parsed.path or "/", safe="/-_.~")
        canonical_headers = (
            f"content-type:{content_type}\nhost:{parsed.netloc}\n"
            f"x-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
        )
        signed = "content-type;host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [method, canonical_uri, parsed.query, canonical_headers, signed, payload_hash]
        )
        scope = f"{day}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )

        def sign(key: bytes, value: str) -> bytes:
            return hmac.new(key, value.encode(), hashlib.sha256).digest()

        date_key = sign(("AWS4" + self.secret_key).encode(), day)
        region_key = sign(date_key, self.region)
        service_key = sign(region_key, "s3")
        signing_key = sign(service_key, "aws4_request")
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        return {
            "content-type": content_type,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            "authorization": (
                f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
                f"SignedHeaders={signed}, Signature={signature}"
            ),
        }

    async def _request(
        self,
        method: str,
        key: str,
        data: bytes = b"",
        content_type: str = "application/octet-stream",
    ) -> httpx.Response:
        url = self._url(key)
        payload_hash = hashlib.sha256(data).hexdigest()
        headers = self._signed_headers(method, url, payload_hash, content_type, datetime.now(UTC))
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.request(method, url, headers=headers, content=data)
        response.raise_for_status()
        return response

    async def put(self, key: str, data: bytes, content_type: str) -> ObjectRef:
        response = await self._request("PUT", key, data, content_type)
        etag = response.headers.get("etag", "").strip('"') or hashlib.sha256(data).hexdigest()
        return ObjectRef("s3", _safe_key(key), etag, len(data))

    async def get(self, key: str) -> bytes:
        return (await self._request("GET", key)).content

    async def delete(self, key: str) -> None:
        await self._request("DELETE", key)


def get_object_store() -> ObjectStore | None:
    backend = str(settings.object_storage_backend or "database").lower()
    if backend == "database":
        return None
    if backend == "local":
        return LocalObjectStore(settings.object_storage_local_path)
    if backend == "s3":
        return S3ObjectStore(
            endpoint=settings.object_storage_endpoint,
            bucket=settings.object_storage_bucket,
            region=settings.object_storage_region,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
            path_style=settings.object_storage_path_style,
        )
    raise ValueError(f"未知对象存储后端: {backend}")


def attachment_object_key(*, tenant_id: str, workspace_id: str, content_hash: str) -> str:
    return _safe_key(f"attachments/{tenant_id}/{workspace_id}/{content_hash[:2]}/{content_hash}")

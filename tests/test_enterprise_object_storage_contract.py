from __future__ import annotations

import hashlib

import pytest

from infra.storage.object_store import LocalObjectStore, S3ObjectStore, attachment_object_key


@pytest.mark.asyncio
async def test_local_object_store_is_atomic_and_scoped(tmp_path):
    store = LocalObjectStore(str(tmp_path))
    key = attachment_object_key(tenant_id="tenant-a", workspace_id="ws-a", content_hash="a" * 64)
    ref = await store.put(key, b"hello", "text/plain")
    assert ref.etag == hashlib.sha256(b"hello").hexdigest()
    assert await store.get(key) == b"hello"
    await store.delete(key)
    assert not (tmp_path / key).exists()


def test_object_key_rejects_path_traversal(tmp_path):
    store = LocalObjectStore(str(tmp_path))
    with pytest.raises(ValueError):
        store._path("../secret")


def test_s3_signature_never_puts_secret_in_headers():
    store = S3ObjectStore(
        endpoint="https://s3.example.com",
        bucket="bucket",
        region="us-east-1",
        access_key="access",
        secret_key="secret-value",
    )
    from datetime import UTC, datetime

    headers = store._signed_headers(
        "PUT", store._url("a/b"), hashlib.sha256(b"x").hexdigest(), "text/plain", datetime.now(UTC)
    )
    assert "AWS4-HMAC-SHA256" in headers["authorization"]
    assert "secret-value" not in str(headers)

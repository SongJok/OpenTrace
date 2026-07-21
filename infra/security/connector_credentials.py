"""Encryption helpers for persisted connector credentials."""

from __future__ import annotations

import json
from dataclasses import asdict

from connectors.sdk.protocol import CredentialRef
from infra.security.data_source_secrets import (
    decrypt_data_source_secret,
    encrypt_data_source_secret,
)


def encrypt_connector_credential(credential: CredentialRef) -> str:
    payload = json.dumps(asdict(credential), ensure_ascii=False, separators=(",", ":"))
    return encrypt_data_source_secret(payload)


def decrypt_connector_credential(encrypted: str) -> CredentialRef:
    payload = json.loads(decrypt_data_source_secret(encrypted))
    if not isinstance(payload, dict):
        raise ValueError("invalid connector credential payload")
    return CredentialRef(
        provider=str(payload.get("provider") or ""),
        account_id=str(payload.get("account_id") or ""),
        access_token=str(payload.get("access_token") or ""),
        refresh_token=str(payload.get("refresh_token") or ""),
        expires_at=payload.get("expires_at"),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )

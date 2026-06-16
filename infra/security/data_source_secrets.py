"""Decrypt data-source credentials (shared by API and agents — no gateway import)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from infra.config.settings import get_settings


def _fernet() -> Fernet:
    secret = get_settings().data_secret_key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_data_source_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_data_source_secret(encrypted: str) -> str:
    return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
from io import BytesIO

import pytest
from fastapi import UploadFile

from gateway.api_gateway.routers.documents import _read_document_upload
from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes


@pytest.mark.asyncio
async def test_document_upload_limit_accepts_pdf_within_configured_size(monkeypatch):
    monkeypatch.setattr(settings, "attachment_max_size_mb", 1)
    upload = UploadFile(filename="company.pdf", file=BytesIO(b"%PDF-1.7\n" + b"a" * 1024))

    raw = await _read_document_upload(upload)

    assert raw.startswith(b"%PDF-1.7")


@pytest.mark.asyncio
async def test_document_upload_limit_rejects_oversized_file_before_ingestion(monkeypatch):
    monkeypatch.setattr(settings, "attachment_max_size_mb", 1)
    upload = UploadFile(filename="company.pdf", file=BytesIO(b"a" * (1024 * 1024 + 1)))

    with pytest.raises(AppException) as exc_info:
        await _read_document_upload(upload)

    assert exc_info.value.code == ErrorCodes.PARAM_INVALID.code
    assert exc_info.value.message == "单个文档不能超过 1MB"


@pytest.mark.asyncio
async def test_document_upload_limit_rejects_empty_file(monkeypatch):
    monkeypatch.setattr(settings, "attachment_max_size_mb", 1)
    upload = UploadFile(filename="empty.pdf", file=BytesIO())

    with pytest.raises(AppException) as exc_info:
        await _read_document_upload(upload)

    assert exc_info.value.code == ErrorCodes.PARAM_INVALID.code
    assert exc_info.value.message == "文档不能为空"

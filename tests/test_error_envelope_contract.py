"""框架级 404 与请求校验错误也必须遵守统一错误信封。"""

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request

from gateway.api_gateway.main import (
    http_exception_handler,
    request_validation_exception_handler,
)


def _request() -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/missing", "headers": []})
    request.state.request_id = "request-test"
    return request


async def test_framework_404_uses_application_error_envelope():
    response = await http_exception_handler(
        _request(), HTTPException(status_code=404, detail="Not Found")
    )
    body = response.body.decode("utf-8")
    assert response.status_code == 404
    for field in ("code", "message", "details", "request_id", "timestamp"):
        assert f'"{field}"' in body


async def test_request_validation_uses_application_error_envelope():
    error = RequestValidationError(
        [{"type": "missing", "loc": ("body", "input"), "msg": "Field required", "input": {}}]
    )
    response = await request_validation_exception_handler(_request(), error)
    body = response.body.decode("utf-8")
    assert response.status_code == 422
    assert '"code":1003' in body
    assert '"request_id":"request-test"' in body

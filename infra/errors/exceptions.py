from __future__ import annotations

from typing import Any, Optional

from .error_codes import ErrorCodes, ErrorSpec, get_error_spec


class AppException(Exception):
    def __init__(
        self,
        code: int,
        message: Optional[str] = None,
        details: Any = None,
        http_status: Optional[int] = None,
    ) -> None:
        spec = get_error_spec(code)
        self.code = code
        self.message = message or spec.message
        self.details = details
        self.http_status = http_status or spec.http_status
        super().__init__(self.message)


class ValidationException(AppException):
    def __init__(self, message: str, details: Any = None):
        super().__init__(ErrorCodes.PARAM_INVALID.code, message=message, details=details)


class NotFoundException(AppException):
    def __init__(self, message: str, details: Any = None):
        super().__init__(ErrorCodes.RESOURCE_NOT_FOUND.code, message=message, details=details)


class DependencyException(AppException):
    def __init__(self, spec: ErrorSpec = ErrorCodes.UPSTREAM_UNAVAILABLE, message: Optional[str] = None, details: Any = None):
        super().__init__(spec.code, message=message or spec.message, details=details, http_status=spec.http_status)


class TimeoutException(AppException):
    def __init__(self, message: str = "请求超时", details: Any = None):
        super().__init__(ErrorCodes.LLM_TIMEOUT.code, message=message, details=details)

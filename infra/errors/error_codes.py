from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    code: int
    http_status: int
    message: str


class ErrorCodes:
    # Global (00)
    PARAM_MISSING = ErrorSpec(1001, 400, "参数缺失")
    PARAM_TYPE = ErrorSpec(1002, 400, "参数类型错误")
    PARAM_INVALID = ErrorSpec(1003, 400, "参数校验失败")
    PERMISSION_DENIED = ErrorSpec(2001, 403, "无权限访问该资源")
    RESOURCE_EXISTS = ErrorSpec(2002, 409, "资源已存在")
    RESOURCE_NOT_FOUND = ErrorSpec(3001, 404, "资源不存在")
    INTERNAL_ERROR = ErrorSpec(5001, 500, "服务内部错误")

    # Auth (01)
    AUTH_SERVICE_UNAVAILABLE = ErrorSpec(104001, 503, "认证服务不可用")
    AUTH_INTERNAL_ERROR = ErrorSpec(104002, 500, "认证内部错误")
    AUTH_UNKNOWN = ErrorSpec(105001, 500, "认证未知错误")

    # Registration (02)
    REGISTRATION_DISABLED = ErrorSpec(2003, 403, "注册功能已关闭")
    REGISTRATION_EMAIL_DOMAIN_DENIED = ErrorSpec(2004, 403, "该邮箱域名不允许注册")
    REGISTRATION_PENDING = ErrorSpec(2005, 403, "账户尚未通过审核，请联系管理员")
    REGISTRATION_DISABLED_ACCOUNT = ErrorSpec(2006, 403, "账户已被禁用，请联系管理员")
    USER_ALREADY_PROCESSED = ErrorSpec(2007, 400, "该用户已被处理，无需重复操作")

    # Chat (02)
    LLM_SERVICE_UNAVAILABLE = ErrorSpec(204001, 503, "LLM 服务不可用")
    LLM_CALL_FAILED = ErrorSpec(204002, 500, "LLM 调用失败")
    LLM_TIMEOUT = ErrorSpec(206001, 504, "LLM 请求超时")
    RATE_LIMITED = ErrorSpec(207001, 429, "请求限流，请稍后重试")

    # Document (03)
    VECTOR_DB_UNAVAILABLE = ErrorSpec(304001, 503, "向量数据库不可用")
    DOCUMENT_PARSE_FAILED = ErrorSpec(305001, 500, "文档解析失败")

    # System (09)
    UPSTREAM_UNAVAILABLE = ErrorSpec(904001, 503, "依赖服务不可用")


_ERROR_INDEX = {
    spec.code: spec
    for spec in ErrorCodes.__dict__.values()
    if isinstance(spec, ErrorSpec)
}


def get_error_spec(code: int) -> ErrorSpec:
    return _ERROR_INDEX.get(code, ErrorCodes.INTERNAL_ERROR)

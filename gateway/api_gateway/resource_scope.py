"""API 兼容入口；授权真相位于 ``infra.security.resource_scope``。"""

from infra.security.resource_scope import (  # noqa: F401
    PERMISSION_RANK,
    accessible_data_sources_statement,
    get_accessible_data_source,
    get_owned_data_source,
    normalized_tenant_scope,
    owned_data_sources_statement,
    scoped_documents_statement,
)

__all__ = [
    "PERMISSION_RANK",
    "accessible_data_sources_statement",
    "get_accessible_data_source",
    "get_owned_data_source",
    "normalized_tenant_scope",
    "owned_data_sources_statement",
    "scoped_documents_statement",
]

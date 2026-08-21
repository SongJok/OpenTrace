"""注册 OpenTrace 自带的 Connector Adapter。"""

from __future__ import annotations

from importlib import metadata
from typing import Any

from connectors.mcp import (
    EnvironmentBearerSecretResolver,
    MCPStreamableHTTPAdapter,
    SecretHeaderResolver,
)
from connectors.prometheus import PrometheusHTTPAdapter
from connectors.registry import ConnectorRegistry, connector_registry

_ENTRY_POINT_GROUP = "opentrace.connectors"
_SECRET_RESOLVER_ENTRY_POINT_GROUP = "opentrace.connector_secret_resolvers"


def _entry_points_for_group() -> list[Any]:
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return list(discovered.select(group=_ENTRY_POINT_GROUP))
    return list(discovered.get(_ENTRY_POINT_GROUP, ()))


def _secret_resolver_entry_points() -> list[Any]:
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return list(discovered.select(group=_SECRET_RESOLVER_ENTRY_POINT_GROUP))
    return list(discovered.get(_SECRET_RESOLVER_ENTRY_POINT_GROUP, ()))


def load_configured_secret_resolver(name: str | None = None) -> SecretHeaderResolver:
    """加载唯一允许的 MCP Secret Resolver；空配置使用 env://。"""

    if name is None:
        from infra.config.settings import settings

        name = settings.connector_secret_resolver_entrypoint
    name = str(name or "").strip()
    if not name:
        return EnvironmentBearerSecretResolver()
    by_name = {str(item.name): item for item in _secret_resolver_entry_points()}
    entrypoint = by_name.get(name)
    if entrypoint is None:
        raise RuntimeError(f"connector_secret_resolver_entrypoint_missing:{name}")
    loaded = entrypoint.load()
    resolver = loaded
    if not callable(getattr(resolver, "resolve_headers", None)) and callable(resolver):
        resolver = resolver()
    if not callable(getattr(resolver, "resolve_headers", None)):
        raise RuntimeError(f"connector_secret_resolver_entrypoint_invalid:{name}")
    return resolver


def register_configured_connectors(
    *,
    registry: ConnectorRegistry = connector_registry,
    names: tuple[str, ...] | None = None,
    force: bool = False,
) -> tuple[str, ...]:
    """只加载部署配置显式允许的已安装 Adapter entry point。"""

    if names is None:
        from infra.config.settings import settings

        names = tuple(settings.connector_adapter_entrypoint_list)
    if not names:
        return ()
    if len(names) != len(set(names)):
        raise RuntimeError("connector_adapter_entrypoint_allowlist_duplicate")
    by_name = {str(item.name): item for item in _entry_points_for_group()}
    missing = sorted(set(names) - set(by_name))
    if missing:
        raise RuntimeError(f"connector_adapter_entrypoint_missing:{','.join(missing)}")

    registered: list[str] = []
    for name in names:
        loaded = by_name[name].load()
        adapter = loaded
        if not getattr(adapter, "adapter_key", None) and callable(adapter):
            adapter = adapter()
        adapter_key = str(getattr(adapter, "adapter_key", "") or "").strip().lower()
        if not adapter_key:
            raise RuntimeError(f"connector_adapter_entrypoint_invalid:{name}")
        existing = registry.get(adapter_key)
        if existing is adapter or (existing is not None and not force):
            if existing is not None and existing is not adapter:
                raise RuntimeError(f"connector_adapter_key_conflict:{adapter_key}")
            continue
        registry.register(adapter, replace=force)
        registered.append(adapter_key)
    return tuple(registered)


def register_builtin_connectors(*, force: bool = False) -> None:
    requires_resolver = (
        connector_registry.get("mcp") is None
        or connector_registry.get("prometheus") is None
        or force
    )
    resolver = load_configured_secret_resolver() if requires_resolver else None
    if connector_registry.get("mcp") is None or force:
        connector_registry.register(
            MCPStreamableHTTPAdapter(secret_resolver=resolver),
            replace=force,
        )
    if connector_registry.get("prometheus") is None or force:
        connector_registry.register(
            PrometheusHTTPAdapter(secret_resolver=resolver),
            replace=force,
        )
    register_configured_connectors(force=force)

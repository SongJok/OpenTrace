"""进程内 Connector Adapter 注册表。"""

from __future__ import annotations

from threading import RLock

from connectors.contracts import EnterpriseConnectorAdapter


class ConnectorRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._adapters: dict[str, EnterpriseConnectorAdapter] = {}

    def register(self, adapter: EnterpriseConnectorAdapter, *, replace: bool = False) -> None:
        key = str(adapter.adapter_key or "").strip().lower()
        if not key:
            raise ValueError("connector_adapter_key_required")
        with self._lock:
            if key in self._adapters and not replace:
                raise ValueError(f"connector_adapter_already_registered:{key}")
            operations = adapter.operations()
            names = [item.name for item in operations]
            dynamic = bool(getattr(adapter, "dynamic_operations", False))
            if (not names and not dynamic) or len(names) != len(set(names)):
                raise ValueError(f"connector_adapter_operations_invalid:{key}")
            self._adapters[key] = adapter

    def get(self, adapter_key: str) -> EnterpriseConnectorAdapter | None:
        with self._lock:
            return self._adapters.get((adapter_key or "").strip().lower())

    def require(self, adapter_key: str) -> EnterpriseConnectorAdapter:
        adapter = self.get(adapter_key)
        if adapter is None:
            raise KeyError(f"connector_adapter_not_registered:{adapter_key}")
        return adapter

    def list_adapter_keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._adapters))

    def clear(self) -> None:
        """仅供隔离测试使用。"""

        with self._lock:
            self._adapters.clear()


connector_registry = ConnectorRegistry()

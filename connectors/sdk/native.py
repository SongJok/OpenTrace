"""Native Connector 适配器构建器。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol

from connectors.contracts import (
    ConnectorExecutionContext,
    ConnectorOperationSpec,
    ConnectorResult,
)


class NativeConnectorHandler(Protocol):
    async def __call__(
        self,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult: ...


class NativeConnectorAdapter:
    """将确定性操作目录与处理函数绑定成受治理适配器。"""

    def __init__(
        self,
        *,
        adapter_key: str,
        operations: tuple[ConnectorOperationSpec, ...],
        handlers: dict[str, NativeConnectorHandler],
    ) -> None:
        normalized_key = adapter_key.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,127}", normalized_key):
            raise ValueError("native_connector_adapter_key_invalid")
        names = [spec.name for spec in operations]
        if not operations or len(names) != len(set(names)):
            raise ValueError("native_connector_operations_invalid")
        if set(names) != set(handlers):
            raise ValueError("native_connector_handlers_mismatch")
        self.adapter_key = normalized_key
        self._operations = tuple(operations)
        self._handlers = dict(handlers)

    def operations(self) -> tuple[ConnectorOperationSpec, ...]:
        return self._operations

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult:
        handler = self._handlers.get(operation)
        if handler is None:
            raise RuntimeError("native_connector_operation_not_declared")
        result = await handler(
            dict(arguments),
            context=context,
            connector_config=dict(connector_config),
            secret_ref=secret_ref,
        )
        if not isinstance(result, ConnectorResult):
            raise TypeError("native_connector_result_invalid")
        return result


class NativeConnectorBuilder:
    """以装饰器形式构建 Native Connector，不复制 Gateway 治理逻辑。"""

    def __init__(self, adapter_key: str) -> None:
        self.adapter_key = adapter_key
        self._specs: list[ConnectorOperationSpec] = []
        self._handlers: dict[str, NativeConnectorHandler] = {}

    def operation(
        self, spec: ConnectorOperationSpec
    ) -> Callable[[NativeConnectorHandler], NativeConnectorHandler]:
        def register(handler: NativeConnectorHandler) -> NativeConnectorHandler:
            if spec.name in self._handlers:
                raise ValueError(f"native_connector_operation_duplicate:{spec.name}")
            self._specs.append(spec)
            self._handlers[spec.name] = handler
            return handler

        return register

    def build(self) -> NativeConnectorAdapter:
        return NativeConnectorAdapter(
            adapter_key=self.adapter_key,
            operations=tuple(self._specs),
            handlers=self._handlers,
        )

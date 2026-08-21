"""受治理 Connector SDK；外部系统适配器必须通过此边界执行。"""

from connectors.contracts import (
    ConnectorEvidence,
    ConnectorExecutionContext,
    ConnectorOperationSpec,
    ConnectorResult,
    EnterpriseConnectorAdapter,
)
from connectors.registry import ConnectorRegistry, connector_registry

__all__ = [
    "ConnectorEvidence",
    "ConnectorExecutionContext",
    "ConnectorOperationSpec",
    "ConnectorRegistry",
    "ConnectorResult",
    "EnterpriseConnectorAdapter",
    "connector_registry",
]

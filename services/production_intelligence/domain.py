"""生产智能平台的受控领域词表。"""

from __future__ import annotations

from enum import StrEnum


class AssetType(StrEnum):
    BUSINESS_DOMAIN = "business_domain"
    SERVICE = "service"
    REPOSITORY = "repository"
    DEPLOYMENT = "deployment"
    CONFIG = "config"
    DATABASE = "database"
    TABLE = "table"
    DASHBOARD = "dashboard"
    ALERT = "alert"
    OWNER = "owner"
    RUNBOOK = "runbook"
    BUSINESS_API = "business_api"


class RelationType(StrEnum):
    CONTAINS = "contains"
    OWNED_BY = "owned_by"
    DEPENDS_ON = "depends_on"
    REPOSITORY_FOR = "repository_for"
    DEPLOYED_AS = "deployed_as"
    CONFIGURED_BY = "configured_by"
    READS_FROM = "reads_from"
    WRITES_TO = "writes_to"
    MONITORED_BY = "monitored_by"
    DOCUMENTED_BY = "documented_by"
    EXPOSES = "exposes"


class ConnectorKind(StrEnum):
    DATA = "data"
    OBSERVABILITY = "observability"
    KNOWLEDGE = "knowledge"
    CODE = "code"
    BUSINESS = "business"
    CONFIG = "config"
    CICD = "cicd"
    CMDB = "cmdb"
    KUBERNETES = "kubernetes"


class ConnectorTransport(StrEnum):
    MCP = "mcp"
    NATIVE = "native"
    REST = "rest"
    RPC = "rpc"


class OperationRisk(StrEnum):
    READ = "read"
    WRITE_LOW = "write_low"
    WRITE_HIGH = "write_high"
    DESTRUCTIVE = "destructive"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


ASSET_TYPES = frozenset(item.value for item in AssetType)
RELATION_TYPES = frozenset(item.value for item in RelationType)
CONNECTOR_KINDS = frozenset(item.value for item in ConnectorKind)
CONNECTOR_TRANSPORTS = frozenset(item.value for item in ConnectorTransport)
OPERATION_RISKS = frozenset(item.value for item in OperationRisk)
DATA_CLASSIFICATIONS = frozenset(item.value for item in DataClassification)

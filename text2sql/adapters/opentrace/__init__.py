"""将独立 Text2SQL 核心接入 OpenTrace 现有数据源和模型网关。"""

from text2sql.adapters.opentrace.evidence import OpenTraceEvidenceProvider
from text2sql.adapters.opentrace.executor import OpenTraceQueryExecutor
from text2sql.adapters.opentrace.generator import OpenTraceSQLGenerator
from text2sql.adapters.opentrace.repository import OpenTraceRunRepository

__all__ = [
    "OpenTraceEvidenceProvider",
    "OpenTraceQueryExecutor",
    "OpenTraceRunRepository",
    "OpenTraceSQLGenerator",
]

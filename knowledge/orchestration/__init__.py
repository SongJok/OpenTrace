"""知识编排公共 API。

在线事实源位于 ``knowledge`` 领域模型；本包提供稳定编排接口与 Obsidian
投影视图，避免调用方直接耦合编译器、队列或 ORM。
"""

from knowledge.orchestration.data import (
    ManifestAsset,
    ManifestManager,
    RawAsset,
    RawAssetManager,
    WorkspaceManifest,
)
from knowledge.orchestration.metadata import (
    BuildGuidelines,
    BuildStage,
    MergeDecision,
    MergeRules,
    PageSchema,
    ScheduledKnowledgeTask,
    SchemaManager,
)
from knowledge.orchestration.wiki import (
    HotMemory,
    HotMemoryEntry,
    IngestPipeline,
    IngestResult,
    LintChecker,
    LintIssue,
    LintResult,
    QueryPipeline,
    QueryResult,
    RetrievalLevel,
)

__all__ = [
    "BuildGuidelines",
    "BuildStage",
    "HotMemory",
    "HotMemoryEntry",
    "IngestPipeline",
    "IngestResult",
    "KnowledgeVault",
    "KnowledgeWorkspace",
    "LintChecker",
    "LintIssue",
    "LintResult",
    "ManifestAsset",
    "ManifestManager",
    "MaterializeResult",
    "MergeDecision",
    "MergeRules",
    "PageSchema",
    "QueryPipeline",
    "QueryResult",
    "RawAsset",
    "RawAssetManager",
    "RetrievalLevel",
    "ScheduledKnowledgeTask",
    "SchemaManager",
    "WorkspaceManifest",
    "WorkspacePage",
    "WorkspaceRelation",
    "WorkspaceSnapshot",
    "WorkspaceSource",
]


def __getattr__(name: str):
    """延迟加载 Vault 投影，避免 workspace 与 orchestration 的导入环。"""
    if name in {
        "KnowledgeVault",
        "KnowledgeWorkspace",
        "MaterializeResult",
        "WorkspacePage",
        "WorkspaceRelation",
        "WorkspaceSnapshot",
        "WorkspaceSource",
    }:
        from knowledge import workspace

        return getattr(workspace, name)
    raise AttributeError(name)

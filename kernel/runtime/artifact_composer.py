"""
ArtifactComposer — 将 FusionResult + CriticResult 封装为命名的 Artifact。

纯数据转换 — 不调用 LLM。生成结构化、有类型、带标签的 Artifact，
包含完整证据溯源和置信度元数据。
"""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class ArtifactComposer:
    """将 FusionResult + CriticResult 组合为命名、有类型的 Artifact。

    不调用 LLM — 确定性数据转换。
    """

    def compose(
        self,
        query: str,
        fusion_result: Any,  # FusionResult
        critic_result: Any,  # CriticResult
        session_id: str = "",
        turn_id: str = "",
        intent_category: str = "",
        tags: list[str] | None = None,
        workspace_manager: Any = None,  # WorkspaceManager
    ) -> Any:  # Artifact
        """从融合 + 批评结果生成 Artifact。

        Artifact 携带完整溯源：使用了哪些证据、如何融合、
        分配了什么质量评分。
        """
        from kernel.runtime.artifacts import Artifact, ArtifactManager

        # 从内容自动推断 artifact 类型
        content = fusion_result.merged_context or ""
        confidence = getattr(fusion_result, "confidence", 0.0)

        artifact_type = _infer_artifact_type(content, intent_category)
        name = _generate_artifact_name(query, artifact_type)

        all_tags = list(tags or [])
        if intent_category:
            all_tags.append(intent_category)

        metadata = {
            "fusion_method": getattr(fusion_result, "method", ""),
            "fusion_confidence": confidence,
            "evidence_ids": getattr(fusion_result, "evidence_ids", []),
            "critic_passed": getattr(critic_result, "passed", False),
            "critic_factuality": getattr(critic_result, "factuality", 0.0),
            "critic_completeness": getattr(critic_result, "completeness", 0.0),
            "critic_hallucination_risk": getattr(critic_result, "hallucination_risk", 0.0),
            "critic_evidence_utilization": getattr(critic_result, "evidence_utilization", 0.0),
            "critic_notes": getattr(critic_result, "notes", ""),
        }

        artifact = Artifact(
            session_id=session_id,
            turn_id=turn_id,
            name=name,
            artifact_type=artifact_type,
            content=content,
            content_type="text/markdown",
            tags=all_tags,
            metadata=metadata,
        )

        logger.debug(
            "Artifact composed",
            name=name,
            type=artifact_type,
            confidence=confidence,
            evidence_count=len(metadata["evidence_ids"]),
        )

        return artifact


def _infer_artifact_type(content: str, intent_category: str) -> str:
    """从内容结构和意图推断 artifact 类型。"""
    if "|" in content and "\n" in content and content.count("|") > 3:
        return "table"
    if intent_category in ("data", "data_analysis"):
        return "table"
    if content.startswith("```") or "def " in content:
        return "code"
    return "text"


def _generate_artifact_name(query: str, artifact_type: str) -> str:
    """从查询生成可读的 artifact 名称。"""
    # 将查询截断为合理的名称长度
    name = query.strip()[:60]
    if len(query) > 60:
        name += "..."
    return name

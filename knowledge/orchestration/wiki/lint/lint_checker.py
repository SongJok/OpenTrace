"""知识健康检查的公共适配层。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.storage.database import AsyncSessionLocal
from knowledge.lint import run_knowledge_lint


@dataclass(frozen=True, slots=True)
class LintIssue:
    code: str
    severity: str
    resource_type: str
    resource_id: str
    message: str

    @property
    def page_title(self) -> str:
        return self.resource_id


@dataclass(slots=True)
class LintResult:
    issues: list[LintIssue] = field(default_factory=list)
    health_score: float = 100.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def critical_issues(self) -> list[LintIssue]:
        return [item for item in self.issues if item.severity in {"critical", "error"}]


class LintChecker:
    async def check_workspace(
        self,
        *,
        workspace_id: str,
        tenant_id: str = "default",
        owner_id: str | None = None,
    ) -> LintResult:
        async with AsyncSessionLocal() as db:
            raw = await run_knowledge_lint(
                db,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_id=owner_id,
            )
            await db.commit()
        issues = [LintIssue(**item) for item in raw.get("findings", [])]
        return LintResult(issues=issues, health_score=self.get_health_score(issues), raw=raw)

    @staticmethod
    def get_health_score(result: LintResult | list[LintIssue]) -> float:
        issues = result.issues if isinstance(result, LintResult) else result
        weights = {"critical": 15.0, "error": 8.0, "warning": 2.0, "info": 0.5}
        penalty = sum(weights.get(item.severity, 1.0) for item in issues)
        return round(max(0.0, 100.0 - penalty), 1)

"""规则执行 Agent — 将查询与业务规则匹配。

关键词匹配为主，规则解读回退使用 LLMRole.CHEAP_CRITIC。
"""

from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage

# 常见规则类别及关键词触发器
_RULE_PATTERNS: dict[str, list[str]] = {
    "usage_policy": ["使用规范", "使用规则", "用法", "怎么用", "使用说明", "操作指南"],
    "data_privacy": ["隐私", "数据保护", "个人信息", "GDPR", "合规"],
    "access_control": ["权限", "谁能访问", "允许", "拒绝", "授权"],
    "content_guidelines": ["内容规范", "发布规则", "审核", "违规"],
    "security": ["安全", "漏洞", "加密", "认证", "防火墙"],
}


class RuleEngineAgent(BaseAgent):
    agent_type = "rules"

    def __init__(self) -> None:
        super().__init__(agent_type=self.agent_type)

    async def execute(self, task: TaskMessage) -> AgentResult:
        query = getattr(task, "query", "") or ""
        params = getattr(task, "params", None) or {}

        matched_rules: list[str] = []

        # Step 1: keyword matching
        query_lower = query.lower()
        for category, keywords in _RULE_PATTERNS.items():
            if any(kw in query_lower for kw in keywords):
                matched_rules.append(category)

        # Step 2: if params specify a rule category, include it directly
        rule_category = params.get("rule_category", "")
        if rule_category and rule_category not in matched_rules:
            matched_rules.append(rule_category)

        if not matched_rules:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="",
                confidence=0.1,
                metadata={
                    "matched_rules": [],
                    "note": "no matching rules found",
                    "policy_decision": "no_match",
                },
                evidence_objects=[
                    self._make_evidence_object(
                        content="no matching rules",
                        source_type="policy",
                        credibility=0.1,
                        relevance=0.2,
                        metadata={"matched_rules": [], "policy_decision": "no_match"},
                    )
                ],
            )

        # Step 3: generate rule explanation
        try:
            from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

            gw = get_model_gateway()
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are a compliance and business rules assistant. "
                        "Explain the relevant rules or policies concisely in Chinese. "
                        "If you don't know the specific rule, say '未找到具体规则'."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"查询: {query[:500]}\n"
                        f"匹配的规则类别: {', '.join(matched_rules)}\n"
                        f"请简要说明相关规则要点。"
                    ),
                ),
            ]
            response = await gw.complete(messages, role=LLMRole.CHEAP_CRITIC)
            content = (response.content or "").strip()
        except Exception:
            content = f"匹配到规则类别: {', '.join(matched_rules)}"

        body = content or f"匹配到规则类别: {', '.join(matched_rules)}"
        conf = min(0.5 + len(matched_rules) * 0.1, 0.9)
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=body,
            confidence=conf,
            metadata={
                "matched_rules": matched_rules,
                "method": "keyword" if not content else "llm_critic",
                "policy_decision": "matched",
                "matched_rule_ids": matched_rules,
            },
            evidence_objects=[
                self._make_evidence_object(
                    content=body[:4000],
                    source_type="policy",
                    credibility=conf,
                    relevance=0.85,
                    metadata={
                        "matched_rules": matched_rules,
                        "policy_decision": "matched",
                    },
                )
            ],
        )

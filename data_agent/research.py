"""有限预算的数据研究规划器。"""

from __future__ import annotations

import re

from data_agent.contracts import EvidenceType, ResearchPlan, ResearchStep


class ResearchPlanner:
    """根据问题特征选择证据来源。

    这是策略层，不让模型自行发现未授权数据源。数据源的选择由请求 Scope 锁定，
    规划器只决定在该范围内需要读取哪些类型的证据。
    """

    _metric_terms = re.compile(
        r"收入|流水|销售|金额|数量|人数|用户数|订单数|占比|率|均值|平均|总计|"
        r"gmv|revenue|count|sum|avg",
        re.I,
    )
    _process_terms = re.compile(r"流程|状态|支付|退款|发货|注册|转化|留存|生命周期|原因|为什么")
    _policy_terms = re.compile(r"政策|规则|活动|奖励|结算|退款|为什么|原因|变更")
    _report_terms = re.compile(r"报表|日报|周报|月报|经营看板|dashboard|bi", re.I)
    _time_terms = re.compile(
        r"今天|昨日|本周|本月|今年|去年|最近|过去|趋势|同比|环比|日|周|月|季度|年", re.I
    )
    _skill_terms = re.compile(r"趋势|同比|环比|漏斗|留存|cohort|top|排名|分布|异常|复购|转化", re.I)

    def plan(self, question: str) -> ResearchPlan:
        text = str(question or "").strip()
        steps: list[ResearchStep] = [
            ResearchStep(
                source=EvidenceType.SCHEMA, reason="任何 SQL 都必须先证明表和字段属于当前数据源"
            ),
            ResearchStep(
                source=EvidenceType.SOURCE_POLICY,
                reason="读取数据源级访问、脱敏和审批规则",
            ),
            ResearchStep(
                source=EvidenceType.RELATIONSHIP, reason="需要验证可用 JOIN 路径和基数风险"
            ),
        ]
        if self._metric_terms.search(text):
            steps.append(
                ResearchStep(
                    source=EvidenceType.METRIC, reason="问题包含聚合或业务指标词", max_items=30
                )
            )
            steps.append(
                ResearchStep(
                    source=EvidenceType.BUSINESS_RULE,
                    reason="指标必须同时读取固有过滤、排除条件和口径变更规则",
                )
            )
        if self._time_terms.search(text):
            steps.append(
                ResearchStep(
                    source=EvidenceType.COLUMN_PROFILE,
                    reason="需要选择正确的事件时间字段和时间粒度",
                )
            )
        if self._process_terms.search(text):
            steps.append(
                ResearchStep(
                    source=EvidenceType.BUSINESS_PROCESS, reason="问题涉及业务状态或线上流程"
                )
            )
            steps.append(
                ResearchStep(
                    source=EvidenceType.KNOWLEDGE,
                    reason="需要检索流程文档和已发布业务口径",
                    required=False,
                )
            )
            steps.append(
                ResearchStep(
                    source=EvidenceType.BUSINESS_RULE,
                    reason="读取业务状态、排除条件和指标计算规则",
                )
            )
        if self._policy_terms.search(text):
            steps.append(
                ResearchStep(
                    source=EvidenceType.POLICY,
                    reason="问题涉及政策、活动或业务规则变化",
                    required=False,
                )
            )
        if self._report_terms.search(text):
            steps.append(
                ResearchStep(
                    source=EvidenceType.REPORT,
                    reason="BI 报表是已确认事实和指标口径的重要证据",
                    required=False,
                )
            )
        if self._skill_terms.search(text):
            steps.append(
                ResearchStep(
                    source=EvidenceType.SKILL,
                    reason="问题适合使用已验证的分析方法模板",
                    required=False,
                )
            )
        steps.append(
            ResearchStep(
                source=EvidenceType.SQL_ASSET,
                reason="检索同一数据源的已验证历史查询作为参考",
                required=False,
            )
        )
        steps.append(
            ResearchStep(
                source=EvidenceType.LINEAGE,
                reason="选择经过加工和治理的可信表，避免误用原始明细层",
                required=False,
            )
        )
        steps.append(
            ResearchStep(
                source=EvidenceType.EXECUTION_MEMORY,
                reason="复用相同作用域内已验证的历史计划和结果校验经验",
                required=False,
            )
        )
        steps.append(
            ResearchStep(
                source=EvidenceType.FAILURE_MEMORY,
                reason="规避相同作用域和版本下已重复失败的查询结构",
                required=False,
            )
        )
        steps.append(
            ResearchStep(
                source=EvidenceType.DATA_QUALITY,
                reason="执行前检查数据新鲜度和已知质量问题",
                required=False,
            )
        )
        unique: dict[EvidenceType, ResearchStep] = {}
        for step in steps:
            unique.setdefault(step.source, step)
        return ResearchPlan(
            steps=list(unique.values()),
            budget=min(20, max(8, len(unique) * 2)),
            stop_conditions=[
                "没有当前数据源 Schema 时停止并阻止执行",
                "指标或关系存在权威冲突时先澄清",
                "所有证据都必须带来源、作用域和版本",
            ],
        )

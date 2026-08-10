"""使用 OpenTrace Model Gateway 生成受逻辑计划约束的 SQL 候选。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from kernel.data_cognition.sql_dialect import detect_sql_dialect
from kernel.data_cognition.sql_planner import SQLPlanner
from text2sql.contracts import (
    CandidateSQL,
    EvidenceBundle,
    EvidenceType,
    LogicalQueryPlan,
    QueryRequest,
)


class OpenTraceSQLGenerator:
    def __init__(self, planner: SQLPlanner | None = None) -> None:
        self.planner = planner or SQLPlanner()

    async def generate(
        self,
        request: QueryRequest,
        logical_plan: LogicalQueryPlan,
        evidence: EvidenceBundle,
    ) -> Sequence[CandidateSQL]:
        schema = {
            "database": evidence.database_name,
            "tables": [
                {"name": name, "columns": columns}
                for name, columns in evidence.table_columns.items()
            ],
            "metrics": [item.payload for item in evidence.of_type(EvidenceType.METRIC)[:20]],
            "relationships": [
                item.payload for item in evidence.of_type(EvidenceType.RELATIONSHIP)[:50]
            ],
            "sql_references": [
                {
                    "title": item.payload.get("title"),
                    "description": item.payload.get("description"),
                    "sql": item.payload.get("sql"),
                }
                for item in evidence.of_type(EvidenceType.SQL_ASSET)[:5]
            ],
        }
        grounded_question = (
            f"用户问题：{request.question}\n"
            f"结构化逻辑计划：{logical_plan.model_dump_json(ensure_ascii=False)}\n"
            "历史 SQL 只能参考口径，不能复制固定值，也不能绕过当前 Schema。\n"
            f"证据：{json.dumps(schema, ensure_ascii=False)}"
        )
        planned = await self.planner.generate_candidates(
            grounded_question,
            schema_hint=json.dumps(schema, ensure_ascii=False),
            dialect=detect_sql_dialect(evidence.dialect),
            n=request.candidate_count,
        )
        return [CandidateSQL(sql=item.sql, source="model") for item in planned]

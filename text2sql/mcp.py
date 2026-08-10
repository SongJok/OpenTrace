"""Text2SQL 的 MCP 类型化工具清单。

工具清单可被现有 OpenTrace MCP Server 或外部 MCP Gateway 发布。工具本身不携带凭证，
真正调用仍需经过 Text2SQL API 的 Scope、策略和审计链。
"""

from __future__ import annotations

from typing import Any

TEXT2SQL_MCP_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "text2sql.query",
        "description": "在授权数据源范围内研究语义、生成并可选执行只读 SQL",
        "sideEffectLevel": "read",
        "inputSchema": {
            "type": "object",
            "required": ["question", "data_source_id"],
            "properties": {
                "question": {"type": "string", "minLength": 1},
                "data_source_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["sql_only", "execute_and_answer"]},
                "confirmed": {"type": "boolean"},
                "idempotency_key": {"type": "string", "maxLength": 255},
                "max_rows": {"type": "integer", "minimum": 1, "maximum": 10000},
                "project_id": {"type": "string"},
            },
        },
        "annotations": {"durable": True, "requiresDataSourceScope": True},
    },
    {
        "name": "text2sql.catalog",
        "description": "读取授权数据源的 Schema、指标、关系和数据质量证据",
        "sideEffectLevel": "read",
        "inputSchema": {
            "type": "object",
            "required": ["data_source_id"],
            "properties": {
                "data_source_id": {"type": "string"},
                "question": {"type": "string"},
                "project_id": {"type": "string"},
            },
        },
        "annotations": {"durable": False, "requiresDataSourceScope": True},
    },
    {
        "name": "text2sql.feedback",
        "description": "记录用户对 SQL 候选或结果的结构化反馈，不自动晋升知识",
        "sideEffectLevel": "write",
        "inputSchema": {
            "type": "object",
            "required": ["run_id", "data_source_id", "verdict"],
            "properties": {
                "run_id": {"type": "string"},
                "data_source_id": {"type": "string"},
                "project_id": {"type": "string"},
                "verdict": {
                    "type": "string",
                    "enum": ["correct", "incorrect", "needs_clarification"],
                },
                "candidate_id": {"type": "string"},
                "corrected_sql": {"type": "string"},
                "comment": {"type": "string"},
            },
        },
        "annotations": {"durable": True, "requiresApproval": False},
    },
)


def mcp_tools() -> list[dict[str, Any]]:
    return [dict(tool) for tool in TEXT2SQL_MCP_TOOLS]

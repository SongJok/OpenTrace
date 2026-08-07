"""
Analytics / code-interpreter style tools (ChatGPT Code Interpreter parity, best-effort).
"""

from __future__ import annotations

from plugins.chart.generator import run_chart_generator
from plugins.code.interpreter import run_code_interpreter
from plugins.data.analysis import run_data_analysis
from plugins.file.sandbox import run_file_sandbox
from tools.registry.registry import registry


@registry.tool(
    name="execute_sql_draft",
    description=(
        "执行已经向用户展示并由用户明确选择的持久化 SQL 草案候选。"
        "首次问数不得调用；只有用户明确指定候选 ID 或要求执行全部候选时才调用。"
        "执行前会重新校验权限、Schema 指纹、SQL 哈希和只读 AST，并进入持久审批。"
    ),
    tags=["执行草案", "确认执行", "候选ID"],
    parameters={
        "type": "object",
        "properties": {
            "draft_id": {"type": "string", "description": "已展示给用户的 SQL 草案 ID"},
            "candidate_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "用户明确选择的候选 ID；执行全部时可为空",
            },
            "execute_all": {
                "type": "boolean",
                "description": "仅当用户明确要求执行全部候选时设为 true",
            },
        },
        "required": ["draft_id", "candidate_ids", "execute_all"],
        "additionalProperties": False,
    },
    side_effect="write",
    max_retries=0,
    supports_parallel=False,
    timeout_seconds=60.0,
)
async def tool_execute_sql_draft(
    draft_id: str,
    candidate_ids: list[str] | None = None,
    execute_all: bool = False,
    user_id: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
    **_: object,
) -> dict:
    from infra.storage.database import AsyncSessionLocal
    from services.sql_assets import execute_sql_query_draft

    if not all((user_id, tenant_id, workspace_id)):
        raise PermissionError("trusted SQL draft execution scope is required")
    async with AsyncSessionLocal() as db:
        return await execute_sql_query_draft(
            db,
            draft_id=draft_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            candidate_ids=candidate_ids,
            execute_all=execute_all,
        )


@registry.tool(
    name="code_interpreter",
    description=(
        "Execute Python in a session sandbox (subprocess). Returns JSON: stdout, stderr, "
        "output_files, work_dir. Input: raw Python code, or JSON "
        '{"code":"...","packages":["numpy"]} . Packages are allowlist pip installs.'
    ),
    tags=[
        "python",
        "code",
        "run",
        "execute",
        "interpreter",
        "pip",
        "script",
        "数据分析",
        "计算",
    ],
    side_effect="write",
)
async def tool_code_interpreter(query: str = "", session_id: str = "", **_) -> str:
    return await run_code_interpreter(query, session_id)


@registry.tool(
    name="chart_generator",
    description=(
        "Generate charts from JSON spec; returns JSON with image_base64 (png) or html. "
        'Input JSON: {"chart_type":"line|bar|scatter|pie","data":{"x":[],"y":[]},'
        '"title":"","format":"png|html"} . Queries mentioning sin/正弦 get a demo chart.'
    ),
    tags=["chart", "plot", "graph", "matplotlib", "plotly", "可视化", "图表", "折线图", "柱状图"],
)
async def tool_chart_generator(query: str = "", **_) -> str:
    return await run_chart_generator(query)


@registry.tool(
    name="data_analysis",
    description=(
        "Pandas describe / groupby aggregate / dropna dedupe. "
        'Input JSON: {"operation":"describe|aggregate|clean","data":"<csv or records>",...}'
    ),
    tags=["pandas", "csv", "dataframe", "统计", "聚合", "清洗", "分析", "data"],
)
async def tool_data_analysis(query: str = "", **_) -> str:
    return await run_data_analysis(query)


@registry.tool(
    name="file_sandbox",
    description=(
        "Read/write/list/delete files under the session workspace. "
        'Input JSON: {"operation":"read|write|list|delete","path":"rel/path","content":"..."}'
    ),
    tags=["file", "read", "write", "sandbox", "workspace", "文件", "目录"],
    side_effect="write",
)
async def tool_file_sandbox(query: str = "", session_id: str = "", **_) -> str:
    return run_file_sandbox(query, session_id)

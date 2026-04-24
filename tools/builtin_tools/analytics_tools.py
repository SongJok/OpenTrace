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
)
async def tool_file_sandbox(query: str = "", session_id: str = "", **_) -> str:
    return run_file_sandbox(query, session_id)

"""企业数据库、知识、审批与主动预警主线的跨层合约。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_enterprise_database_types_reach_router_schema_and_frontend():
    databases = _source("gateway/api_gateway/routers/databases.py")
    router = _source("execution/data/db_router.py")
    selector = _source("frontend/src/components/DatabaseTypeSelect.tsx")
    for source_type in ("mysql", "clickhouse", "doris"):
        assert source_type in databases
        assert source_type in router
        assert source_type in selector.lower()

    database_page = _source("frontend/src/pages/DatabasesPage.tsx")
    assert "apiTestDatabaseConnection(token, id)" in database_page
    assert "apiSyncDatabaseSchema(token, id)" in database_page


def test_project_and_chat_share_one_data_source_scope():
    work_page = _source("frontend/src/pages/WorkPage.tsx")
    chat_page = _source("frontend/src/pages/ChatPage.tsx")
    chat_input = _source("frontend/src/components/ChatInput.tsx")
    responses = _source("gateway/api_gateway/routers/responses.py")
    runner = _source("kernel/agent_loop/runner.py")

    assert "projectDataSourceIds" in work_page
    assert "availableDataSources" in chat_page
    assert "data_source_ids: dataSourceId ? [dataSourceId] : []" in chat_input
    assert 'required_permission="query"' in responses
    assert "Project 未授权该数据源" in responses
    assert '"error": "project_data_source_not_authorized"' in runner


def test_data_agent_and_alert_scheduler_recheck_trusted_scope():
    data_agent = _source("agents/data_agent.py")
    data_agent_v2 = _source("agents/data_agent_v2/supervisor.py")
    scheduler = _source("infra/alerts/scheduler.py")

    assert "get_accessible_data_source" in data_agent
    assert "trusted data source scope is required" in data_agent
    assert "get_accessible_data_source" in data_agent_v2
    assert '"tenant_id": snapshot["tenant_id"]' in scheduler
    assert '"workspace_id": snapshot["workspace_id"]' in scheduler


def test_project_context_instructs_combined_data_and_knowledge_grounding():
    context = _source("kernel/agent_loop/context.py")
    runner = _source("kernel/agent_loop/runner.py")

    assert "Project 企业上下文" in context
    assert "同时调用 data 与 rag" in context
    assert "Schema=" in context
    assert "_prefetch_knowledge_grounding" in runner


def test_alert_creation_remains_a_durable_approval_side_effect():
    tools = _source("tools/builtin_tools/platform_tools.py")
    runner = _source("kernel/agent_loop/runner.py")

    assert 'name="create_data_alert"' in tools
    assert 'side_effect="write"' in tools
    assert "ResponseApproval" in runner

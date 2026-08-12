import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents.bootstrap import register_builtin_agents
from kernel.agent_loop.contracts import ExecutionPlan, IntentPlan, PlanningDecision, SideEffect
from kernel.agent_loop.runner import AgentLoop
from kernel.agent_loop.write_intent import (
    is_explicit_write_request,
    is_sql_draft_execution_request,
)

ROOT = Path(__file__).resolve().parents[1]


class KernelFlowContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_unified_agent_loop_has_bounded_rounds_and_approvals(self):
        txt = self._read("kernel/agent_loop/runner.py")
        self.assertIn("max_rounds: int = 8", txt)
        self.assertIn('response.status = "requires_action"', txt)
        self.assertIn("_restore_tool_history", txt)

    def test_meta_cognition_has_should_retry(self):
        txt = self._read("kernel/meta_cognition/meta_cognition.py")
        self.assertIn("async def should_retry", txt)
        self.assertIn("retry_count", txt)
        self.assertIn("max_retries", txt)

    def test_policy_has_concrete_rules(self):
        txt = self._read("kernel/policy/engine.py")
        self.assertIn("今天", txt)
        self.assertIn("latest", txt)
        self.assertIn("新闻", txt)
        self.assertIn("max(doc_scores) < 0.7", txt)
        self.assertIn("tool_calls", txt)

    def test_response_resume_uses_persisted_cursor_and_worker_checkpoint(self):
        txt = self._read("gateway/api_gateway/routers/responses.py")
        self.assertIn("starting_after: int = -1", txt)
        self.assertIn("ResponseEvent.sequence_number > cursor", txt)
        worker = self._read("infra/responses/worker.py")
        self.assertIn("claim_response", worker)
        self.assertIn("lease_owner", worker)

    def test_reasoning_yaml_has_numeric_constraints(self):
        txt = self._read("kernel/prompt_engine/reasoning.yaml")
        self.assertIn("300", txt)
        self.assertIn("[doc:文件名]", txt)
        self.assertIn("根据现有信息无法回答", txt)
        self.assertIn("code_interpreter", txt)
        self.assertIn("chart_generator", txt)
        self.assertIn("OpenTrace", txt)

    def test_orchestrator_wires_analytics_tools(self):
        txt = self._read("tools/builtin_tools/analytics_tools.py")
        self.assertIn('name="code_interpreter"', txt)
        self.assertIn('name="chart_generator"', txt)
        self.assertIn("data_analysis", txt)

    def test_manager_owns_final_response(self):
        txt = self._read("kernel/agent_loop/runner.py")
        self.assertIn("AgentLoopResult", txt)
        self.assertIn("model_response.content", txt)

    def test_explicit_knowledge_grounding_is_deterministically_prefetched(self):
        self.assertTrue(AgentLoop._requires_knowledge_grounding("请根据已发布知识库回答这个问题"))
        self.assertTrue(AgentLoop._requires_knowledge_grounding("请从上传的文档中查找答案"))
        self.assertFalse(AgentLoop._requires_knowledge_grounding("请解释什么是知识库"))

        txt = self._read("kernel/agent_loop/runner.py")
        self.assertIn("_prefetch_knowledge_grounding", txt)
        self.assertIn('and "rag" in spec_by_name', txt)

    def test_responses_agent_catalogue_obeys_runtime_flags(self):
        register_builtin_agents(force=True)
        with patch("infra.config.settings.settings.kernel_agent_rag_enabled", False):
            names = {spec.name for spec in AgentLoop._available_tool_specs({})}
        self.assertNotIn("rag", names)
        self.assertIn("data", names)

        with patch("infra.config.settings.settings.kernel_agent_enabled", False):
            names = {spec.name for spec in AgentLoop._available_tool_specs({})}
        self.assertTrue({"data", "rag"}.isdisjoint(names))

    def test_responses_exposes_only_governed_data_execution_write_tool(self):
        register_builtin_agents(force=True)
        specs = {spec.name: spec for spec in AgentLoop._available_tool_specs({})}
        self.assertIn("execute_sql_draft", specs)
        self.assertEqual(specs["execute_sql_draft"].side_effect, SideEffect.WRITE)
        self.assertEqual(specs["execute_sql_draft"].max_retries, 0)
        self.assertTrue({"code_interpreter", "file_sandbox", "data_analysis"}.isdisjoint(specs))

    def test_sql_draft_selection_is_bound_to_the_pending_draft(self):
        draft = {
            "draft_id": "draft-1",
            "group_type": "alternative",
            "candidates": [
                {"id": "candidate-a", "position": 1, "execution_status": "pending"},
                {"id": "candidate-b", "position": 2, "execution_status": "pending"},
            ],
        }
        selected = AgentLoop._resolve_sql_draft_execution_request("执行第二个候选", draft)
        assert selected == {
            "status": "ready",
            "draft_id": "draft-1",
            "arguments": {
                "draft_id": "draft-1",
                "candidate_ids": ["candidate-b"],
                "execute_all": False,
                "retry_failed": False,
            },
        }
        ambiguous = AgentLoop._resolve_sql_draft_execution_request("执行", draft)
        assert ambiguous is not None and ambiguous["status"] == "clarify"
        assert "candidate-a" in ambiguous["question"]
        assert AgentLoop._resolve_sql_draft_execution_request("解释第二个候选", draft) is None
        assert AgentLoop._resolve_sql_draft_execution_request("就执行第一个吧", draft)["arguments"][
            "candidate_ids"
        ] == ["candidate-a"]
        execute_all = AgentLoop._resolve_sql_draft_execution_request("执行全部候选", draft)
        assert execute_all is not None and execute_all["status"] == "clarify"

    def test_pending_sql_draft_policy_only_allows_governed_execution(self):
        decision = PlanningDecision(
            intent=IntentPlan(goal="执行查询", capabilities=("data", "rag")),
            execution_plan=ExecutionPlan(goal="执行查询"),
        )
        governed = AgentLoop._apply_pending_sql_draft_policy(
            decision,
            {
                "status": "ready",
                "arguments": {
                    "draft_id": "draft-1",
                    "candidate_ids": ["candidate-a"],
                    "execute_all": False,
                    "retry_failed": False,
                },
            },
        )
        self.assertEqual(governed.intent.capabilities, ("execute_sql_draft",))
        self.assertEqual(governed.intent.risk, SideEffect.WRITE)
        self.assertEqual(governed.execution_plan.steps[0].capability, "execute_sql_draft")
        self.assertTrue(is_explicit_write_request("执行候选 1"))
        self.assertTrue(is_sql_draft_execution_request("采用第二个方案"))
        self.assertTrue(is_sql_draft_execution_request("确认执行"))
        self.assertFalse(is_sql_draft_execution_request("解释第二个方案"))
        self.assertFalse(is_sql_draft_execution_request("继续分析指标定义"))

    def test_verified_data_answer_projection_keeps_citations_and_learning(self):
        projected = AgentLoop._data_answer_projection(
            "execute_sql_draft",
            {
                "status": "completed",
                "result": {
                    "execution_summary": {
                        "data_agent_run_id": "run-1",
                        "state": "completed",
                        "answer": "付费用户为 12 [R1] [E1]",
                        "answer_citations": [{"label": "R1"}, {"label": "E1"}],
                        "learning": {"status": "observed"},
                        "preflight": {"status": "pass"},
                        "result_validation": {"status": "pass"},
                    }
                },
            },
        )
        self.assertEqual(projected["answer"], "付费用户为 12 [R1] [E1]")
        self.assertEqual([item["label"] for item in projected["answer_citations"]], ["R1", "E1"])
        self.assertEqual(projected["learning"]["status"], "observed")

    def test_approval_restore_keeps_governed_sql_timeout_and_no_retry(self):
        approval = SimpleNamespace(
            call_id="call-1",
            tool_name="execute_sql_draft",
            arguments={
                "draft_id": "draft-1",
                "candidate_ids": ["candidate-1"],
                "execute_all": False,
                "retry_failed": False,
            },
            status="approved",
            side_effect_level="write",
            reason=None,
        )

        class Rows:
            @staticmethod
            def scalars():
                return SimpleNamespace(all=lambda: [approval])

        db = SimpleNamespace(
            execute=AsyncMock(return_value=Rows()),
            scalar=AsyncMock(return_value=None),
        )
        loop = AgentLoop()
        captured = {}

        async def execute_tool(_db, *, response, call, spec, emit):
            captured["spec"] = spec
            return {"status": "completed"}

        loop._execute_tool = execute_tool
        restored = asyncio.run(
            loop._restore_tool_history(
                db,
                response=SimpleNamespace(id="response-1"),
                messages=[],
                emit=AsyncMock(),
            )
        )

        self.assertEqual(restored, [("execute_sql_draft", {"status": "completed"})])
        self.assertEqual(captured["spec"].max_retries, 0)
        self.assertEqual(captured["spec"].timeout_seconds, 60.0)
        self.assertEqual(captured["spec"].side_effect, SideEffect.WRITE)

    def test_analytics_tools_registered_module_importable(self):
        txt = self._read("tools/builtin_tools/analytics_tools.py")
        self.assertIn('name="code_interpreter"', txt)
        self.assertIn('name="chart_generator"', txt)

    def test_sandbox_download_route_registered(self):
        txt = self._read("gateway/api_gateway/main.py")
        self.assertIn("sandbox.router", txt)
        txt2 = self._read("gateway/api_gateway/routers/sandbox.py")
        self.assertIn("/sandbox/download", txt2)
        self.assertIn("Session not found or no permission", txt2)

    def test_cognitive_kernel_run_and_stream_use_orchestrator(self):
        txt = self._read("kernel/cognitive_kernel.py")
        self.assertIn("get_runtime_gateway", txt)
        self.assertIn("runtime_gateway", txt)

    def test_identity_layer_is_wired_across_gateway_and_kernel(self):
        identity_txt = self._read("kernel/identity/system_identity.py")
        gateway_txt = self._read("model/model_gateway/gateway.py")
        kernel_txt = self._read("kernel/cognitive_kernel.py")
        self.assertIn("SYSTEM_IDENTITY", identity_txt)
        self.assertIn("CANONICAL_IDENTITY_RESPONSE", identity_txt)
        self.assertIn("merge_system_identity", gateway_txt)
        self.assertIn("_post_process_identity_response", gateway_txt)
        self.assertIn("get_cached_identity_answer", kernel_txt)

    def test_step_observability_metrics_and_span_present(self):
        metrics_txt = self._read("infra/observability/metrics.py")
        self.assertIn("KERNEL_STEP_TOTAL", metrics_txt)
        self.assertIn("opentrace_kernel_step_total", metrics_txt)
        self.assertIn("step_type", metrics_txt)

    def test_redis_db_indices_are_safe_and_have_runtime_guard(self):
        settings_txt = self._read("infra/config/settings.py")
        redis_txt = self._read("infra/cache/redis_client.py")
        self.assertIn("redis_session_db: int = 10", settings_txt)
        self.assertIn("redis_pubsub_db: int = 15", settings_txt)
        self.assertIn("_normalize_db_index", redis_txt)
        self.assertIn('config_get("databases")', redis_txt)


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from unittest.mock import patch

from agents.bootstrap import register_builtin_agents
from kernel.agent_loop.runner import AgentLoop

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
        self.assertIn('starting_after: int = -1', txt)
        self.assertIn('ResponseEvent.sequence_number > cursor', txt)
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
        self.assertTrue({"data", "rag", "web_intelligence", "skills", "rules"}.isdisjoint(names))
        self.assertIn("calculator", names)

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
        self.assertIn("config_get(\"databases\")", redis_txt)


if __name__ == "__main__":
    unittest.main()

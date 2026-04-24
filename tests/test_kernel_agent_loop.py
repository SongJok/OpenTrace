import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class KernelFlowContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_orchestrator_has_step_loop_and_resume(self):
        txt = self._read("kernel/orchestrator.py")
        self.assertIn("while not self._is_complete(state)", txt)
        self.assertIn("StepType.REASON", txt)
        self.assertIn("StepType.DECIDE", txt)
        self.assertIn("StepType.EXECUTE", txt)
        self.assertIn("StepType.OBSERVE", txt)
        self.assertIn("StepType.REFLECT", txt)
        self.assertIn("async def resume(self, session_id: str, step_index: int)", txt)
        self.assertIn("kernel:state:", txt)

    def test_orchestrator_enforces_tool_observe_interleave(self):
        txt = self._read("kernel/orchestrator.py")
        # 每轮只执行一个工具，其余 pending，确保 execute->observe 交替
        self.assertIn("pending_tool_calls", txt)
        self.assertIn("calls = calls[:1]", txt)
        self.assertIn("if t == StepType.EXECUTE", txt)

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

    def test_chat_resume_endpoint_and_session_guard(self):
        txt = self._read("gateway/api_gateway/routers/chat.py")
        self.assertIn("@router.post(\"/chat/resume\"", txt)
        self.assertIn("Session not found or no permission", txt)
        self.assertRegex(txt, r"orchestrator\.resume\(session_id=session_id, step_index=req\.step_index\)")

    def test_reasoning_yaml_has_numeric_constraints(self):
        txt = self._read("kernel/prompt_engine/reasoning.yaml")
        self.assertIn("300", txt)
        self.assertIn("[doc:文件名]", txt)
        self.assertIn("根据现有信息无法回答", txt)
        self.assertIn("code_interpreter", txt)
        self.assertIn("chart_generator", txt)
        self.assertIn("OpenTrace", txt)

    def test_orchestrator_wires_analytics_tools(self):
        txt = self._read("kernel/orchestrator.py")
        self.assertIn("chart_generator", txt)
        self.assertIn("code_interpreter", txt)
        self.assertIn("data_analysis", txt)
        self.assertIn("file_sandbox", txt)
        self.assertIn("_inject_tool_artifacts", txt)

    def test_orchestrator_has_non_empty_final_response_fallback(self):
        txt = self._read("kernel/orchestrator.py")
        self.assertIn('candidate = str(state.context.get("final_answer", "")).strip()', txt)
        self.assertIn('if candidate:', txt)
        self.assertIn('我暂时无法基于当前上下文给出可靠答案', txt)

    def test_reflect_stage_allows_observation_based_answer(self):
        txt = self._read("kernel/orchestrator.py")
        self.assertIn('if not artifacts.strip() and state.context.get("last_observation"):', txt)
        self.assertIn('validation.score >= 0.45', txt)

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
        self.assertIn("CognitiveOrchestrator", txt)
        self.assertRegex(txt, r"resp = await orchestrator\.process\(")
        self.assertIn("SSE 路径同样走 Step-based Orchestrator", txt)

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
        orchestrator_txt = self._read("kernel/orchestrator.py")
        metrics_txt = self._read("infra/observability/metrics.py")
        self.assertIn("kernel.step.", orchestrator_txt)
        self.assertIn("KERNEL_STEP_TOTAL", orchestrator_txt)
        self.assertIn("opentrace_kernel_step_total", metrics_txt)

    def test_redis_db_indices_are_safe_and_have_runtime_guard(self):
        settings_txt = self._read("infra/config/settings.py")
        redis_txt = self._read("infra/cache/redis_client.py")
        self.assertIn("redis_session_db: int = 10", settings_txt)
        self.assertIn("redis_pubsub_db: int = 15", settings_txt)
        self.assertIn("_normalize_db_index", redis_txt)
        self.assertIn("config_get(\"databases\")", redis_txt)


if __name__ == "__main__":
    unittest.main()

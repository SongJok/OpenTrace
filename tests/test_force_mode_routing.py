"""Tests for force_mode routing — user-selected agent routing bypasses PlanAgent."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch


class ForceModeRoutingTests(unittest.TestCase):
    def test_v4_force_mode_rag_creates_rag_subtask(self):
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        async def _run():
            orch = CognitiveOrchestratorV4()
            captured_plan = None

            async def fake_dispatch(plan, event_cb=None):
                nonlocal captured_plan
                captured_plan = plan
                return []

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="帮我查文档",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "rag"},
                )
                await orch.process(req)

            asyncio.run(_run())

    def test_v4_force_mode_data_creates_data_subtask(self):
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        async def _run():
            orch = CognitiveOrchestratorV4()
            captured_plan = None

            async def fake_dispatch(plan, event_cb=None):
                nonlocal captured_plan
                captured_plan = plan
                return []

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="查订单",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "data_query", "data_source_id": "ds1"},
                )
                await orch.process(req)

            asyncio.run(_run())

    def test_v4_no_force_mode_uses_plan_agent(self):
        """Without force_mode, PlanAgent.generate_plan should be called."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        async def _run():
            orch = CognitiveOrchestratorV4()
            plan_called = False

            original_generate = orch.plan_agent.generate_plan

            async def fake_generate(*args, **kwargs):
                nonlocal plan_called
                plan_called = True
                return await original_generate(*args, **kwargs)

            with patch.object(orch.plan_agent, 'generate_plan', side_effect=fake_generate), \
                 patch.object(orch.dispatcher, 'dispatch', return_value=[]), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="你好",
                    session_id="s1",
                    user_id="u1",
                    metadata={},
                )
                await orch.process(req)
                self.assertTrue(plan_called, "PlanAgent.generate_plan should be called when force_mode is not set")

            asyncio.run(_run())

    def test_chat_request_accepts_force_mode(self):
        from gateway.api_gateway.routers.chat import ChatRequest

        # Valid force_mode values
        for mode in ["rag", "data_query", "data_analysis", "anomaly_tracking"]:
            req = ChatRequest(query="test", force_mode=mode)
            self.assertEqual(req.force_mode, mode)

        # Default is None
        req = ChatRequest(query="test")
        self.assertIsNone(req.force_mode)

    def test_v4_force_mode_anomaly_tracking_routes_to_skills(self):
        """anomaly_tracking should route to agent_type='skills', not 'tool'."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        async def _run():
            orch = CognitiveOrchestratorV4()
            captured_plan = None

            async def fake_dispatch(plan, event_cb=None):
                nonlocal captured_plan
                captured_plan = plan
                return []

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="追踪异常",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "anomaly_tracking"},
                )
                await orch.process(req)
                self.assertIsNotNone(captured_plan)
                self.assertEqual(len(captured_plan.subtasks), 1)
                self.assertEqual(captured_plan.subtasks[0].agent_type, "skills")
                self.assertTrue(captured_plan.subtasks[0].params.get("enabled_skills"))

            asyncio.run(_run())

    def test_v4_force_mode_response_metadata_includes_force_mode(self):
        """The response metadata should include the force_mode value."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        captured_resp = None

        async def _run():
            nonlocal captured_resp
            orch = CognitiveOrchestratorV4()

            async def fake_dispatch(plan, event_cb=None):
                return []

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="查文档",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "rag"},
                )
                captured_resp = await orch.process(req)

        asyncio.run(_run())
        self.assertEqual(captured_resp.metadata.get("force_mode"), "rag")

    def test_v4_force_mode_skips_auto_inject_rag(self):
        """When force_mode is set, auto-inject RAG subtask should be skipped."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        async def _run():
            orch = CognitiveOrchestratorV4()
            captured_plan = None

            async def fake_dispatch(plan, event_cb=None):
                nonlocal captured_plan
                captured_plan = plan
                # Return a non-rag result so auto-inject would trigger if not guarded
                return []

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                # Query has doc intent but force_mode=data_query should not inject rag
                req = OrchestratorV4Request(
                    query="根据文档查询数据",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "data_query", "data_source_id": "ds1"},
                )
                await orch.process(req)
                # Should only have 1 subtask (data), no auto-injected rag
                rag_count = sum(1 for s in captured_plan.subtasks if s.agent_type == "rag")
                self.assertEqual(rag_count, 0, "Auto-inject RAG should be skipped when force_mode is set")

            asyncio.run(_run())

    def test_stream_emits_force_mode_event(self):
        """Streaming path should emit a force_mode event."""
        from kernel.cognitive_kernel import CognitiveKernel, KernelRequest

        async def _run():
            kernel = CognitiveKernel()
            events = []

            # Mock the orchestrator to return a response with force_mode in metadata
            mock_resp = Mock()
            mock_resp.content = "test answer"
            mock_resp.route = "agent_cluster"
            mock_resp.strategy = "parallel"
            mock_resp.passed_validation = True
            mock_resp.validation_score = 0.9
            mock_resp.hallucination_risk = 0.0
            mock_resp.intent_category = "rag"
            mock_resp.metadata = {
                "force_mode": "rag",
                "adaptive_profile": {"name": "balanced"},
                "plan": {"subtasks": []},
                "agent_results": [],
                "annotations": [],
                "execution_graph": None,
                "answer_draft": "",
                "phases": [],
            }

            with patch.object(kernel, '_classify_intent_domain', return_value=Mock(value="qa")):
                from kernel.cognition.self_model import IntrospectionAssessment
                from kernel.cognition.types import CapabilityLevel
                mock_assessment = Mock(level=CapabilityLevel.AVAILABLE, reasoning="", fallback_strategy="")
                with patch.object(kernel.self_model, 'introspect', return_value=mock_assessment), \
                     patch.object(kernel.self_model, 'get_identity_prompt', return_value=""), \
                     patch('kernel.cognitive_kernel.CognitiveOrchestratorV4') as MockOrch:
                    mock_orch = Mock()
                    mock_orch.process = AsyncMock(return_value=mock_resp)
                    MockOrch.return_value = mock_orch

                    req = KernelRequest(
                        query="查文档",
                        session_id="s1",
                        user_id="u1",
                        stream=True,
                        metadata={"force_mode": "rag"},
                    )
                    async for event in kernel.stream(req):
                        events.append(event)

            asyncio.run(_run())
            force_mode_events = [e for e in events if e.get("type") == "force_mode"]
            self.assertEqual(len(force_mode_events), 1)
            self.assertEqual(force_mode_events[0]["data"]["mode"], "rag")


class SkillsAgentTests(unittest.TestCase):
    def test_skills_agent_returns_fallback_when_no_skills(self):
        """When no skills are installed, SkillsAgent returns a fallback message."""
        from agents.skills_agent import SkillsAgent
        from agents.base import TaskMessage

        async def _run():
            agent = SkillsAgent()
            with patch('agents.skills_agent.marketplace') as mock_mp:
                mock_mp.list_installed.return_value = []
                msg = TaskMessage(
                    task_id="t1",
                    agent_type="skills",
                    query="追踪异常",
                    params={},
                    session_id="s1",
                    user_id="u1",
                )
                result = await agent.execute(msg)
                self.assertEqual(result.status, "success")
                self.assertIn("0", result.content)  # "已尝试 0 个已安装技能"

            asyncio.run(_run())

    def test_skills_agent_respects_enabled_skills(self):
        """SkillsAgent should only execute skills in the enabled_skills whitelist."""
        from agents.skills_agent import SkillsAgent
        from agents.base import TaskMessage

        async def _run():
            agent = SkillsAgent()
            with patch('agents.skills_agent.marketplace') as mock_mp:
                skill_a = Mock(skill_id="a@1", name="SkillA", description="", skill_type="generic")
                skill_b = Mock(skill_id="b@1", name="SkillB", description="", skill_type="generic")
                mock_mp.list_installed.return_value = [skill_a, skill_b]
                mock_mp.test_skill.return_value = {"success": True, "output": "ok"}

                msg = TaskMessage(
                    task_id="t1",
                    agent_type="skills",
                    query="test",
                    params={"enabled_skills": ["b@1"]},
                    session_id="s1",
                    user_id="u1",
                )
                result = await agent.execute(msg)
                # Only skill_b should be tested
                calls = [c[0] for c in mock_mp.test_skill.call_args_list]
                called_ids = [c[0] for c in calls]
                self.assertIn("b@1", called_ids)
                self.assertNotIn("a@1", called_ids)

            asyncio.run(_run())

    def test_skills_agent_empty_enabled_skills_returns_message(self):
        """When enabled_skills whitelist contains no installed skills, return a message."""
        from agents.skills_agent import SkillsAgent
        from agents.base import TaskMessage

        async def _run():
            agent = SkillsAgent()
            with patch('agents.skills_agent.marketplace') as mock_mp:
                skill_a = Mock(skill_id="a@1", name="SkillA", description="", skill_type="generic")
                mock_mp.list_installed.return_value = [skill_a]

                msg = TaskMessage(
                    task_id="t1",
                    agent_type="skills",
                    query="test",
                    params={"enabled_skills": ["z@1"]},
                    session_id="s1",
                    user_id="u1",
                )
                result = await agent.execute(msg)
                self.assertEqual(result.status, "success")
                self.assertIn("均未安装", result.content)
                self.assertEqual(result.metadata.get("installed_count"), 0)

            asyncio.run(_run())

    def test_skills_agent_skill_type_prioritization(self):
        """Skills with matching skill_type should score higher for anomaly_tracking mode."""
        from agents.skills_agent import _score_match

        generic_skill = Mock()
        generic_skill.name = "general"
        generic_skill.description = "helps with stuff"
        generic_skill.skill_type = "generic"

        anomaly_skill = Mock()
        anomaly_skill.name = "track"
        anomaly_skill.description = "tracks anomalies"
        anomaly_skill.skill_type = "anomaly_tracking"

        generic_score = _score_match(generic_skill, "追踪异常", "anomaly_tracking")
        anomaly_score = _score_match(anomaly_skill, "追踪异常", "anomaly_tracking")

        self.assertGreater(anomaly_score, generic_score)


class DispatcherSupervisorTests(unittest.TestCase):
    def test_supervisor_rejects_empty_skill_result(self):
        """Supervisor should reject a skills result with no matched skills when skills were installed."""
        from kernel.dispatcher import RuntimeSupervisor
        from agents.base import AgentResult

        sup = RuntimeSupervisor(enabled=True)

        # Installed skills but no match
        result = AgentResult(
            task_id="t1",
            agent_type="skills",
            status="success",
            content="已尝试 3 个已安装技能，但未找到完全匹配的结果。",
            confidence=0.4,
            metadata={"matched_skills": 0, "installed_count": 3},
        )
        ok, reason = sup.check(result)
        self.assertFalse(ok)
        self.assertEqual(reason, "skills_no_match")

    def test_supervisor_rejects_short_skill_content(self):
        """Supervisor should reject very short skills content."""
        from kernel.dispatcher import RuntimeSupervisor
        from agents.base import AgentResult

        sup = RuntimeSupervisor(enabled=True)

        result = AgentResult(
            task_id="t1",
            agent_type="skills",
            status="success",
            content="短",
            confidence=0.7,
            metadata={"matched_skills": 1, "installed_count": 3},
        )
        ok, reason = sup.check(result)
        self.assertFalse(ok)
        self.assertEqual(reason, "skills_content_too_short")

    def test_supervisor_accepts_good_skill_result(self):
        """Supervisor should accept a good skills result."""
        from kernel.dispatcher import RuntimeSupervisor
        from agents.base import AgentResult

        sup = RuntimeSupervisor(enabled=True)

        result = AgentResult(
            task_id="t1",
            agent_type="skills",
            status="success",
            content="异常追踪结果：发现 3 个异常事件",
            confidence=0.8,
            metadata={"matched_skills": 1, "installed_count": 5},
        )
        ok, reason = sup.check(result)
        self.assertTrue(ok)


class ForceModeEdgeCaseTests(unittest.TestCase):
    def test_invalid_force_mode_is_ignored(self):
        """An unknown force_mode value should be ignored and fall back to PlanAgent."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request, VALID_FORCE_MODES

        self.assertNotIn("unknown", VALID_FORCE_MODES)

        async def _run():
            orch = CognitiveOrchestratorV4()
            plan_called = False

            original_generate = orch.plan_agent.generate_plan

            async def fake_generate(*args, **kwargs):
                nonlocal plan_called
                plan_called = True
                return await original_generate(*args, **kwargs)

            with patch.object(orch.plan_agent, 'generate_plan', side_effect=fake_generate), \
                 patch.object(orch.dispatcher, 'dispatch', return_value=[]), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="你好",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "unknown"},
                )
                await orch.process(req)
                self.assertTrue(plan_called, "PlanAgent should be called when force_mode is invalid")

            asyncio.run(_run())

    def test_skills_async_timeout_does_not_block(self):
        """A timing-out skill should not prevent other skills from executing."""
        from agents.skills_agent import SkillsAgent
        from agents.base import TaskMessage

        async def _run():
            agent = SkillsAgent()

            def slow_test(*_args):
                import time
                time.sleep(30)

            def fast_test(skill_id, _input):
                if skill_id == "fast@1":
                    return {"success": True, "output": "fast result"}
                return {"success": False, "error": "not found"}

            with patch('agents.skills_agent.marketplace') as mock_mp:
                slow_skill = Mock(skill_id="slow@1", name="SlowSkill", description="slow", skill_type="generic")
                fast_skill = Mock(skill_id="fast@1", name="FastSkill", description="fast", skill_type="generic")
                mock_mp.list_installed.return_value = [slow_skill, fast_skill]
                mock_mp.test_skill.side_effect = fast_test

                msg = TaskMessage(
                    task_id="t1",
                    agent_type="skills",
                    query="fast",
                    params={},
                    session_id="s1",
                    user_id="u1",
                )
                result = await agent.execute(msg)
                # Fast skill should still succeed
                self.assertEqual(result.status, "success")
                self.assertGreater(result.confidence, 0.5)

            asyncio.run(_run())

    def test_force_mode_data_analysis_routes_to_data_agent(self):
        """data_analysis force_mode should route to agent_type='data'."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        async def _run():
            orch = CognitiveOrchestratorV4()
            captured_plan = None

            async def fake_dispatch(plan, event_cb=None):
                nonlocal captured_plan
                captured_plan = plan
                return []

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.9, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(text="OK")):
                req = OrchestratorV4Request(
                    query="分析数据",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "data_analysis", "data_source_id": "ds1"},
                )
                await orch.process(req)
                self.assertEqual(captured_plan.subtasks[0].agent_type, "data")

            asyncio.run(_run())

    def test_rag_force_mode_no_docs_no_document_toolresult(self):
        """When force_mode='rag' and no documents found, no document source ToolResult should be created."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request
        from agents.base import AgentResult

        captured_tool_results = None

        async def _run():
            nonlocal captured_tool_results
            orch = CognitiveOrchestratorV4()

            async def fake_dispatch(plan, event_cb=None):
                return [AgentResult(
                    task_id="t1", agent_type="rag", status="success",
                    content="未检索到相关内容。", confidence=0.3,
                    metadata={"chunks": [], "citations": [], "llmwiki_entries": [], "vector_chunks": []},
                )]

            # Intercept fusion_engine.run to capture the tool_results that were constructed
            original_run = orch.fusion_engine.run

            def capture_fusion(fusion_input, **kwargs):
                nonlocal captured_tool_results
                captured_tool_results = fusion_input.results
                return Mock(confidence=0.5, merged_context="test", conflicts=[], alternate_contexts=[], evidence_map=[])

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch.fusion_engine, 'run', side_effect=capture_fusion), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(spec=['text', 'fragments', 'to_text'], text="OK", fragments=[], to_text=Mock(return_value="OK"))):
                req = OrchestratorV4Request(
                    query="什么是队长",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "rag"},
                )
                await orch.process(req)

        asyncio.run(_run())
        # No document ToolResult should be created when RAG finds zero chunks
        doc_sources = [r.source for r in captured_tool_results if getattr(r, "source", None) in {"document", "llmwiki"}]
        self.assertEqual(len(doc_sources), 0, f"Expected no document ToolResults when RAG returns zero chunks, but got: {doc_sources}")

    def test_rag_force_mode_no_docs_returns_explicit_message(self):
        """When force_mode='rag' and no documents found, the answer path should skip _llm_grounded_answer."""
        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request
        from agents.base import AgentResult

        grounded_answer_called = False

        async def _run():
            nonlocal grounded_answer_called
            orch = CognitiveOrchestratorV4()

            async def fake_dispatch(plan, event_cb=None):
                return [AgentResult(
                    task_id="t1", agent_type="rag", status="success",
                    content="未检索到相关内容。", confidence=0.3,
                    metadata={"chunks": [], "citations": [], "llmwiki_entries": [], "vector_chunks": []},
                )]

            original_method = orch._llm_grounded_answer

            async def fake_grounded(*args, **kwargs):
                nonlocal grounded_answer_called
                grounded_answer_called = True
                return await original_method(*args, **kwargs)

            with patch.object(orch.dispatcher, 'dispatch', side_effect=fake_dispatch), \
                 patch.object(orch, '_llm_grounded_answer', side_effect=fake_grounded), \
                 patch.object(orch.fusion_engine, 'run', return_value=Mock(confidence=0.5, merged_context="未在知识库中找到相关内容", conflicts=[], alternate_contexts=[], evidence_map=[])), \
                 patch.object(orch.critic_engine, 'run', return_value=Mock(need_fix=False, feedback="")), \
                 patch.object(orch.annotator, 'annotate_agent_result', side_effect=lambda **kw: Mock(text="", annotation=Mock(level=Mock(name="INFO"), source_type=Mock(value=""), confidence=1.0, caveats=[], citations=[]))), \
                 patch.object(orch.annotator, 'merge_responses', return_value=Mock(fragments=[])), \
                 patch.object(orch.validator, 'validate_raw_output', return_value=(True, [], Mock(to_text=lambda: "OK", fragments=[]))), \
                 patch.object(orch.annotator, 'annotate_model_response', return_value=Mock(spec=['text', 'fragments', 'to_text'], text="OK", fragments=[], to_text=Mock(return_value="OK"))):
                req = OrchestratorV4Request(
                    query="什么是队长",
                    session_id="s1",
                    user_id="u1",
                    metadata={"force_mode": "rag"},
                )
                await orch.process(req)

        asyncio.run(_run())
        # _llm_grounded_answer should NOT be called when RAG finds zero chunks
        self.assertFalse(grounded_answer_called, "_llm_grounded_answer should not be called when RAG returns zero chunks")


if __name__ == "__main__":
    unittest.main()

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_durable_path_has_named_trace_boundaries():
    worker = (ROOT / "infra" / "responses" / "worker.py").read_text(encoding="utf-8")
    runner = (ROOT / "kernel" / "agent_loop" / "runner.py").read_text(encoding="utf-8")
    context = (ROOT / "kernel" / "agent_loop" / "context.py").read_text(encoding="utf-8")
    model = (ROOT / "model" / "model_gateway" / "gateway.py").read_text(encoding="utf-8")
    assert 'start_as_current_span("response.agent_loop")' in worker
    assert '@traced_async("agent_loop.run")' in runner
    assert '@traced_async("agent_loop.tool_execute")' in runner
    assert '@traced_async("agent_loop.context_assemble")' in context
    assert 'start_as_current_span("model_gateway.complete")' in model

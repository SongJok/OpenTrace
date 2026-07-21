from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uploaded_attachment_is_direct_context_not_sandbox_file() -> None:
    context_source = (ROOT / "kernel/agent_loop/context.py").read_text(encoding="utf-8")
    runner_source = (ROOT / "kernel/agent_loop/runner.py").read_text(encoding="utf-8")

    assert "应直接根据这些内容回答" in context_source
    assert "不要调用 file_sandbox" in context_source
    assert "不要选择 file_sandbox 等文件工具重新读取" in runner_source

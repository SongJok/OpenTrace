"""Contract tests for the v2 Responses compatibility surface."""

from gateway.api_gateway.routers.responses import extract_user_input, translate_legacy_event


def test_extract_user_input_prefers_last_user_item() -> None:
    assert extract_user_input([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": " latest "},
    ]) == "latest"


def test_legacy_final_answer_becomes_item_then_terminal_event() -> None:
    translated = translate_legacy_event({"type": "final_answer", "data": {"content": "ok"}})
    assert translated == [
        ("response.output_item.done", {"item_type": "message", "role": "assistant", "content": "ok"}),
        ("response.completed", {"status": "completed", "content": "ok"}),
    ]


def test_legacy_reasoning_is_exposed_only_as_progress_summary() -> None:
    translated = translate_legacy_event({"type": "reasoning_step", "data": {"stage": "ROUTE"}})
    assert translated == [("response.progress", {"stage": "ROUTE"})]

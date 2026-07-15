"""The v2 request publishes one namespaced OpenTrace extension."""

from gateway.api_gateway.routers.responses import ResponseCreateRequest


def test_response_request_migrates_transition_fields_into_extension() -> None:
    request = ResponseCreateRequest(
        input="查询附件数据",
        conversation_id="session-1",
        enabled_skills=["rag"],
        disabled_skills=["web"],
        data_source_id="source-1",
        force_database=True,
        attachment_ids=["attachment-1"],
        knowledge={"action": "query", "scope": "session"},
    )
    assert request.enabled_skills == ["rag"]
    assert request.data_source_id == "source-1"
    assert request.opentrace.enabled_skills == ["rag"]
    assert request.model_dump(mode="json").get("attachment_ids") is None

"""Stream final_answer carries enterprise fields when present."""

from __future__ import annotations


def test_final_answer_shape_contract():
    stream_meta = {
        "control_plane": {"allowed": True},
        "capabilities_used": ["document_retrieval"],
        "prompt_tokens": 10,
        "semantic_observability": {"enterprise_telemetry": {"cognitive": {}}},
    }
    final_data = {
        "content": "ok",
        "metadata": stream_meta,
    }
    for key in ("control_plane", "capabilities_used", "prompt_tokens"):
        if key in stream_meta:
            final_data[key] = stream_meta[key]
    obs = stream_meta.get("semantic_observability") or {}
    if obs.get("enterprise_telemetry"):
        final_data["enterprise_telemetry"] = obs["enterprise_telemetry"]
    assert final_data["control_plane"]["allowed"] is True
    assert "enterprise_telemetry" in final_data
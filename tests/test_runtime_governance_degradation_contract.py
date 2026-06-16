"""Runtime governance hooks — degradations land in ctx.metadata."""

from __future__ import annotations

from kernel.runtime.governance_hooks import degrade_ctx, degrade_request_meta


def test_degrade_ctx_appends_semantic_observability():
    class Ctx:
        metadata = {}

    degrade_ctx(Ctx(), subsystem="test_sub", detail="unit_test", exc=ValueError("boom"))
    obs = Ctx.metadata.get("semantic_observability") or {}
    deg = obs.get("degradations") or []
    assert len(deg) >= 1
    assert deg[-1]["subsystem"] == "test_sub"
    assert "boom" in deg[-1]["detail"]


def test_degrade_request_meta_mutates_request():
    class Req:
        def __init__(self) -> None:
            self.metadata: dict = {}

    req = Req()
    md = degrade_request_meta(req, subsystem="request_sub", detail="req_test")
    assert "semantic_observability" in md
    assert req.metadata.get("semantic_observability")
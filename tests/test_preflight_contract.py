"""Control plane preflight module."""

from __future__ import annotations

from control_plane.preflight import preflight_from_metadata


class TestPreflight:
    def test_preflight_allowed_default(self):
        out = preflight_from_metadata(
            user_id="u1",
            session_id="s1",
            metadata={"tenant_id": "default"},
            query="hello",
        )
        assert out.get("allowed") is True

    def test_pii_triggers_gdpr_when_configured(self):
        from control_plane.control_plane import get_enterprise_control_plane

        cp = get_enterprise_control_plane()
        out = cp.evaluate_turn(
            metadata={"compliance_frameworks": ["gdpr"], "data_residency": "us"},
            pii_detected=True,
        )
        assert out.allowed is False
"""PII detection and memory compression plans."""

from __future__ import annotations

from governance.pii_detector import detect_pii_signals
from memory.fabric.memory_compression import plan_memory_maintenance


class TestPII:
    def test_email_detected(self):
        sig = detect_pii_signals("contact me at user@example.com")
        assert sig.detected is True
        assert "email" in sig.types


class TestMemoryCompression:
    def test_overflow_archives_low_confidence(self):
        memories = [
            {"id": f"m{i}", "confidence": 0.1 + i * 0.01} for i in range(150)
        ]
        plan = plan_memory_maintenance(memories, max_active=128)
        assert plan.summarize is True
        assert len(plan.archive_ids) + len(plan.forget_ids) > 0
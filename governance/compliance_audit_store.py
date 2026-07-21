"""Re-export compliance audit from kernel.governance (single implementation)."""

from __future__ import annotations

from kernel.governance.compliance_audit_store import (
    list_recent_events,
    list_recent_events_from_db,
    record_compliance_event,
)

__all__ = [
    "record_compliance_event",
    "list_recent_events",
    "list_recent_events_from_db",
]
"""
FailureMemory — Structured storage for execution failures.

Stores FailureRecord keyed by capability_type, enabling:
  - Automatic avoidance of known failure patterns
  - Degradation detection and alerting
  - Query pattern → failure type correlation

Works alongside ExecutionMemory (success-focused) to provide a complete
picture of capability behavior.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# Max records to keep in memory
_MAX_RECORDS = 500
# How long before a failure record is considered stale
_STALE_SECONDS = 86400 * 7  # 7 days


@dataclass
class FailureRecord:
    """A single recorded failure event."""

    capability_type: str
    failure_type: str  # timeout | hallucination | low_critic | contradiction | empty_result | user_dissatisfaction | exception
    query_pattern: str = ""  # fingerprint of the triggering query
    context_snapshot: str = ""  # brief description of triggering conditions
    resolution: str = ""  # how it was eventually resolved
    latency_ms: int = 0
    timestamp: float = field(default_factory=time.time)
    record_id: str = ""


@dataclass
class FailureStats:
    """Aggregated failure statistics for a capability."""
    capability_type: str = ""
    total_failures: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    recent_failures_1h: int = 0
    recent_failures_24h: int = 0
    avg_resolution_latency_ms: int = 0
    most_common_failure: str = ""
    most_common_query_pattern: str = ""


class FailureMemory:
    """Structured memory for execution failures, indexed by capability_type.

    Single instance (module-level singleton).  Used by the constraint layer
    and the CapabilityReasoner to avoid known-bad execution paths.
    """

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._records: list[FailureRecord] = []
        self._by_capability: dict[str, list[FailureRecord]] = defaultdict(list)
        self._max_records = max_records
        self._id_counter = 0

    # ── Recording ─────────────────────────────────────────────────────────

    def record(self, record: FailureRecord) -> None:
        """Record a failure event."""
        self._id_counter += 1
        record.record_id = f"fail_{self._id_counter}_{int(record.timestamp)}"

        self._records.append(record)
        self._by_capability[record.capability_type].append(record)

        # Evict oldest if over capacity
        while len(self._records) > self._max_records:
            oldest = self._records.pop(0)
            cap_list = self._by_capability.get(oldest.capability_type, [])
            if oldest in cap_list:
                cap_list.remove(oldest)

        logger.debug(
            "Failure recorded",
            capability=record.capability_type,
            failure_type=record.failure_type,
        )

    def record_from_result(
        self,
        capability_type: str,
        query: str,
        success: bool,
        error_msg: str = "",
        latency_ms: int = 0,
        critic_score: float = 0.0,
    ) -> None:
        """Convenience: record a failure from an execution result."""
        if success:
            return  # Only record failures

        failure_type = "exception"
        if "timeout" in error_msg.lower():
            failure_type = "timeout"
        elif "empty" in error_msg.lower():
            failure_type = "empty_result"
        elif critic_score < 0.4:
            failure_type = "low_critic"
        elif "hallucin" in error_msg.lower():
            failure_type = "hallucination"
        elif "contradict" in error_msg.lower():
            failure_type = "contradiction"

        self.record(FailureRecord(
            capability_type=capability_type,
            failure_type=failure_type,
            query_pattern=query[:100],
            context_snapshot=error_msg[:200],
            latency_ms=latency_ms,
        ))

    # ── Querying ──────────────────────────────────────────────────────────

    def get_recent_failures(
        self, capability_type: str, window_seconds: float = 3600
    ) -> list[FailureRecord]:
        """Get failures for a capability within a time window."""
        now = time.time()
        cutoff = now - window_seconds
        return [
            r for r in self._by_capability.get(capability_type, [])
            if r.timestamp >= cutoff
        ]

    def get_stats(self, capability_type: str) -> FailureStats:
        """Get aggregated failure statistics for a capability."""
        records = self._by_capability.get(capability_type, [])
        if not records:
            return FailureStats(capability_type=capability_type)

        now = time.time()
        by_type: dict[str, int] = defaultdict(int)
        recent_1h = 0
        recent_24h = 0
        total_latency = 0
        latency_count = 0

        for r in records:
            by_type[r.failure_type] += 1
            if r.timestamp >= now - 3600:
                recent_1h += 1
            if r.timestamp >= now - 86400:
                recent_24h += 1
            if r.latency_ms > 0:
                total_latency += r.latency_ms
                latency_count += 1

        most_common = max(by_type, key=by_type.get) if by_type else ""

        return FailureStats(
            capability_type=capability_type,
            total_failures=len(records),
            by_type=dict(by_type),
            recent_failures_1h=recent_1h,
            recent_failures_24h=recent_24h,
            avg_resolution_latency_ms=total_latency // latency_count if latency_count else 0,
            most_common_failure=most_common,
        )

    def should_avoid(self, capability_type: str, query: str = "") -> tuple[bool, str]:
        """Check if a capability should be avoided based on recent failure patterns.

        Returns (should_avoid, reason).
        """
        recent = self.get_recent_failures(capability_type, window_seconds=3600)

        if len(recent) >= 5:
            return True, (
                f"{capability_type} has {len(recent)} failures in the last hour. "
                "Strongly recommend avoiding this capability."
            )

        if len(recent) >= 3:
            # Check if failures are concentrated (same failure type)
            types = [r.failure_type for r in recent]
            if len(set(types)) <= 1:
                return True, (
                    f"{capability_type} has {len(recent)} concentrated {types[0]} failures "
                    "in the last hour."
                )

        # Check for timeout pattern
        timeouts = [r for r in recent if r.failure_type == "timeout"]
        if len(timeouts) >= 3:
            return True, (
                f"{capability_type} has {len(timeouts)} timeouts in the last hour."
            )

        return False, ""

    def find_similar_failures(
        self, query: str, top_k: int = 3
    ) -> list[FailureRecord]:
        """Find past failures with similar query patterns (simple keyword overlap)."""
        query_lower = query.lower()
        query_tokens = set(query_lower.split())

        scored: list[tuple[float, FailureRecord]] = []
        for r in self._records:
            pattern_lower = r.query_pattern.lower()
            pattern_tokens = set(pattern_lower.split())
            if not pattern_tokens:
                continue
            overlap = len(query_tokens & pattern_tokens)
            score = overlap / max(len(query_tokens), 1)
            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    # ── Maintenance ───────────────────────────────────────────────────────

    def clear_stale(self) -> int:
        """Remove records older than _STALE_SECONDS.  Returns count removed."""
        now = time.time()
        cutoff = now - _STALE_SECONDS
        before = len(self._records)
        self._records = [r for r in self._records if r.timestamp >= cutoff]
        for cap_type in list(self._by_capability.keys()):
            self._by_capability[cap_type] = [
                r for r in self._by_capability[cap_type] if r.timestamp >= cutoff
            ]
        removed = before - len(self._records)
        if removed:
            logger.debug("Cleared stale failure records", count=removed)
        return removed

    def reset(self) -> None:
        """Clear all records."""
        self._records.clear()
        self._by_capability.clear()
        self._id_counter = 0


# Module-level singleton
failure_memory = FailureMemory()

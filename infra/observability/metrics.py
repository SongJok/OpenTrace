"""
Prometheus metrics — gracefully degrades if prometheus_client not installed.
"""
from __future__ import annotations

from typing import Any

_PROM_AVAILABLE = False
try:
    from prometheus_client import Counter, Gauge, Histogram, REGISTRY
    _PROM_AVAILABLE = True
except ImportError:
    pass


class _Noop:
    """No-op metric object — ignores all calls."""
    def labels(self, **kwargs) -> "_Noop":
        return self
    def inc(self, amount: float = 1) -> None:
        pass
    def dec(self, amount: float = 1) -> None:
        pass
    def observe(self, amount: float) -> None:
        pass
    def __call__(self, *args, **kwargs) -> "_Noop":
        return self


def _counter(name: str, doc: str, labels: list) -> Any:
    if not _PROM_AVAILABLE:
        return _Noop()
    try:
        return Counter(name, doc, labels)
    except Exception:
        return _Noop()


def _gauge(name: str, doc: str, labels: list | None = None) -> Any:
    if not _PROM_AVAILABLE:
        return _Noop()
    try:
        if labels:
            return Gauge(name, doc, labels)
        return Gauge(name, doc)
    except Exception:
        return _Noop()


def _histogram(name: str, doc: str, labels: list, buckets: list) -> Any:
    if not _PROM_AVAILABLE:
        return _Noop()
    try:
        return Histogram(name, doc, labels, buckets=buckets)
    except Exception:
        return _Noop()


HTTP_REQUESTS_TOTAL = _counter(
    "opentrace_http_requests_total", "Total HTTP requests", ["method", "endpoint", "status"]
)
HTTP_REQUEST_DURATION = _histogram(
    "opentrace_http_request_duration_seconds", "HTTP latency",
    ["method", "endpoint"], [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)
LLM_CALLS_TOTAL = _counter(
    "opentrace_llm_calls_total", "Total LLM calls", ["provider", "model", "status"]
)
LLM_TOKENS_USED = _counter(
    "opentrace_llm_tokens_total", "Total tokens", ["provider", "model", "type"]
)
LLM_LATENCY = _histogram(
    "opentrace_llm_latency_seconds", "LLM latency",
    ["provider", "model"], [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)
AGENT_TASKS_TOTAL = _counter(
    "opentrace_agent_tasks_total", "Agent tasks", ["agent_type", "status"]
)
AGENT_STEPS = _histogram(
    "opentrace_agent_steps", "Steps per agent", ["agent_type"], [1, 2, 4, 8, 16, 32]
)
ACTIVE_SESSIONS = _gauge("opentrace_active_sessions", "Active sessions")
MEMORY_HITS = _counter(
    "opentrace_memory_hits_total", "Memory hits", ["store_type"]
)
DAG_EXECUTIONS_TOTAL = _counter(
    "opentrace_dag_executions_total", "DAG executions", ["status"]
)
DAG_TASK_DURATION = _histogram(
    "opentrace_dag_task_duration_seconds", "DAG task duration",
    ["task_type"], [0.01, 0.1, 0.5, 1.0, 5.0, 30.0]
)
KERNEL_STEP_TOTAL = _counter(
    "opentrace_kernel_step_total", "Kernel loop step executions", ["step_type", "status"]
)

# Semantic parsing cache metrics
SEMANTIC_PARSE_CACHE_TOTAL = _counter(
    "opentrace_semantic_parse_cache_total", "Semantic parse cache lookups", ["result"]  # result: hit/miss/error
)
SEMANTIC_PARSE_CACHE_LATENCY = _histogram(
    "opentrace_semantic_parse_cache_latency_seconds", "Cache lookup latency",
    [], [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5]
)

# JOIN path inference metrics
JOIN_PATH_INFERENCE_TOTAL = _counter(
    "opentrace_join_path_inference_total", "JOIN path inference attempts", ["method"]  # method: fk/heuristic/llm
)
JOIN_PATH_INFERENCE_SUCCESS = _counter(
    "opentrace_join_path_inference_success", "Successful JOIN path inferences", ["method"]
)
JOIN_PATH_DEPTH = _histogram(
    "opentrace_join_path_depth", "JOIN path depth distribution",
    [], [1, 2, 3, 4, 5, 10]
)

ENTERPRISE_TURNS_TOTAL = _counter(
    "opentrace_enterprise_turns_total",
    "Cognitive turns with enterprise telemetry",
    ["tenant_id", "success"],
)
ENTERPRISE_TURN_COST = _counter(
    "opentrace_enterprise_turn_cost_usd",
    "Attributed turn cost (estimated)",
    ["tenant_id", "capability_type"],
)
CONTROL_PLANE_DENIALS = _counter(
    "opentrace_control_plane_denials_total",
    "Control plane denials",
    ["reason"],
)
GOAL_STABILITY = _gauge(
    "opentrace_cognitive_goal_stability",
    "Last recorded goal stability score",
)
CAPABILITY_SUCCESS_RATE = _gauge(
    "opentrace_capability_success_rate",
    "Rolling capability success rate from Capability OS",
    ["capability_type"],
)

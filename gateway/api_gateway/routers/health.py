"""
Health-check router.
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from infra.cache.redis_client import get_pubsub_redis
from infra.config.orchestrator_label import (
    orchestrator_annotations_enabled,
    resolve_orchestrator_label,
)
from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.observability.runtime_metrics import runtime_metrics_store
from kernel.cognition.world_model import WorldModel

router = APIRouter()

START_TIME = time.time()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    uptime_seconds: float
    environment: str


class DependencyHealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    agent_bus: str
    agent_worker: str
    orchestrator: str
    timestamp: int


class RuntimeCognitionHealthResponse(BaseModel):
    status: str
    orchestrator: str
    annotations_enabled: bool
    lexicon_records: int
    avg_agent_latency_ms: int
    avg_first_token_ms: int
    avg_orchestrator_latency_ms: int
    supervisor_retry_total: int
    metric_samples: int
    adaptive_mode_enabled: bool
    timestamp: int


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="opentrace",
        version="0.1.0",
        uptime_seconds=round(time.time() - START_TIME, 2),
        environment=settings.app_env,
    )


@router.get("/health/deps", response_model=DependencyHealthResponse)
async def health_deps() -> DependencyHealthResponse:
    now = int(time.time())

    db_status = "ok"
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "down"

    redis_status = "ok"
    bus_status = "ok"
    worker_status = "degraded"
    try:
        r = await get_pubsub_redis()
        pong = await r.r.ping()
        if not pong:
            redis_status = "down"
            bus_status = "down"
        else:
            bus_mode = str(getattr(settings, "kernel_agent_bus_mode", "pubsub")).lower()
            ns = str(getattr(settings, "kernel_agent_bus_namespace", "opentrace:agent"))
            if bus_mode == "stream":
                # stream health check should not rely on zset APIs
                _ = f"{ns}:stream:result"
            hb = await r.get(f"{ns}:worker:heartbeat")
            if isinstance(hb, str) and hb:
                try:
                    if now - int(float(hb)) <= 45:
                        worker_status = "ok"
                except Exception:
                    worker_status = "degraded"
    except Exception:
        redis_status = "down"
        bus_status = "down"
        worker_status = "down"

    overall = "ok"
    if "down" in {db_status, redis_status, bus_status}:
        overall = "down"
    elif worker_status != "ok":
        overall = "degraded"

    return DependencyHealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        agent_bus=bus_status,
        agent_worker=worker_status,
        orchestrator=resolve_orchestrator_label(settings),
        timestamp=now,
    )


@router.get("/health/runtime", response_model=RuntimeCognitionHealthResponse)
async def health_runtime() -> RuntimeCognitionHealthResponse:
    now = int(time.time())
    wm = WorldModel()
    records = len(wm.entity_registry.all())
    orchestrator = resolve_orchestrator_label(settings)
    annotations_enabled = orchestrator_annotations_enabled(settings)
    metrics = runtime_metrics_store.snapshot()
    return RuntimeCognitionHealthResponse(
        status="ok",
        orchestrator=orchestrator,
        annotations_enabled=annotations_enabled,
        lexicon_records=records,
        avg_agent_latency_ms=int(metrics.get("avg_agent_latency_ms", 0) or 0),
        avg_first_token_ms=int(metrics.get("avg_first_token_ms", 0) or 0),
        avg_orchestrator_latency_ms=int(metrics.get("avg_orchestrator_latency_ms", 0) or 0),
        supervisor_retry_total=int(metrics.get("supervisor_retry_total", 0) or 0),
        metric_samples=int(metrics.get("samples", 0) or 0),
        adaptive_mode_enabled=bool(getattr(settings, "kernel_adaptive_mode_enabled", False)),
        timestamp=now,
    )


class CognitiveOsHealthResponse(BaseModel):
    status: str
    flag_validation_ok: bool
    flag_violations: list[str]
    tier1_runtimes: list[str]
    orchestrator_label: str
    timestamp: int


@router.get("/health/cognitive-os", response_model=CognitiveOsHealthResponse)
async def health_cognitive_os() -> CognitiveOsHealthResponse:
    """Readiness for vNext: flag deps + Tier-1 runtime registry (no secrets)."""
    from infra.config.flag_governance import validate_feature_flags
    from kernel.runtime.registry import ensure_runtimes_registered, list_runtimes

    fv = validate_feature_flags(settings)
    ensure_runtimes_registered()
    tier1 = sorted(list_runtimes())
    status = "ok" if fv.ok else "degraded"
    return CognitiveOsHealthResponse(
        status=status,
        flag_validation_ok=fv.ok,
        flag_violations=list(fv.violations),
        tier1_runtimes=tier1,
        orchestrator_label=resolve_orchestrator_label(settings),
        timestamp=int(time.time()),
    )


@router.get("/ping")
async def ping() -> dict:
    return {"pong": True}

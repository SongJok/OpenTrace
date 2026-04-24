from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from infra.config.settings import settings


DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "speed": {
        "draft_threshold": 0.65,
        "draft_max_chars": 280,
        "rag_min_score": 0.30,
        "max_parallel": 2,
    },
    "balanced": {
        "draft_threshold": 0.75,
        "draft_max_chars": 220,
        "rag_min_score": 0.35,
        "max_parallel": 3,
    },
    "quality": {
        "draft_threshold": 0.80,
        "draft_max_chars": 180,
        "rag_min_score": 0.40,
        "max_parallel": 2,
    },
    "identity": {
        "draft_threshold": 1.0,
        "draft_max_chars": 160,
        "rag_min_score": 0.40,
        "max_parallel": 1,
    },
}


def _load_json_profiles() -> dict[str, dict[str, Any]]:
    raw = str(getattr(settings, "kernel_adaptive_profile_json", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = dict(v)
    return out


PROFILE_OVERRIDES = _load_json_profiles()


def get_profile_defaults(name: str) -> dict[str, Any]:
    key = (name or "balanced").strip().lower() or "balanced"
    base = deepcopy(DEFAULT_PROFILES.get(key, DEFAULT_PROFILES["balanced"]))
    override = PROFILE_OVERRIDES.get(key, {})
    base.update(override)
    base["name"] = key
    return base

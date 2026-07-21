from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from infra.config.settings import settings

DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "speed": {
        "draft_threshold": 0.65,
        "draft_max_chars": 400,
        "rag_min_score": 0.30,
        "max_parallel": 2,
    },
    "balanced": {
        "draft_threshold": 0.75,
        "draft_max_chars": 340,
        "rag_min_score": 0.35,
        "max_parallel": 3,
    },
    "quality": {
        "draft_threshold": 0.80,
        "draft_max_chars": 260,
        "rag_min_score": 0.40,
        "max_parallel": 2,
    },
    "identity": {
        "draft_threshold": 1.0,
        "draft_max_chars": 200,
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


# ── User preference tag → profile / answer-style mapping ──────────────

# Tags that affect conciseness (lower draft_max_chars → more concise)
_CONCISE_TAGS = {"concise", "简洁", "brief", "short", "精简", "简练"}
_DETAILED_TAGS = {"detailed", "详细", "verbose", "comprehensive", "详尽", "full"}

# Tags that affect technical level
_TECHNICAL_TAGS = {"technical", "技术", "expert", "专业", "developer", "engineer"}
_PLAIN_TAGS = {"plain", "通俗", "simple", "beginner", "易懂", "non-technical", "layman"}

# Tags that affect structure preference
_STRUCTURED_TAGS = {"structured", "结构化", "report", "bullet", "列表"}
_CONVERSATIONAL_TAGS = {"conversational", "对话", "chatty", "口语", "casual", "随意"}

# Tags that affect tone
_FORMAL_TAGS = {"formal", "正式", "professional"}
_WARM_TAGS = {"warm", "温暖", "friendly", "友好", "亲切"}


def apply_user_tags(profile: dict[str, Any], user_tags: list[str]) -> dict[str, Any]:
    """Merge user preference tags into an adaptive profile dict.

    Returns a new dict (does not mutate the input).
    """
    if not user_tags:
        return profile
    p = deepcopy(profile)
    tags_lower = {t.strip().lower() for t in user_tags if t and t.strip()}
    if not tags_lower:
        return p

    # ── Conciseness ──────────────────────────────────────────────────
    if tags_lower & _CONCISE_TAGS:
        p["draft_max_chars"] = max(120, int(p.get("draft_max_chars", 340) * 0.6))
        p["conciseness"] = "concise"
    elif tags_lower & _DETAILED_TAGS:
        p["draft_max_chars"] = min(800, int(p.get("draft_max_chars", 340) * 2))
        p["conciseness"] = "detailed"

    # ── Technical level ──────────────────────────────────────────────
    if tags_lower & _TECHNICAL_TAGS:
        p["technical_level"] = "technical"
    elif tags_lower & _PLAIN_TAGS:
        p["technical_level"] = "plain"

    # ── Structure ────────────────────────────────────────────────────
    if tags_lower & _STRUCTURED_TAGS:
        p["structure"] = "structured"
    elif tags_lower & _CONVERSATIONAL_TAGS:
        p["structure"] = "conversational"

    # ── Tone ─────────────────────────────────────────────────────────
    if tags_lower & _FORMAL_TAGS:
        p["tone"] = "formal"
    elif tags_lower & _WARM_TAGS:
        p["tone"] = "warm"

    return p


def user_tags_to_style_hints(user_tags: list[str]) -> dict[str, str | None]:
    """Extract answer-style hints from user preference tags.

    Returns a dict with keys: conciseness, technical_level, structure, tone.
    Each value is a string or None.
    """
    hints: dict[str, str | None] = {
        "conciseness": None,
        "technical_level": None,
        "structure": None,
        "tone": None,
    }
    if not user_tags:
        return hints
    tags_lower = {t.strip().lower() for t in user_tags if t and t.strip()}

    if tags_lower & _CONCISE_TAGS:
        hints["conciseness"] = "concise"
    elif tags_lower & _DETAILED_TAGS:
        hints["conciseness"] = "detailed"

    if tags_lower & _TECHNICAL_TAGS:
        hints["technical_level"] = "technical"
    elif tags_lower & _PLAIN_TAGS:
        hints["technical_level"] = "plain"

    if tags_lower & _STRUCTURED_TAGS:
        hints["structure"] = "structured"
    elif tags_lower & _CONVERSATIONAL_TAGS:
        hints["structure"] = "conversational"

    if tags_lower & _FORMAL_TAGS:
        hints["tone"] = "formal"
    elif tags_lower & _WARM_TAGS:
        hints["tone"] = "warm"

    return hints

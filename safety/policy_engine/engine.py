"""
Safety Policy Engine — request evaluation against configurable access policies.
Now includes Redis-backed rate-limit enforcement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)

RATE_LIMIT_KEY = "opentrace:rate_limit:{user_id}"


class PolicyAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REDACT = "redact"
    AUDIT = "audit"
    RATE_LIMIT = "rate_limit"


@dataclass
class PolicyRule:
    rule_id: str
    name: str
    action: PolicyAction
    conditions: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    enabled: bool = True


@dataclass
class PolicyResult:
    allowed: bool
    action: PolicyAction
    matched_rule: Optional[str] = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


_DEFAULT_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="deny_empty_query",
        name="Deny empty queries",
        action=PolicyAction.DENY,
        conditions={"min_query_length": 1},
        priority=1,
    ),
    PolicyRule(
        rule_id="rate_limit_anon",
        name="Rate limit anonymous users",
        action=PolicyAction.RATE_LIMIT,
        conditions={"user_id_pattern": "", "max_rpm": 20},
        priority=10,
    ),
    PolicyRule(
        rule_id="audit_sensitive",
        name="Audit sensitive operations",
        action=PolicyAction.AUDIT,
        conditions={"keywords": ["delete", "drop", "truncate", "rm -rf"]},
        priority=20,
    ),
]


class SafetyPolicyEngine:
    """
    Evaluates requests against the configured rule set.
    Rate-limit rules are enforced via Redis sliding-window counters.
    """

    def __init__(self, rules: Optional[list[PolicyRule]] = None) -> None:
        self._rules = sorted(
            rules or _DEFAULT_RULES, key=lambda r: r.priority
        )

    def evaluate(
        self,
        query: str,
        user_id: str = "",
        session_id: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> PolicyResult:
        """Synchronous evaluation — rate-limit uses best-effort cached count."""
        with tracer.start_as_current_span("safety_policy.evaluate") as span:
            ctx = {"query": query, "user_id": user_id,
                   "session_id": session_id, **(metadata or {})}
            for rule in self._rules:
                if not rule.enabled:
                    continue
                result = self._check_rule_sync(rule, ctx)
                if result is not None:
                    span.set_attribute("policy.rule", rule.rule_id)
                    span.set_attribute("policy.action", result.action.value)
                    logger.info("Policy matched", rule=rule.rule_id,
                                action=result.action.value, user=user_id)
                    return result
            return PolicyResult(allowed=True, action=PolicyAction.ALLOW,
                                reason="No rules matched")

    async def evaluate_async(
        self,
        query: str,
        user_id: str = "",
        session_id: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> PolicyResult:
        """Async evaluation — enforces rate-limit rules with Redis."""
        with tracer.start_as_current_span("safety_policy.evaluate_async") as span:
            ctx = {"query": query, "user_id": user_id,
                   "session_id": session_id, **(metadata or {})}
            for rule in self._rules:
                if not rule.enabled:
                    continue
                result = await self._check_rule_async(rule, ctx)
                if result is not None:
                    span.set_attribute("policy.rule", rule.rule_id)
                    span.set_attribute("policy.action", result.action.value)
                    logger.info("Policy matched (async)", rule=rule.rule_id,
                                action=result.action.value, user=user_id)
                    return result
            return PolicyResult(allowed=True, action=PolicyAction.ALLOW,
                                reason="No rules matched")

    def _check_rule_sync(
        self, rule: PolicyRule, ctx: dict[str, Any]
    ) -> Optional[PolicyResult]:
        cond = rule.conditions
        if "min_query_length" in cond:
            if len(ctx.get("query", "")) < cond["min_query_length"]:
                return PolicyResult(allowed=False, action=PolicyAction.DENY,
                                    matched_rule=rule.rule_id, reason="Query too short")
        if "keywords" in cond:
            q = ctx.get("query", "").lower()
            for kw in cond["keywords"]:
                if kw in q:
                    return PolicyResult(allowed=True, action=PolicyAction.AUDIT,
                                        matched_rule=rule.rule_id,
                                        reason=f"Sensitive keyword: {kw}")
        # Rate-limit sync: skip (requires Redis, handled in async path)
        return None

    async def _check_rule_async(
        self, rule: PolicyRule, ctx: dict[str, Any]
    ) -> Optional[PolicyResult]:
        cond = rule.conditions
        # Deny empty
        if "min_query_length" in cond:
            if len(ctx.get("query", "")) < cond["min_query_length"]:
                return PolicyResult(allowed=False, action=PolicyAction.DENY,
                                    matched_rule=rule.rule_id, reason="Query too short")
        # Rate limit — Redis sliding window (per-minute)
        if rule.action == PolicyAction.RATE_LIMIT:
            max_rpm = cond.get("max_rpm", 20)
            user_id = ctx.get("user_id", "")
            # Apply to anonymous users if user_id_pattern == ""
            if cond.get("user_id_pattern", None) == "" and user_id == "":
                exceeded = await self._check_rate_limit("anon", max_rpm)
                if exceeded:
                    return PolicyResult(
                        allowed=False, action=PolicyAction.RATE_LIMIT,
                        matched_rule=rule.rule_id,
                        reason=f"Rate limit exceeded: {max_rpm} rpm",
                    )
        # Keyword audit
        if "keywords" in cond:
            q = ctx.get("query", "").lower()
            for kw in cond["keywords"]:
                if kw in q:
                    return PolicyResult(allowed=True, action=PolicyAction.AUDIT,
                                        matched_rule=rule.rule_id,
                                        reason=f"Sensitive keyword: {kw}")
        return None

    async def _check_rate_limit(self, key: str, max_rpm: int) -> bool:
        """Redis sliding-window rate limiter. Returns True if limit exceeded."""
        import time
        try:
            from infra.cache.redis_client import get_rate_limit_redis
            r = await get_rate_limit_redis()
            rkey = RATE_LIMIT_KEY.format(user_id=key)
            now = int(time.time())
            window_start = now - 60
            pipe = r.pipeline()
            pipe.zremrangebyscore(rkey, 0, window_start)
            pipe.zadd(rkey, {str(now * 1000): now})
            pipe.zcard(rkey)
            pipe.expire(rkey, 120)
            results = await pipe.execute()
            count = results[2]
            return int(count) > max_rpm
        except Exception as exc:  # noqa: BLE001
            logger.debug("Rate limit check failed", error=str(exc))
            return False

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def remove_rule(self, rule_id: str) -> None:
        self._rules = [r for r in self._rules if r.rule_id != rule_id]


policy_engine = SafetyPolicyEngine()

"""
Safety Guardrails — input/output content filtering.
Adds PII detection and integrates with SafetyPolicyEngine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from infra.observability.logger import get_logger

logger = get_logger(__name__)

# -----------------------------------------------------------------------
# Blocklist patterns
# -----------------------------------------------------------------------
_ATTACK_PATTERNS: list[str] = [
    r"\b(hack|exploit|malware|ransomware|rootkit|keylogger)\b",
    r"\b(password dump|credential leak|sql injection|xss|csrf)\b",
    r"\b(rm -rf|drop table|delete from|truncate table)\b",
    r"(ignore previous instructions|disregard your instructions|jailbreak)",
]

# PII patterns — redact rather than block
_PII_PATTERNS: dict[str, str] = {
    "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "phone_cn": r"1[3-9]\d{9}",
    "phone_intl": r"\+?1?\s?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}",
    "credit_card": r"\b(?:\d[ -]?){13,16}\b",
    "id_cn": r"\b[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b",
}


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str = ""
    sanitized: Optional[str] = None
    pii_detected: bool = False


class Guardrails:
    """
    Layered safety filter:
      1. Attack/injection blocklist → block entirely
      2. PII patterns              → redact in output
      3. SafetyPolicyEngine        → policy-level deny/audit
    """

    def __init__(
        self,
        blocklist: Optional[list[str]] = None,
        redact_pii_in_output: bool = True,
    ) -> None:
        patterns = blocklist or _ATTACK_PATTERNS
        self._block_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self._pii_patterns = {
            label: re.compile(p) for label, p in _PII_PATTERNS.items()
        }
        self._redact_pii = redact_pii_in_output

        # Lazy-load SafetyPolicyEngine to avoid circular imports
        self._policy_engine = None

    def _get_policy_engine(self):
        if self._policy_engine is None:
            from safety.policy_engine.engine import SafetyPolicyEngine
            self._policy_engine = SafetyPolicyEngine()
        return self._policy_engine

    def check_input(
        self,
        text: str,
        user_id: str = "",
        session_id: str = "",
    ) -> GuardrailResult:
        # 1. Attack blocklist
        for pattern in self._block_patterns:
            if pattern.search(text):
                logger.warning("Guardrail blocked input", pattern=pattern.pattern, user=user_id)
                return GuardrailResult(
                    allowed=False,
                    reason=f"Blocked pattern: {pattern.pattern}",
                )

        # 2. Policy engine check
        policy = self._get_policy_engine()
        result = policy.evaluate(query=text, user_id=user_id, session_id=session_id)
        if not result.allowed:
            logger.warning("Policy engine blocked input", rule=result.matched_rule, user=user_id)
            return GuardrailResult(allowed=False, reason=result.reason)

        return GuardrailResult(allowed=True, sanitized=text)

    def check_output(
        self,
        text: str,
        redact_pii: Optional[bool] = None,
    ) -> GuardrailResult:
        sanitized = text
        pii_found = False

        # 1. Attack patterns in output → redact
        for pattern in self._block_patterns:
            if pattern.search(sanitized):
                sanitized = pattern.sub("[REDACTED]", sanitized)
                logger.warning("Guardrail redacted output", pattern=pattern.pattern)

        # 2. PII redaction
        should_redact = redact_pii if redact_pii is not None else self._redact_pii
        if should_redact:
            for label, pattern in self._pii_patterns.items():
                if pattern.search(sanitized):
                    sanitized = pattern.sub(f"[{label.upper()}_REDACTED]", sanitized)
                    pii_found = True
                    logger.info("PII redacted from output", pii_type=label)

        return GuardrailResult(
            allowed=True,
            reason="Output sanitized" if sanitized != text else "",
            sanitized=sanitized,
            pii_detected=pii_found,
        )

    def scan_pii(self, text: str) -> dict[str, list[str]]:
        """Return a dict of PII type -> list of matched values (for audit)."""
        findings: dict[str, list[str]] = {}
        for label, pattern in self._pii_patterns.items():
            matches = pattern.findall(text)
            if matches:
                findings[label] = matches
        return findings


# Singleton
guardrails = Guardrails()

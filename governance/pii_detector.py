"""Lightweight PII heuristics for compliance preflight."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PIISignals:
    detected: bool = False
    types: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict:
        return {"detected": self.detected, "types": list(self.types), "score": self.score}


_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?(?:\d{3}[-.\s]?){2,3}\d{3,4}")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def detect_pii_signals(text: str) -> PIISignals:
    t = (text or "").strip()
    if not t:
        return PIISignals()
    types: list[str] = []
    if _EMAIL.search(t):
        types.append("email")
    if _PHONE.search(t):
        types.append("phone")
    if _SSN.search(t):
        types.append("ssn")
    if _CARD.search(t) and any(c.isdigit() for c in t):
        types.append("payment_card")
    score = min(1.0, len(types) * 0.35)
    return PIISignals(detected=len(types) > 0, types=types, score=score)
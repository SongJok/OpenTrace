from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from infra.cache.redis_client import get_memory_redis


@dataclass
class RiskAssessment:
    risk_level: str
    requires_confirmation: bool
    reason: str
    required_permissions: list[str]


def assess_query_risk(query: str) -> RiskAssessment:
    q = (query or "").lower()
    high_patterns = ["delete file", "rm -rf", "发送邮件", "send email", "transfer", "付款", "drop table"]
    medium_patterns = ["run code", "execute", "sandbox", "connector sync", "webhook"]

    if any(p in q for p in high_patterns):
        return RiskAssessment("HIGH", True, "Sensitive operation detected", ["tool:dangerous.write"])
    if any(p in q for p in medium_patterns):
        return RiskAssessment("MEDIUM", True, "Potentially risky tool operation", ["tool:exec"])
    return RiskAssessment("LOW", False, "", [])


async def issue_permission_token(session_id: str, permissions: list[str], ttl_seconds: int = 3600) -> str:
    raw = f"{session_id}:{','.join(sorted(set(permissions)))}:{time.time()}:{secrets.token_hex(8)}"
    token = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    r = await get_memory_redis()
    key = f"opentrace:perm:{token}"
    await r.setex(key, max(60, ttl_seconds), ",".join(sorted(set(permissions))) + f"|{session_id}")
    return token


async def validate_permission_token(session_id: str, token: str, required_permissions: list[str]) -> bool:
    r = await get_memory_redis()
    raw = await r.get(f"opentrace:perm:{token}")
    if not raw:
        return False
    try:
        perm_part, sid = str(raw).rsplit("|", 1)
    except ValueError:
        return False
    if sid != session_id:
        return False
    granted = set([x for x in perm_part.split(",") if x])
    return all(p in granted for p in required_permissions)


class ToolAnomalyDetector:
    def __init__(self) -> None:
        self._history: list[list[str]] = []
        self._model = None

    def _featurize(self, seq: list[str]) -> list[float]:
        s = "|".join(seq[-10:])
        h = hashlib.sha256(s.encode("utf-8")).digest()
        return [float(x) / 255.0 for x in h[:16]]

    def _fit_if_possible(self) -> None:
        if len(self._history) < 30:
            return
        try:
            from sklearn.ensemble import IsolationForest  # type: ignore
            X = [self._featurize(x) for x in self._history[-300:]]
            self._model = IsolationForest(random_state=42, contamination=0.08)
            self._model.fit(X)
        except Exception:
            self._model = None

    def record(self, tool_sequence: list[str]) -> None:
        if tool_sequence:
            self._history.append(tool_sequence[-10:])
        if len(self._history) > 500:
            self._history = self._history[-500:]
        self._fit_if_possible()

    def is_anomalous(self, tool_sequence: list[str]) -> bool:
        if not tool_sequence:
            return False
        if self._model is not None:
            try:
                pred = self._model.predict([self._featurize(tool_sequence)])
                return int(pred[0]) == -1
            except Exception:
                pass
        known = {t for seq in self._history for t in seq}
        if not known:
            return False
        unknown_count = sum(1 for t in tool_sequence if t not in known)
        return (unknown_count / max(1, len(tool_sequence))) > 0.6


tool_anomaly_detector = ToolAnomalyDetector()

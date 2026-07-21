"""
置信度衰减策略 — 基于时间和使用频率的记忆置信度衰减。

记忆不是永恒的真理。置信度会衰减：
- 随时间指数衰减（半衰期按记忆类型可配置）
- 检测到矛盾时（惩罚）
- 长期未使用时（萎缩）

防止过时记忆污染认知管线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import exp, log
from typing import Any

# 各记忆类型的默认半衰期（小时）
DEFAULT_HALF_LIVES: dict[str, float] = {
    "fact": 720.0,          # 30 天 — 事实相对稳定
    "preference": 1440.0,    # 60 天 — 用户偏好变化缓慢
    "episodic": 168.0,       # 7 天 — 近期事件更相关
    "semantic": 2160.0,      # 90 天 — 习得知识衰减缓慢
    "procedural": 4320.0,    # 180 天 — 技能稳定
    "conversation": 24.0,    # 1 天 — 对话上下文是短暂的
}


@dataclass
class ConfidenceDecayPolicy:
    """记忆随时间衰减的策略。"""
    memory_type: str = "fact"
    half_life_hours: float = 720.0
    min_confidence: float = 0.1       # 永不低于此值
    archive_threshold: float = 0.15    # 置信度低于此值时归档
    contradiction_penalty: float = 0.3  # 矛盾惩罚乘数
    atrophy_rate: float = 0.001        # 未使用时每天的萎缩率
    boost_on_access: float = 0.05      # 记忆被访问时的置信度提升


def apply_confidence_decay(
    memories: list[dict[str, Any]],
    policy: ConfidenceDecayPolicy | None = None,
) -> list[dict[str, Any]]:
    """对记忆列表应用置信度衰减。

    返回更新了置信度评分的记忆。低于 archive_threshold 的记忆
    被标记为待归档（置信度设为 archive_threshold 并加标记）。

    Args:
        memories: 记忆字典列表，包含键：content, confidence, created_at,
                  memory_type, last_accessed_at, access_count。
        policy: 衰减策略；如果为 None 则根据 memory_type 使用默认值。

    Returns:
        带有衰减置信度和元数据的记忆列表。
    """
    now = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []

    for mem in memories:
        mem_type = mem.get("memory_type", "fact")
        effective_policy = policy or ConfidenceDecayPolicy(
            memory_type=mem_type,
            half_life_hours=DEFAULT_HALF_LIVES.get(mem_type, 720.0),
        )
        half_life = effective_policy.half_life_hours

        # 获取时间戳
        created_str = mem.get("created_at", "")
        last_accessed_str = mem.get("last_accessed_at", created_str)

        created_at = _parse_timestamp(created_str) or now
        last_accessed = _parse_timestamp(last_accessed_str) or created_at

        # 基于时间的指数衰减
        age_hours = (now - created_at).total_seconds() / 3600.0
        decay_factor = exp(-log(2) * age_hours / half_life) if half_life > 0 else 1.0

        original_confidence = float(mem.get("confidence", 0.5))
        decayed_confidence = original_confidence * decay_factor

        # 萎缩：长期未使用的记忆额外衰减
        unused_hours = (now - last_accessed).total_seconds() / 3600.0
        atrophy_days = unused_hours / 24.0
        atrophy_penalty = effective_policy.atrophy_rate * atrophy_days
        decayed_confidence -= atrophy_penalty

        # 访问提升：频繁访问的记忆抵抗衰减
        access_count = int(mem.get("access_count", 0))
        if access_count > 0:
            access_boost = min(effective_policy.boost_on_access * log(access_count + 1), 0.2)
            decayed_confidence += access_boost

        # 钳位
        decayed_confidence = max(decayed_confidence, effective_policy.min_confidence)
        decayed_confidence = min(decayed_confidence, 1.0)

        result = dict(mem)
        result["confidence"] = round(decayed_confidence, 4)
        result["decay_factor"] = round(decay_factor, 4)
        result["age_hours"] = round(age_hours, 1)

        if decayed_confidence <= effective_policy.archive_threshold:
            result["should_archive"] = True
            result["archive_reason"] = f"confidence {decayed_confidence:.3f} below threshold {effective_policy.archive_threshold}"
        else:
            result["should_archive"] = False

        results.append(result)

    return results


def _parse_timestamp(ts: Any) -> datetime | None:
    """解析各种时间戳格式。"""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        try:
            # ISO 格式
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return None

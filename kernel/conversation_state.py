"""ConversationState — persistent structured session state for multi-turn chat.

Provides load/save/merge/compact for the conversation_states table,
replacing the flat metadata dict previously passed between turns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.storage.database import AsyncSessionLocal

logger = get_logger(__name__)


def _truncate_by_tokens(
    state: ConversationState,
    field: str,
    counter: Any,
    max_tokens: int,
) -> None:
    text = getattr(state, field, "") or ""
    if not text:
        return
    tokens = counter.count(text)
    if tokens <= max_tokens:
        return
    ratio = len(text) / max(tokens, 1)
    approx_chars = int(max_tokens * ratio * 0.9)
    if approx_chars < len(text):
        setattr(state, field, text[:approx_chars])


@dataclass
class EntityRef:
    name: str = ""
    entity_type: str = ""
    value: str = ""
    confidence: float = 0.5


@dataclass
class ConversationState:
    session_id: str = ""
    active_topic: str = ""
    active_intent: str = ""
    active_domain: str = "general_qa"
    active_entities: list[EntityRef] = field(default_factory=list)
    active_constraints: dict[str, Any] = field(default_factory=dict)
    active_mode: str = ""
    active_data_source_id: str = ""
    active_document_ids: list[str] = field(default_factory=list)
    active_attachment_ids: list[str] = field(default_factory=list)
    last_user_goal: str = ""
    last_assistant_summary: str = ""
    last_plan: dict[str, Any] = field(default_factory=dict)
    last_results: list[dict[str, Any]] = field(default_factory=list)
    last_result_refs: list[dict[str, Any]] = field(default_factory=list)
    last_turn_type: str = ""
    conversation_summary: str = ""
    pending_clarification: str = ""
    state_version: int = 0
    id: str = ""
    conversation_phase: str = ""
    turn_sequence: int = 0
    phase_transitions: list[dict[str, Any]] = field(default_factory=list)
    topic_stack: list[str] = field(default_factory=list)
    confirmed_facts: list[dict[str, Any]] = field(default_factory=list)
    turn_confidences: list[float] = field(default_factory=list)
    confidence_trend: list[float] = field(default_factory=list)
    learned_preferences: dict[str, Any] = field(default_factory=dict)

    _EXTENSION_FIELDS: frozenset = field(
        default=frozenset({
            "conversation_summary",
            "last_result_refs",
            "last_turn_type",
            "conversation_phase",
            "turn_sequence",
            "phase_transitions",
            "topic_stack",
            "confirmed_facts",
            "turn_confidences",
            "confidence_trend",
            "learned_preferences",
        }),
        repr=False,
    )

    def _pack_extension(self) -> dict[str, Any]:
        ext: dict[str, Any] = {}
        for f in self._EXTENSION_FIELDS:
            val = getattr(self, f, None)
            if val is not None and val != [] and val != {} and val != "":
                ext[f] = val
        return ext

    def _unpack_extension(self, d: dict[str, Any]) -> None:
        if not d:
            return
        for f in self._EXTENSION_FIELDS:
            if f in d:
                setattr(self, f, d[f])

    def is_same_topic(self, query: str) -> bool:
        return bool(
            self.active_topic
            and query.strip().lower().startswith(self.active_topic.lower())
        )

    def is_drill_down(self, query: str) -> bool:
        q_lower = query.strip().lower()
        return q_lower != self.active_topic.lower() and (
            q_lower.startswith(self.active_topic.lower())
            or (
                self.active_topic.lower() in q_lower
                and len(q_lower) > len(self.active_topic)
            )
        )

    def push_topic(self, topic: str) -> None:
        if self.active_topic and self.active_topic != topic:
            self.topic_stack.append(self.active_topic)
        self.active_topic = topic

    def pop_topic(self) -> str | None:
        if self.topic_stack:
            prev = self.topic_stack.pop()
            self.active_topic = prev
            return prev
        return None

    def to_db_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_topic": self.active_topic,
            "active_intent": self.active_intent,
            "active_domain": self.active_domain,
            "active_entities": (
                [
                    {"name": e.name, "entity_type": e.entity_type, "value": e.value, "confidence": e.confidence}
                    for e in self.active_entities
                ]
                if self.active_entities
                else []
            ),
            "active_constraints": self.active_constraints or {},
            "active_mode": self.active_mode,
            "active_data_source_id": self.active_data_source_id,
            "active_document_ids": self.active_document_ids or [],
            "active_attachment_ids": self.active_attachment_ids or [],
            "last_user_goal": self.last_user_goal,
            "last_assistant_summary": self.last_assistant_summary,
            "last_plan": self.last_plan or {},
            "last_results": self.last_results or [],
            "pending_clarification": self.pending_clarification or "",
            "state_version": self.state_version,
            "state_extension": self._pack_extension(),
        }

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> ConversationState:
        entities_raw = row.get("active_entities") or []
        entities = [
            EntityRef(
                name=e.get("name", ""),
                entity_type=e.get("entity_type", ""),
                value=e.get("value", ""),
                confidence=e.get("confidence", 0.5),
            )
            for e in entities_raw
        ]
        cs = cls(
            id=row.get("id", ""),
            session_id=row.get("session_id", ""),
            active_topic=row.get("active_topic") or "",
            active_intent=row.get("active_intent") or "",
            active_domain=row.get("active_domain") or "general_qa",
            active_entities=entities,
            active_constraints=row.get("active_constraints") or {},
            active_mode=row.get("active_mode") or "",
            active_data_source_id=row.get("active_data_source_id") or "",
            active_document_ids=row.get("active_document_ids") or [],
            active_attachment_ids=row.get("active_attachment_ids") or [],
            last_user_goal=row.get("last_user_goal") or "",
            last_assistant_summary=row.get("last_assistant_summary") or "",
            last_plan=row.get("last_plan") or {},
            last_results=row.get("last_results") or [],
            pending_clarification=row.get("pending_clarification") or "",
            state_version=row.get("state_version", 0),
        )
        ext = row.get("state_extension") or {}
        cs._unpack_extension(ext)
        return cs


class ConversationStateManager:
    def __init__(self) -> None:
        self.enabled = bool(
            getattr(settings, "kernel_conversation_state_enabled", True)
        )

    async def load(self, session_id: str) -> ConversationState | None:
        if not self.enabled:
            return None
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select
                from infra.storage.models import ConversationState as CSModel

                result = await db.execute(
                    select(CSModel).where(CSModel.session_id == session_id)
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return None
                cs = self._apply_to_row(row, None)  # builds ConversationState from row
                return cs
        except Exception as exc:
            logger.warning("ConversationState load failed", error=str(exc))
            return None

    async def save(self, cs: ConversationState) -> None:
        if not self.enabled:
            return
        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select
                from infra.storage.models import ConversationState as CSModel

                result = await db.execute(
                    select(CSModel).where(CSModel.session_id == cs.session_id)
                )
                row = result.scalar_one_or_none()
                if row is None:
                    row = CSModel(session_id=cs.session_id)
                    db.add(row)
                self._to_row(cs, row)
                await db.commit()
        except Exception as exc:
            logger.warning("ConversationState save failed", error=str(exc))

    async def get_or_create(self, session_id: str) -> ConversationState:
        cached = await self.load(session_id)
        if cached is not None:
            return cached
        cs = ConversationState(session_id=session_id, state_version=1)
        await self.save(cs)
        return cs

    def apply_patch(
        self, cs: ConversationState, patch: dict[str, Any]
    ) -> ConversationState:
        if not patch:
            return cs
        for key, val in patch.items():
            if hasattr(cs, key):
                setattr(cs, key, val)
        return cs

    def advance_turn(
        self, cs: ConversationState, query: str, response: str | None = None
    ) -> ConversationState:
        cs.turn_sequence += 1
        cs.last_user_goal = query.strip()
        if response:
            cs.last_assistant_summary = response.strip()
        cs.state_version += 1
        cs.pending_clarification = ""
        _detect_phase(query, cs, response or "")
        return cs

    def add_confidence(
        self, cs: ConversationState, turn_seq: int, confidence: float
    ) -> None:
        while len(cs.turn_confidences) < turn_seq:
            cs.turn_confidences.append(0.0)
        if len(cs.turn_confidences) == turn_seq:
            cs.turn_confidences.append(confidence)
        else:
            cs.turn_confidences[turn_seq] = confidence
        cs.confidence_trend = cs.turn_confidences[-10:]

    def compact(self, cs: ConversationState) -> ConversationState:
        try:
            from kernel.token_counter import get_token_counter

            counter = get_token_counter()
            max_t = int(
                getattr(settings, "conversation_state_max_tokens", 2000)
            )
            _truncate_by_tokens(cs, "last_user_goal", counter, max_t)
            _truncate_by_tokens(cs, "last_assistant_summary", counter, max_t)
            _truncate_by_tokens(cs, "conversation_summary", counter, max_t)
            if cs.confirmed_facts:
                cs.confirmed_facts = _merge_facts(cs.confirmed_facts, [])
        except Exception as exc:
            logger.warning("ConversationState compact failed", error=str(exc))
        return cs

    def _apply_to_row(
        self, row: Any, cs: ConversationState | None
    ) -> ConversationState:
        row_dict = {
            "id": row.id,
            "session_id": row.session_id,
            "active_topic": row.active_topic,
            "active_intent": row.active_intent,
            "active_domain": row.active_domain,
            "active_entities": row.active_entities,
            "active_constraints": row.active_constraints,
            "active_mode": row.active_mode,
            "active_data_source_id": row.active_data_source_id,
            "active_document_ids": row.active_document_ids,
            "active_attachment_ids": row.active_attachment_ids,
            "last_user_goal": row.last_user_goal,
            "last_assistant_summary": row.last_assistant_summary,
            "last_plan": row.last_plan,
            "last_results": row.last_results,
            "pending_clarification": row.pending_clarification,
            "state_version": row.state_version,
            "state_extension": row.state_extension,
        }
        return ConversationState.from_db_row(row_dict)

    def _to_row(self, cs: ConversationState, row: Any) -> None:
        data = cs.to_db_dict()
        for k, v in data.items():
            if k == "state_extension":
                setattr(row, k, v)
            elif hasattr(row, k):
                setattr(row, k, v)


def _detect_phase(
    query: str, state: ConversationState, response: str = ""
) -> str:
    q = query.strip()
    q_lower = q.lower()
    if state.pending_clarification:
        state.conversation_phase = "clarification"
    elif state.is_drill_down(q):
        state.conversation_phase = "drill_down"
        state.phase_transitions.append(
            {
                "from_phase": state.conversation_phase,
                "to_phase": "drill_down",
                "turn": state.turn_sequence,
            }
        )
    elif state.turn_sequence > 0 and state.is_same_topic(q):
        state.conversation_phase = "follow_up"
    elif state.turn_sequence == 0:
        state.conversation_phase = "open"
    else:
        state.conversation_phase = "topic_shift"
        state.phase_transitions.append(
            {
                "from_phase": state.conversation_phase,
                "to_phase": "topic_shift",
                "turn": state.turn_sequence,
            }
        )
    return state.conversation_phase


def _merge_facts(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    max_facts: int = 50,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for f in existing:
        key = f.get("fact", str(f))
        merged[key] = dict(f)
    for f in incoming:
        key = f.get("fact", str(f))
        merged[key] = dict(f)
    return sorted(merged.values(), key=lambda f: f.get("confidence", 0), reverse=True)[
        :max_facts
    ]

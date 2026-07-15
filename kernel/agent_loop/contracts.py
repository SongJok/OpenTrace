from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SideEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ExecutionProfile(StrEnum):
    AUTO = "auto"
    FAST = "fast"
    DEEP = "deep"


@dataclass(frozen=True)
class IntentPlan:
    goal: str
    task_type: str = "chat"
    capabilities: tuple[str, ...] = ()
    ambiguity: str | None = None
    risk: SideEffect = SideEffect.READ
    execution_profile: ExecutionProfile = ExecutionProfile.AUTO
    execution_mode: str = "interactive"
    expected_outputs: tuple[str, ...] = ("answer",)
    clarification_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "task_type": self.task_type,
            "capabilities": list(self.capabilities),
            "ambiguity": self.ambiguity,
            "risk": self.risk.value,
            "execution_profile": self.execution_profile.value,
            "execution_mode": self.execution_mode,
            "expected_outputs": list(self.expected_outputs),
            "clarification_question": self.clarification_question,
        }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    side_effect: SideEffect = SideEffect.READ
    required_permissions: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    max_retries: int = 2
    supports_parallel: bool = True
    idempotency_scope: str = "response_call"

    def as_openai_tool(self) -> dict[str, Any]:
        schema = _strict_object_schema(self.parameters)
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": schema,
            "strict": True,
        }


def _strict_object_schema(value: dict[str, Any] | None) -> dict[str, Any]:
    schema = dict(value or {})
    schema.setdefault("type", "object")
    properties = dict(schema.get("properties") or {})
    originally_required = set(schema.get("required") or [])
    normalized: dict[str, Any] = {}
    for name, raw_property in properties.items():
        prop = dict(raw_property or {})
        if prop.get("type") == "object":
            prop = _strict_object_schema(prop)
        elif prop.get("type") == "array" and isinstance(prop.get("items"), dict):
            items = dict(prop["items"])
            prop["items"] = _strict_object_schema(items) if items.get("type") == "object" else items
        if name not in originally_required and isinstance(prop.get("type"), str):
            prop["type"] = [prop["type"], "null"]
        normalized[name] = prop
    schema["properties"] = normalized
    schema["required"] = list(normalized.keys())
    schema["additionalProperties"] = False
    return schema


def parse_tool_specs(raw_tools: list[dict[str, Any]]) -> list[ToolSpec]:
    """Normalize both Responses and Chat Completions function shapes."""
    specs: list[ToolSpec] = []
    for raw in raw_tools:
        raw_function = raw.get("function")
        function: dict[str, Any] = raw_function if isinstance(raw_function, dict) else raw
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        raw_extension = raw.get("opentrace")
        extension: dict[str, Any] = raw_extension if isinstance(raw_extension, dict) else {}
        level = str(extension.get("side_effect") or raw.get("side_effect") or "read")
        try:
            side_effect = SideEffect(level)
        except ValueError:
            side_effect = SideEffect.READ
        specs.append(
            ToolSpec(
                name=name,
                description=str(function.get("description") or name),
                parameters=dict(function.get("parameters") or {}),
                side_effect=side_effect,
                required_permissions=tuple(extension.get("required_permissions") or ()),
                timeout_seconds=float(extension["timeout_seconds"]) if "timeout_seconds" in extension else 30.0,
                max_retries=max(0, int(extension["max_retries"])) if "max_retries" in extension else 2,
                supports_parallel=bool(extension.get("supports_parallel", True)),
                idempotency_scope=str(extension.get("idempotency_scope") or "response_call"),
            )
        )
    return specs


@dataclass
class AgentLoopResult:
    status: str
    content: str = ""
    model: str = ""
    intent: IntentPlan | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> IntentPlan:
        try:
            risk = SideEffect(str(value.get("risk") or SideEffect.READ.value))
        except ValueError:
            risk = SideEffect.READ
        try:
            profile = ExecutionProfile(
                str(value.get("execution_profile") or ExecutionProfile.AUTO.value)
            )
        except ValueError:
            profile = ExecutionProfile.AUTO
        execution_mode = str(value.get("execution_mode") or "interactive")
        if execution_mode not in {"interactive", "background", "goal"}:
            execution_mode = "interactive"
        return cls(
            goal=str(value.get("goal") or "").strip(),
            task_type=str(value.get("task_type") or "chat"),
            capabilities=tuple(str(item) for item in value.get("capabilities") or []),
            ambiguity=str(value.get("ambiguity")) if value.get("ambiguity") else None,
            risk=risk,
            execution_profile=profile,
            execution_mode=execution_mode,
            expected_outputs=tuple(
                str(item) for item in (value.get("expected_outputs") or ["answer"])
            ),
            clarification_question=(
                str(value.get("clarification_question"))
                if value.get("clarification_question")
                else None
            ),
        )


@dataclass(frozen=True)
class ExecutionStep:
    """面向用户可见、可持久化的执行步骤，不包含模型隐藏思维链。"""

    id: str
    objective: str
    capability: str | None = None
    depends_on: tuple[str, ...] = ()
    success_criteria: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "objective": self.objective,
            "capability": self.capability,
            "depends_on": list(self.depends_on),
            "success_criteria": self.success_criteria,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    """Response 级执行计划，可随持久事件恢复和审计。"""

    goal: str
    complexity: str = "simple"
    steps: tuple[ExecutionStep, ...] = ()
    success_criteria: tuple[str, ...] = ()
    replan_limit: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "complexity": self.complexity,
            "steps": [step.to_dict() for step in self.steps],
            "success_criteria": list(self.success_criteria),
            "replan_limit": self.replan_limit,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ExecutionPlan:
        candidate_steps = value.get("steps")
        raw_steps: list[Any] = candidate_steps if isinstance(candidate_steps, list) else []
        steps: list[ExecutionStep] = []
        known_ids: set[str] = set()
        for index, raw in enumerate(raw_steps[:16], start=1):
            if not isinstance(raw, dict):
                continue
            objective = str(raw.get("objective") or "").strip()
            if not objective:
                continue
            base_id = str(raw.get("id") or f"step_{index}").strip()[:80] or f"step_{index}"
            step_id = base_id
            suffix = 2
            while step_id in known_ids:
                step_id = f"{base_id[:72]}_{suffix}"
                suffix += 1
            depends_on = tuple(
                dependency
                for dependency in (str(item).strip()[:80] for item in raw.get("depends_on") or [])
                if dependency in known_ids
            )
            steps.append(
                ExecutionStep(
                    id=step_id,
                    objective=objective[:500],
                    capability=str(raw.get("capability") or "").strip() or None,
                    depends_on=depends_on,
                    success_criteria=str(raw.get("success_criteria") or "")[:500],
                )
            )
            known_ids.add(step_id)
        complexity = str(value.get("complexity") or "simple")
        if complexity not in {"simple", "moderate", "complex"}:
            complexity = "simple"
        try:
            replan_limit = int(
                value["replan_limit"] if value.get("replan_limit") is not None else 1
            )
        except (TypeError, ValueError):
            replan_limit = 1
        return cls(
            goal=str(value.get("goal") or "").strip(),
            complexity=complexity,
            steps=tuple(steps),
            success_criteria=tuple(str(item) for item in value.get("success_criteria") or []),
            replan_limit=max(0, min(3, replan_limit)),
        )


@dataclass(frozen=True)
class PlanningDecision:
    intent: IntentPlan
    execution_plan: ExecutionPlan


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
                timeout_seconds=(
                    float(extension["timeout_seconds"]) if "timeout_seconds" in extension else 30.0
                ),
                max_retries=(
                    max(0, int(extension["max_retries"])) if "max_retries" in extension else 2
                ),
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

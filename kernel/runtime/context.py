"""
RuntimeContext — 单次认知回合的统一请求上下文。

这是流经运行时每一层的唯一真相来源：
API → Kernel → Orchestrator → Execution → Fusion → Critic。

此前，上下文在 chat.py 中约 200 行代码中临时拼装，
通过 KernelRequest.metadata 以不透明字典条目传递。RuntimeContext
用结构化、有类型、自文档化的 dataclass 取代了这种方式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeContext:
    """单次认知回合的统一、结构化上下文。

    由 chat 路由器中的 `_build_runtime_context()` 一次性构建，
    然后以引用方式流经管线的每一层。
    """

    # ── 请求标识 ──────────────────────────────────────────────────────
    request_id: str
    session_id: str
    user_id: str
    query: str  # 用户原始输入（后续可能被编排器改写）

    # ── 意图锁定 / 认知控制 ──────────────────────────────────────────
    raw_user_query: str = ""
    protected_intent: str = ""
    task_type: str = "general_qa"
    allowed_capabilities: list[str] = field(default_factory=list)
    disallowed_capabilities: list[str] = field(default_factory=list)
    intent_confidence: float = 0.0
    turn_decision: dict[str, Any] = field(default_factory=dict)
    cognitive_budget: dict[str, Any] = field(default_factory=dict)
    relevance_threshold: float = 0.35

    # ── 多轮对话 ─────────────────────────────────────────────────────
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    conversation_state: Any = None  # ConversationState 或 None

    # ── 记忆上下文（由 EvolutionMemoryRouter 预取）──────────────────
    memory_context: str = ""
    episodic_events: list[dict[str, Any]] = field(default_factory=list)

    # ── 工作空间状态（来自 WorkspaceManager.get_state_summary）──────
    workspace_state: dict[str, Any] = field(default_factory=dict)

    # ── 用户画像 / 偏好 ──────────────────────────────────────────────
    user_preferences: list[str] = field(default_factory=list)
    user_style_hints: dict[str, str | None] | None = None
    preference_context_block: str = ""
    custom_instruction_block: str = ""

    # ── 数据源绑定 ───────────────────────────────────────────────────
    data_source_context: dict[str, Any] = field(default_factory=dict)
    available_data_sources: list[dict[str, Any]] = field(default_factory=list)

    # ── 附件上下文 ───────────────────────────────────────────────────
    attachment_contexts: list[dict[str, Any]] = field(default_factory=list)

    # ── 快捷 / 强制模式 ──────────────────────────────────────────────
    force_mode: str | None = None  # 10 个 VALID_FORCE_MODES 之一，或 None
    web_enabled: bool = False
    memory_mode: str = "enabled"
    graph_controls: dict[str, Any] = field(default_factory=dict)

    # ── 对话分支 ─────────────────────────────────────────────────────
    is_branch_request: bool = False
    branch_checkpoint: dict[str, Any] | None = None
    parent_message_id: str | None = None

    # 上一轮的计划/结果，用于检查点复用
    previous_plan: Any = None
    previous_results: Any = None

    # ── 澄清上下文 ───────────────────────────────────────────────────
    clarify_context: str | None = None
    clarify_question_id: str | None = None

    # ── 技能配置 ─────────────────────────────────────────────────────
    enabled_skills: list[str] = field(default_factory=list)
    disabled_skills: list[str] = field(default_factory=list)

    # ── 安全 ──────────────────────────────────────────────────────────
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    tool_permission_token: str | None = None

    # ── 流式输出 ─────────────────────────────────────────────────────
    stream: bool = False

    # ── 链路追踪 ─────────────────────────────────────────────────────
    trace_ctx: Any = None

    # ── 自适应画像（由编排器一次性计算）──────────────────────────────
    adaptive_profile: dict[str, Any] = field(default_factory=dict)

    # ── 通用元数据（可扩展）──────────────────────────────────────────
    metadata: dict[str, Any] | None = None

    def to_metadata_dict(self) -> dict[str, Any]:
        """向后兼容：生成旧版 metadata 字典，供仍依赖它的代码使用。
        新代码应直接访问字段。"""
        return {
            "request_id": self.request_id,
            "raw_user_query": self.raw_user_query or self.query,
            "protected_intent": self.protected_intent or self.query,
            "task_type": self.task_type,
            "allowed_capabilities": self.allowed_capabilities,
            "disallowed_capabilities": self.disallowed_capabilities,
            "intent_confidence": self.intent_confidence,
            "turn_decision": self.turn_decision,
            "cognitive_budget": self.cognitive_budget,
            "relevance_threshold": self.relevance_threshold,
            "graph_controls": self.graph_controls,
            "enabled_skills": self.enabled_skills,
            "disabled_skills": self.disabled_skills,
            "user_preferences": self.user_preferences,
            "user_preference_context_block": self.preference_context_block,
            "custom_instruction_block": self.custom_instruction_block,
            "data_source_id": self.data_source_context.get("data_source_id"),
            "data_source_name": self.data_source_context.get("data_source_name"),
            "data_source_database": self.data_source_context.get("database"),
            "data_source_source_type": self.data_source_context.get("source_type"),
            "data_source_schema": self.data_source_context.get("schema"),
            "force_mode": self.force_mode,
            "clarify_context": self.clarify_context,
            "clarify_question_id": self.clarify_question_id,
            "parent_message_id": self.parent_message_id,
            "previous_plan": self.previous_plan,
            "previous_results": self.previous_results,
            "resume_mode": self.is_branch_request,
            "branch_checkpoint": self.branch_checkpoint,
            "attachment_contexts": self.attachment_contexts,
            "web_enabled": self.web_enabled,
            "memory_mode": self.memory_mode,
            "memory_context": self.memory_context,
            "history": list(self.conversation_history or []),
            **(self.metadata or {}),
        }

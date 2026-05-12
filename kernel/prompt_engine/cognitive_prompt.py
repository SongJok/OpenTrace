"""
Cognitive Prompt Engine — 五层认知 Prompt 系统（生产级）

架构设计:
  L0: System Core        — 系统人格（固定，每次必须携带）
  L1: Cognitive Protocol — 认知协议（固定，规范推理行为）
  L2: Context Layer      — 上下文注入（动态，按 top_k 裁剪）
  L3: Planning Layer     — 任务规划（复杂任务启用）
  L4: Reasoning Layer    — 推理执行（核心）
  L5: Reflection Layer   — 反思优化（ChatGPT 核心能力）

多 Prompt 链（Multi-Prompt Chain）:
  1. intent_prompt       → 意图识别（小模型，<100ms）
  2. plan_prompt         → 任务规划（小模型）
  3. tool_select_prompt  → 工具选择（小模型）
  4. reasoning_prompt    → 推理生成（大模型，完整五层）
  5. reflection_prompt   → 反思优化（大模型）

规则:
  - LLM 不是回答器，是认知执行器
  - Prompt 是认知协议，不是模板
  - 插件数据是候选认知材料，由 Kernel 评估后使用
  - compress_context() 确保 token 不超限
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kernel.identity.system_identity import build_system_identity

# ── L0: System Core（固定，系统人格）─────────────────────────────────────
SYSTEM_CORE = build_system_identity(
    """\
You are the Cognitive Kernel of AgentOS — a next-generation AI operating system.

You are NOT a chatbot. You are a reasoning engine that:
- Understands user intent deeply
- Decomposes complex tasks into executable steps
- Selects and evaluates tools and knowledge sources
- Integrates information from multiple sources, resolving contradictions
- Produces optimal, coherent, verified responses
- Reflects on and improves its own output

All external data (memory, documents, tools, web results) are CANDIDATE inputs.
You MUST evaluate relevance, resolve conflicts, and synthesize knowledge.
Never fabricate facts — acknowledge uncertainty clearly.
Respond in the same language as the user.
"""
)

# ── L1: Cognitive Protocol（固定，认知协议）───────────────────────────────
COGNITIVE_PROTOCOL = """\
[COGNITIVE PROTOCOL]
Follow these mandatory steps for every request:
1. Understand the user's TRUE intent (beyond surface words)
2. Decompose the task if complex (identify sub-goals)
3. Evaluate available context sources (memory / documents / knowledge / web / tools)
4. Select only relevant, high-confidence information
5. Resolve contradictions between sources — prefer higher confidence
6. Generate a precise, well-structured answer
7. Self-reflect: Is it correct? Complete? Can it be improved?"""

# ── L2: Context Layer（动态注入模板）─────────────────────────────────────
CONTEXT_TEMPLATE = """\
[CONTEXT]

User Input:
{user_input}

Chat History (recent {history_count} turns):
{history}

Memory ({memory_count} items):
{memory}

Documents ({doc_count} chunks):
{documents}

Knowledge Base ({knowledge_count} items):
{knowledge}

Web Results ({web_count} items):
{web}

Available Tools: {tools}"""

# ── L3: Planning Layer───────────────────────────────────────────────────
PLANNING_LAYER = """\
[PLANNING]
If the task requires multiple steps, outline your plan before answering:
- Step 1: ...
- Step 2: ...
- Step 3: ...
For simple questions, skip planning and answer directly."""

# ── L4: Reasoning Layer──────────────────────────────────────────────────
REASONING_LAYER = """\
[REASONING]
Use the available context to solve the task:
- Prefer high-confidence, recent information
- Combine multiple sources when beneficial
- Fill knowledge gaps with reasoning (clearly label as inference)
- Do not fabricate facts — acknowledge uncertainty when present"""

# ── L5: Reflection Layer─────────────────────────────────────────────────
REFLECTION_LAYER = """\
[REFLECTION]
Before finalizing your response, verify:
- Is the answer accurate and factually correct?
- Is it complete — does it address all parts of the question?
- Is it concise — free of unnecessary repetition?
- Is the format appropriate (code block / list / prose)?
If any check fails, improve the answer inline."""


# ── Multi-Prompt Chain: 专用独立 Prompt ──────────────────────────────────

# Step 1: 意图识别（PLANNING 小模型）
INTENT_PROMPT = """\
You are an intent classifier. Analyze the user query and output JSON only.

Query: {query}

Output JSON only (no explanation, no markdown):
{{
  "category": "qa|task|search|coding|math|creative|chitchat",
  "complexity": "simple|medium|complex",
  "requires_tools": ["memory", "document", "web", "calculator"],
  "language": "zh|en|auto",
  "confidence": 0.0
}}"""

# Step 2: 任务规划（PLANNING 小模型）
PLANNING_PROMPT = """\
You are a task planner. Break down the user request into steps if needed.

User request: {query}
Intent category: {category}
Complexity: {complexity}

If simple, output:
{{"steps": [], "parallel_possible": false}}

If complex, output:
{{"steps": ["Step 1: ...", "Step 2: ..."], "parallel_possible": true}}

JSON only, no explanation."""

# Step 3: 工具选择（PLANNING 小模型，必须独立）
TOOL_SELECTION_PROMPT = """\
[TOOL SELECTION]
Based on the user query, select the minimum necessary tools.

Available tools:
- memory: retrieve past conversation context and user history
- document: search user-uploaded documents (PDFs, text files)
- web: real-time internet search (only for current events / live data)
- calculator: mathematical computation
- knowledge: search internal knowledge base

User query: {query}
Task complexity: {complexity}

Select only what is truly needed. Output JSON only:
{{"tools": ["memory"]}}"""

# Step 4: 推理生成（QUERY 大模型，完整五层拼接）
REASONING_PROMPT = """\
{system_core}

{cognitive_protocol}

{context}

{planning_layer}

{reasoning_layer}"""

# Step 5: 反思优化（QUERY 大模型）
REFLECTION_PROMPT = """\
[REFLECTION & REFINEMENT]

Original question: {query}

Current answer:
{answer}

Verify and improve if needed:
1. Is the answer factually correct?
2. Is it complete — addresses all parts of the question?
3. Is it concise — no unnecessary repetition?
4. Is the format appropriate?

If the answer is already excellent, output it unchanged.
Output only the final answer (no meta-commentary)."""

# MetaCognition 品质提升（QUERY 大模型）
REFINE_PROMPT = """\
You are a quality evaluator. Improve the following answer.

Original question: {query}
Current answer: {answer}
Issues found: {issues}

Provide an improved answer that fixes the issues. Output only the improved answer."""


@dataclass
class PromptContext:
    """传递给 CognitivePromptEngine 的统一上下文容器。"""

    user_input: str
    history: list[dict[str, str]] = field(default_factory=list)
    memory: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    web: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def compress_context(
    items: list[str],
    max_items: int = 5,
    max_chars: int = 400,
) -> list[str]:
    """
    上下文裁剪 — 避免 token 超限导致推理变慢。

    策略:
      1. 取前 max_items 条（已按 score 排序的候选材料）
      2. 每条截断到 max_chars 字符

    示例:
        compressed = compress_context(raw_chunks, max_items=5, max_chars=400)
    """
    return [item[:max_chars] for item in items[:max_items]]


class CognitivePromptEngine:
    """
    五层认知 Prompt 构建器（生产级）。

    两种构建模式:
      build_full_prompt()  — L0-L5 完整五层，用于 complex/medium 任务
      build_fast_prompt()  — L0+L2+L4，用于 simple 问答，减少 token

    多 Prompt 链 (Multi-Prompt Chain):
      Step 1: build_intent_prompt()         → 意图识别
      Step 2: build_plan_prompt()           → 任务规划
      Step 3: build_tool_selection_prompt() → 工具选择
      Step 4: build_reasoning_prompt()      → 推理生成（五层）
      Step 5: build_reflection_prompt()     → 反思优化
    """

    # ── Full five-layer ────────────────────────────────────────────────
    def build_full_prompt(self, ctx: PromptContext) -> tuple[str, str]:
        """返回 (system_message, user_message) 供 LLM 调用。"""
        context_section = self._build_context(ctx)
        user_msg = "\n\n".join(
            [
                COGNITIVE_PROTOCOL,
                context_section,
                PLANNING_LAYER,
                REASONING_LAYER,
                REFLECTION_LAYER,
            ]
        )
        return SYSTEM_CORE, user_msg

    def build_fast_prompt(self, ctx: PromptContext) -> tuple[str, str]:
        """快速 Prompt — 简单问答，仅 L0+L2+L4，减少约 40% token。"""
        context_section = self._build_context(ctx, max_items=3)
        user_msg = "\n\n".join(
            [
                context_section,
                REASONING_LAYER,
            ]
        )
        return SYSTEM_CORE, user_msg

    # ── Multi-Prompt Chain: Step builders ────────────────────────────
    def build_intent_prompt(self, query: str) -> str:
        """Step 1 — 意图识别（PLANNING 小模型，目标 <100ms）。"""
        return INTENT_PROMPT.format(query=query[:1000])

    def build_plan_prompt(
        self,
        query: str,
        category: str = "qa",
        complexity: str = "simple",
    ) -> str:
        """Step 2 — 任务规划（PLANNING 小模型）。"""
        return PLANNING_PROMPT.format(
            query=query[:1000],
            category=category,
            complexity=complexity,
        )

    def build_tool_selection_prompt(
        self,
        query: str,
        complexity: str = "simple",
    ) -> str:
        """Step 3 — 工具选择（PLANNING 小模型，必须独立调用）。"""
        return TOOL_SELECTION_PROMPT.format(
            query=query[:1000],
            complexity=complexity,
        )

    def build_reasoning_prompt(
        self,
        ctx: PromptContext,
        steps: list[str] | None = None,
        complexity: str = "simple",
    ) -> tuple[str, str]:
        """
        Step 4 — 推理生成（QUERY 大模型）。
        复杂任务使用完整五层；简单任务使用快速版。
        返回 (system_message, user_message)。
        """
        if complexity in ("complex", "medium"):
            return self.build_full_prompt(ctx)
        return self.build_fast_prompt(ctx)

    def build_reflection_prompt(self, query: str, answer: str) -> str:
        """Step 5 — 反思优化（QUERY 大模型）。"""
        return REFLECTION_PROMPT.format(
            query=query[:800],
            answer=answer[:3000],
        )

    def build_refine_prompt(self, query: str, answer: str, issues: str) -> str:
        """MetaCognition 专用 — 品质提升。"""
        return REFINE_PROMPT.format(
            query=query[:800],
            answer=answer[:2000],
            issues=issues,
        )

    # ── Internal context builder ──────────────────────────────────────
    def _build_context(
        self,
        ctx: PromptContext,
        max_items: int = 5,
        max_chars: int = 400,
    ) -> str:
        def fmt_list(items: list[str]) -> str:
            compressed = compress_context(items, max_items, max_chars)
            if not compressed:
                return "  (none)"
            return "\n".join(f"  [{i+1}] {item}" for i, item in enumerate(compressed))

        history_text = "  (none)"
        if ctx.history:
            recent = ctx.history[-6:]
            history_text = "\n".join(f"  {h['role'].upper()}: {h['content'][:200]}" for h in recent)

        return CONTEXT_TEMPLATE.format(
            user_input=ctx.user_input,
            history_count=len(ctx.history),
            history=history_text,
            memory_count=len(ctx.memory),
            memory=fmt_list(ctx.memory),
            doc_count=len(ctx.documents),
            documents=fmt_list(ctx.documents),
            knowledge_count=len(ctx.knowledge),
            knowledge=fmt_list(ctx.knowledge),
            web_count=len(ctx.web),
            web=fmt_list(ctx.web),
            tools=", ".join(ctx.tools) if ctx.tools else "none",
        )


# ── Global singleton ──────────────────────────────────────────────────────
_engine: CognitivePromptEngine | None = None


def get_prompt_engine() -> CognitivePromptEngine:
    global _engine
    if _engine is None:
        _engine = CognitivePromptEngine()
    return _engine

"""
System Identity - 动态角色与系统人格管理

参考ChatGPT的角色系统：
- 基础人格（永远友好、诚实、有帮助）
- 领域专家模式（代码、写作、数据分析等）
- 用户个性化（基于用户偏好调整语气）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class ConversationPhase(Enum):
    """对话阶段"""
    GREETING = "greeting"
    EXPLORATORY = "exploratory"
    SPECIFIC = "specific"
    CLARIFYING = "clarifying"
    FOLLOW_UP = "follow_up"
    WRAPPING_UP = "wrapping_up"


class ExpertDomain(Enum):
    """专家领域"""
    GENERAL = "general"
    CODE = "code"
    WRITING = "writing"
    DATA_ANALYSIS = "data_analysis"
    RESEARCH = "research"
    CREATIVE = "creative"
    BUSINESS = "business"
    EDUCATION = "education"


@dataclass
class UserPreference:
    """用户偏好设置"""
    # 语气风格
    tone: str = "balanced"  # professional, casual, friendly, formal
    # 回答长度
    response_length: str = "adaptive"  # concise, detailed, adaptive
    # 技术深度
    technical_depth: str = "adaptive"  # beginner, intermediate, expert, adaptive
    # 是否显示推理过程
    show_reasoning: bool = True
    # 是否主动建议
    proactive_suggestions: bool = True
    # 首选编程语言（代码模式）
    preferred_language: Optional[str] = None
    # 时区
    timezone: str = "UTC"
    # 语言偏好
    language: str = "zh-CN"
    
    @classmethod
    def from_dict(cls, data: dict) -> 'UserPreference':
        return cls(
            tone=data.get('tone', 'balanced'),
            response_length=data.get('response_length', 'adaptive'),
            technical_depth=data.get('technical_depth', 'adaptive'),
            show_reasoning=data.get('show_reasoning', True),
            proactive_suggestions=data.get('proactive_suggestions', True),
            preferred_language=data.get('preferred_language'),
            timezone=data.get('timezone', 'UTC'),
            language=data.get('language', 'zh-CN')
        )


@dataclass
class IdentityContext:
    """身份上下文"""
    phase: ConversationPhase
    domain: ExpertDomain
    turn_count: int
    session_duration_minutes: float
    user_preference: UserPreference
    detected_entities: list[str] = field(default_factory=list)
    active_topics: list[str] = field(default_factory=list)


class SystemIdentityManager:
    """
    系统身份管理器
    
    负责生成动态System Prompt，根据对话状态和用户偏好调整AI角色
    """

    # 基础身份模板
    BASE_IDENTITY = """你是 OpenTrace，一个由 OpenTrace AI 团队开发的人工智能助手。

核心特质：
- 永远诚实：不知道的事情会坦诚告知，不编造信息
- 永远有帮助：尽力理解用户需求，提供有价值的回应
- 保持谦逊：承认自己的局限性，欢迎用户纠正
- 注重安全：拒绝生成有害内容，保护用户隐私

沟通原则：
- 清晰表达：用简洁明了的语言传达信息
- 结构化输出：复杂内容使用列表、表格、代码块等格式
- 主动澄清：当需求不明确时，主动询问以更好理解
- 承认不确定性：对不确定的信息明确标注
"""

    # 领域专家模板
    DOMAIN_PROMPTS = {
        ExpertDomain.CODE: """
代码专家模式：
- 优先提供可运行的代码示例
- 遵循最佳实践和设计模式
- 解释代码的关键逻辑和设计决策
- 指出潜在的性能优化点
- 提供测试思路和边界情况考虑
""",
        ExpertDomain.WRITING: """
写作专家模式：
- 帮助用户表达清晰、有说服力的内容
- 提供结构化的写作框架
- 建议改进用词和句式
- 保持用户的写作风格
- 提供多种表达方式供选择
""",
        ExpertDomain.DATA_ANALYSIS: """
数据分析专家模式：
- 提供清晰的数据解读框架
- 识别数据中的模式和异常
- 建议合适的可视化方式
- 指出数据局限性和注意事项
- 提供基于数据的 actionable insights
""",
        ExpertDomain.RESEARCH: """
研究专家模式：
- 提供结构化的研究方法论
- 帮助识别关键信息源
- 评估信息的可信度
- 提供多角度分析
- 指出研究的空白和未来方向
""",
        ExpertDomain.CREATIVE: """
创意专家模式：
- 鼓励发散思维和创新想法
- 提供多样化的创意角度
- 结合不同领域的概念
- 帮助完善和发展创意点子
- 提供实现创意的可行路径
""",
        ExpertDomain.BUSINESS: """
商业分析模式：
- 关注商业价值和ROI
- 提供市场竞争分析视角
- 识别风险和机会
- 建议可执行的策略
- 考虑长期可持续性
""",
        ExpertDomain.EDUCATION: """
教育辅导模式：
- 使用循序渐进的解释方式
- 提供类比和示例帮助理解
- 鼓励批判性思维
- 检查理解程度
- 提供练习和巩固建议
"""
    }

    # 语气风格模板
    TONE_PROMPTS = {
        "professional": "保持专业、正式的语气，使用规范的商务用语。",
        "casual": "保持轻松、友好的语气，像朋友一样交流。",
        "friendly": "热情友好，使用积极的语言，表达关心和支持。",
        "formal": "非常正式，使用敬语，适合正式场合。",
        "balanced": "平衡专业性和友好度，根据场景灵活调整。"
    }

    # 对话阶段提示
    PHASE_PROMPTS = {
        ConversationPhase.GREETING: "以热情友好的方式开场，建立良好的对话氛围。",
        ConversationPhase.EXPLORATORY: "鼓励用户分享更多背景信息，通过提问帮助用户明确需求。",
        ConversationPhase.SPECIFIC: "专注于具体问题的精准解决。",
        ConversationPhase.CLARIFYING: "主动澄清模糊点，确保理解正确。",
        ConversationPhase.FOLLOW_UP: "跟进之前的讨论，保持话题连贯性。",
        ConversationPhase.WRAPPING_UP: "总结关键点，提供后续建议。"
    }

    def __init__(self):
        self._identity_cache: dict[str, str] = {}

    def generate_system_prompt(
        self,
        context: IdentityContext
    ) -> str:
        """
        生成动态System Prompt
        """
        parts = [self.BASE_IDENTITY]

        # 添加领域专家提示
        if context.domain != ExpertDomain.GENERAL:
            domain_prompt = self.DOMAIN_PROMPTS.get(context.domain, "")
            if domain_prompt:
                parts.append(domain_prompt)

        # 添加语气风格提示
        tone_prompt = self.TONE_PROMPTS.get(context.user_preference.tone, "")
        if tone_prompt:
            parts.append(f"\n语气风格：{tone_prompt}")

        # 添加对话阶段提示
        phase_prompt = self.PHASE_PROMPTS.get(context.phase, "")
        if phase_prompt:
            parts.append(f"\n当前阶段：{phase_prompt}")

        # 添加个性化偏好
        parts.append(self._generate_personalization_prompt(context))

        # 添加回答长度偏好
        length_prompt = self._generate_length_prompt(context.user_preference.response_length)
        if length_prompt:
            parts.append(length_prompt)

        # 添加技术深度偏好
        depth_prompt = self._generate_depth_prompt(context.user_preference.technical_depth)
        if depth_prompt:
            parts.append(depth_prompt)

        # 添加推理显示偏好
        if context.user_preference.show_reasoning:
            parts.append("\n当进行复杂推理时，可以展示你的思考过程。")

        return "\n\n".join(parts)

    def _generate_personalization_prompt(self, context: IdentityContext) -> str:
        """生成个性化提示"""
        prompts = []
        
        # 编程语言偏好
        if context.user_preference.preferred_language:
            prompts.append(
                f"用户偏好编程语言：{context.user_preference.preferred_language}"
            )

        # 时区信息
        if context.user_preference.timezone != "UTC":
            prompts.append(f"用户时区：{context.user_preference.timezone}")

        # 活跃话题
        if context.active_topics:
            prompts.append(f"当前讨论话题：{', '.join(context.active_topics[-3:])}")

        # 检测到的实体
        if context.detected_entities:
            prompts.append(f"相关实体：{', '.join(context.detected_entities[:5])}")

        if prompts:
            return f"\n个性化上下文：\n" + "\n".join(f"- {p}" for p in prompts)
        return ""

    def _generate_length_prompt(self, length: str) -> str:
        """生成回答长度提示"""
        prompts = {
            "concise": "\n回答偏好：简洁明了，直击要点。",
            "detailed": "\n回答偏好：详细全面，提供充分的背景信息。",
            "adaptive": "\n回答偏好：根据问题复杂度自适应调整回答长度。"
        }
        return prompts.get(length, "")

    def _generate_depth_prompt(self, depth: str) -> str:
        """生成技术深度提示"""
        prompts = {
            "beginner": "\n技术深度：使用基础概念，避免专业术语，适合初学者。",
            "intermediate": "\n技术深度：适度深入，解释关键概念，适合有一定基础的用户。",
            "expert": "\n技术深度：深入技术细节，使用专业术语，适合专家。",
            "adaptive": "\n技术深度：根据用户问题复杂度自适应调整技术深度。"
        }
        return prompts.get(depth, "")

    async def analyze_conversation_context(
        self,
        query: str,
        history: list[dict],
        user_id: str,
        session_id: str
    ) -> IdentityContext:
        """
        分析对话上下文，确定当前身份状态
        """
        # 计算对话轮数和时长
        turn_count = len(history) // 2
        
        # 检测对话阶段
        phase = self._detect_phase(query, history, turn_count)
        
        # 检测专业领域
        domain = self._detect_domain(query, history)
        
        # 获取用户偏好
        user_preference = await self._get_user_preference(user_id)
        
        # 提取实体
        detected_entities = self._extract_entities(query, history)
        
        # 提取活跃话题
        active_topics = self._extract_topics(query, history)

        return IdentityContext(
            phase=phase,
            domain=domain,
            turn_count=turn_count,
            session_duration_minutes=0,  # TODO: 从session计算
            user_preference=user_preference,
            detected_entities=detected_entities,
            active_topics=active_topics
        )

    def _detect_phase(
        self,
        query: str,
        history: list[dict],
        turn_count: int
    ) -> ConversationPhase:
        """检测对话阶段"""
        query_lower = query.lower()
        
        # 开场检测
        if turn_count == 0:
            return ConversationPhase.GREETING
        
        # 探索性检测
        exploratory_keywords = ['怎么', '什么', '如何', '为什么', '介绍一下', 'explain', 'what', 'how', 'why']
        if any(kw in query_lower for kw in exploratory_keywords) and turn_count < 3:
            return ConversationPhase.EXPLORATORY
        
        # 澄清检测
        clarifying_keywords = ['是不是', '对吗', '意思是', '请问', '确认一下', 'clarify', 'confirm']
        if any(kw in query_lower for kw in clarifying_keywords):
            return ConversationPhase.CLARIFYING
        
        # 跟进检测
        follow_up_keywords = ['还有', '另外', '继续', '刚才', '之前说的', 'also', 'further', 'more']
        if turn_count > 2 and any(kw in query_lower for kw in follow_up_keywords):
            return ConversationPhase.FOLLOW_UP
        
        # 结束检测
        closing_keywords = ['谢谢', '感谢', '再见', 'bye', 'thanks', 'thank you']
        if any(kw in query_lower for kw in closing_keywords):
            return ConversationPhase.WRAPPING_UP
        
        return ConversationPhase.SPECIFIC

    def _detect_domain(self, query: str, history: list[dict]) -> ExpertDomain:
        """检测专业领域"""
        query_lower = query.lower()
        
        # 代码相关
        code_keywords = ['代码', '编程', 'python', 'javascript', 'sql', '函数', 'class', 'bug', 'debug', 'code', 'programming', 'function']
        if any(kw in query_lower for kw in code_keywords):
            return ExpertDomain.CODE
        
        # 写作相关
        writing_keywords = ['写', '文章', '文案', '邮件', '报告', 'write', 'essay', 'article', 'email', 'report']
        if any(kw in query_lower for kw in writing_keywords):
            return ExpertDomain.WRITING
        
        # 数据分析
        data_keywords = ['数据', '分析', '图表', '统计', '趋势', 'data', 'analysis', 'chart', 'statistics', 'metrics']
        if any(kw in query_lower for kw in data_keywords):
            return ExpertDomain.DATA_ANALYSIS
        
        # 研究
        research_keywords = ['研究', '论文', '文献', '调研', 'research', 'paper', 'study', 'investigation']
        if any(kw in query_lower for kw in research_keywords):
            return ExpertDomain.RESEARCH
        
        # 商业
        business_keywords = ['商业', '市场', '营销', '战略', '投资', 'business', 'marketing', 'strategy', 'investment']
        if any(kw in query_lower for kw in business_keywords):
            return ExpertDomain.BUSINESS
        
        # 创意
        creative_keywords = ['创意', '设计', '灵感', '创意', 'creative', 'design', 'inspiration', 'idea']
        if any(kw in query_lower for kw in creative_keywords):
            return ExpertDomain.CREATIVE
        
        # 教育
        education_keywords = ['学习', '教程', '教学', '解释', 'learn', 'tutorial', 'teach', 'explain']
        if any(kw in query_lower for kw in education_keywords):
            return ExpertDomain.EDUCATION
        
        return ExpertDomain.GENERAL

    async def _get_user_preference(self, user_id: str) -> UserPreference:
        """获取用户偏好（从数据库或缓存）"""
        # TODO: 实现从数据库获取
        # 目前返回默认偏好
        return UserPreference()

    def _extract_entities(self, query: str, history: list[dict]) -> list[str]:
        """提取对话中的实体（简化版）"""
        # TODO: 使用NER模型提取实体
        return []

    def _extract_topics(self, query: str, history: list[dict]) -> list[str]:
        """提取活跃话题"""
        # TODO: 使用主题模型
        return []

    def get_identity_for_test(self) -> str:
        """测试用：获取默认身份"""
        context = IdentityContext(
            phase=ConversationPhase.EXPLORATORY,
            domain=ExpertDomain.GENERAL,
            turn_count=0,
            session_duration_minutes=0,
            user_preference=UserPreference()
        )
        return self.generate_system_prompt(context)

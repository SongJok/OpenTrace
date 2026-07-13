"""
Reasoning Visualizer - 推理可视化

参考ChatGPT的推理展示机制，实时展示AI的思考过程
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class StepType(Enum):
    """推理步骤类型"""
    ANALYSIS = "analysis"  # 意图分析
    PLANNING = "planning"  # 任务规划
    RETRIEVING = "retrieving"  # 信息检索
    EXECUTING = "executing"  # 工具执行
    REFLECTING = "reflecting"  # 反思优化
    SYNTHESIZING = "synthesizing"  # 综合生成
    COMPLETE = "complete"  # 完成


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ToolCallStep:
    """工具调用步骤详情"""
    tool_name: str
    parameters: Dict[str, Any]
    result_preview: Optional[str] = None
    execution_time_ms: int = 0


@dataclass
class ReasoningStep:
    """推理步骤"""
    id: str
    type: StepType
    title: str
    description: str
    status: StepStatus = StepStatus.PENDING
    
    # 时间戳
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # 进度
    progress: float = 0.0  # 0-1
    
    # 工具调用（如果是执行步骤）
    tool_calls: List[ToolCallStep] = field(default_factory=list)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def mark_started(self) -> None:
        """标记开始"""
        self.status = StepStatus.IN_PROGRESS
        self.started_at = datetime.utcnow()
    
    def mark_completed(self) -> None:
        """标记完成"""
        self.status = StepStatus.COMPLETED
        self.progress = 1.0
        self.completed_at = datetime.utcnow()
    
    def mark_failed(self, error: str) -> None:
        """标记失败"""
        self.status = StepStatus.FAILED
        self.metadata["error"] = error
    
    def update_progress(self, progress: float) -> None:
        """更新进度"""
        self.progress = min(max(progress, 0.0), 1.0)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "progress": self.progress,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tool_calls": [asdict(tc) for tc in self.tool_calls],
            "metadata": self.metadata
        }


class ReasoningVisualizer:
    """推理可视化器"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.steps: List[ReasoningStep] = []
        self.current_step_id: Optional[str] = None
    
    def create_step(
        self,
        step_type: StepType,
        title: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> ReasoningStep:
        """创建新步骤"""
        step = ReasoningStep(
            id=f"step_{len(self.steps) + 1}",
            type=step_type,
            title=title,
            description=description,
            metadata=metadata or {}
        )
        self.steps.append(step)
        return step
    
    def get_current_step(self) -> Optional[ReasoningStep]:
        """获取当前步骤"""
        if self.current_step_id:
            return next((s for s in self.steps if s.id == self.current_step_id), None)
        return None
    
    def start_step(self, step_id: str) -> None:
        """开始步骤"""
        step = next((s for s in self.steps if s.id == step_id), None)
        if step:
            step.mark_started()
            self.current_step_id = step_id
    
    def complete_step(self, step_id: str) -> None:
        """完成步骤"""
        step = next((s for s in self.steps if s.id == step_id), None)
        if step:
            step.mark_completed()
            if self.current_step_id == step_id:
                self.current_step_id = None
    
    def update_step_progress(self, step_id: str, progress: float) -> None:
        """更新步骤进度"""
        step = next((s for s in self.steps if s.id == step_id), None)
        if step:
            step.update_progress(progress)
    
    def add_tool_call(
        self,
        step_id: str,
        tool_name: str,
        parameters: Dict[str, Any]
    ) -> None:
        """添加工具调用"""
        step = next((s for s in self.steps if s.id == step_id), None)
        if step:
            tool_call = ToolCallStep(
                tool_name=tool_name,
                parameters=parameters
            )
            step.tool_calls.append(tool_call)
    
    def complete_tool_call(
        self,
        step_id: str,
        tool_name: str,
        result_preview: str,
        execution_time_ms: int
    ) -> None:
        """完成工具调用"""
        step = next((s for s in self.steps if s.id == step_id), None)
        if step:
            tool_call = next(
                (tc for tc in step.tool_calls if tc.tool_name == tool_name and tc.result_preview is None),
                None
            )
            if tool_call:
                tool_call.result_preview = result_preview[:200]  # 截断预览
                tool_call.execution_time_ms = execution_time_ms
    
    def to_stream_event(self) -> Dict[str, Any]:
        """转换为流事件"""
        return {
            "type": "reasoning_steps",
            "data": {
                "session_id": self.session_id,
                "steps": [s.to_dict() for s in self.steps],
                "current_step_id": self.current_step_id
            }
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """获取摘要"""
        total_steps = len(self.steps)
        completed_steps = sum(1 for s in self.steps if s.status == StepStatus.COMPLETED)
        failed_steps = sum(1 for s in self.steps if s.status == StepStatus.FAILED)
        
        total_tool_calls = sum(len(s.tool_calls) for s in self.steps)
        
        return {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "total_tool_calls": total_tool_calls,
            "is_complete": all(s.status in [StepStatus.COMPLETED, StepStatus.FAILED] for s in self.steps)
        }


# 预定义的步骤模板
STEP_TEMPLATES = {
    StepType.ANALYSIS: {
        "title": "正在分析您的请求...",
        "description": "理解您的意图和需求"
    },
    StepType.PLANNING: {
        "title": "正在规划解决方案...",
        "description": "设计处理步骤和所需工具"
    },
    StepType.RETRIEVING: {
        "title": "正在检索相关信息...",
        "description": "从知识库和记忆中查找相关内容"
    },
    StepType.EXECUTING: {
        "title": "正在执行工具...",
        "description": "调用必要的工具获取数据"
    },
    StepType.REFLECTING: {
        "title": "正在反思和优化...",
        "description": "检查结果的准确性和完整性"
    },
    StepType.SYNTHESIZING: {
        "title": "正在综合信息...",
        "description": "整合所有信息生成最终回答"
    },
    StepType.COMPLETE: {
        "title": "处理完成",
        "description": "响应已生成"
    }
}


def create_reasoning_step(step_type: StepType, custom_title: Optional[str] = None) -> ReasoningStep:
    """创建标准推理步骤"""
    template = STEP_TEMPLATES.get(step_type, {})
    return ReasoningStep(
        id=f"step_auto_{step_type.value}",
        type=step_type,
        title=custom_title or template.get("title", ""),
        description=template.get("description", "")
    )

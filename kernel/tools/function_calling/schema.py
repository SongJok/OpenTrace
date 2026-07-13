"""
Tool Schema - 工具定义和参数schema

定义工具的结构，支持OpenAI Function Calling格式
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum
import json


class ParameterType(Enum):
    """参数类型"""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class ToolParameter:
    """
    工具参数定义
    
    支持JSON Schema格式
    """
    name: str
    description: str
    param_type: ParameterType
    required: bool = True
    # 额外约束
    enum: Optional[List[str]] = None
    default: Any = None
    # 数组项类型（当param_type为ARRAY时）
    items: Optional['ToolParameter'] = None
    # 对象属性（当param_type为OBJECT时）
    properties: Optional[Dict[str, 'ToolParameter']] = None
    # 嵌套参数定义
    nested_properties: Optional[Dict[str, Any]] = None

    def to_json_schema(self) -> dict:
        """转换为JSON Schema格式"""
        schema = {
            "type": self.param_type.value,
            "description": self.description
        }
        
        if self.enum:
            schema["enum"] = self.enum
        
        if self.default is not None:
            schema["default"] = self.default
        
        if self.param_type == ParameterType.ARRAY and self.items:
            schema["items"] = self.items.to_json_schema()
        
        if self.param_type == ParameterType.OBJECT:
            if self.properties:
                schema["properties"] = {
                    k: v.to_json_schema() for k, v in self.properties.items()
                }
            elif self.nested_properties:
                schema["properties"] = self.nested_properties
        
        return schema


@dataclass
class ToolSchema:
    """
    工具完整Schema
    """
    name: str
    description: str
    parameters: List[ToolParameter]
    # 是否支持并行调用
    supports_parallel: bool = True
    # 执行超时（秒）
    timeout_seconds: int = 30
    # 是否需要用户确认
    requires_confirmation: bool = False
    # 示例调用
    examples: List[Dict[str, Any]] = field(default_factory=list)
    # 返回schema
    return_schema: Optional[Dict[str, Any]] = None

    def to_openai_format(self) -> dict:
        """转换为OpenAI Function Calling格式"""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)
        
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

    def validate_parameters(self, parameters: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证参数是否符合schema
        
        Returns: (is_valid, error_message)
        """
        try:
            # 检查必需参数
            for param in self.parameters:
                if param.required and param.name not in parameters:
                    return False, f"Missing required parameter: {param.name}"
            
            # 检查参数类型
            for name, value in parameters.items():
                param = next((p for p in self.parameters if p.name == name), None)
                if param is None:
                    return False, f"Unknown parameter: {name}"
                
                if not self._validate_type(value, param.param_type):
                    return False, f"Invalid type for parameter {name}: expected {param.param_type.value}"
                
                # 检查enum约束
                if param.enum and value not in param.enum:
                    return False, f"Invalid value for parameter {name}: must be one of {param.enum}"
            
            return True, None
            
        except Exception as e:
            return False, str(e)

    def _validate_type(self, value: Any, expected_type: ParameterType) -> bool:
        """验证值是否符合期望类型"""
        type_map = {
            ParameterType.STRING: str,
            ParameterType.INTEGER: int,
            ParameterType.NUMBER: (int, float),
            ParameterType.BOOLEAN: bool,
            ParameterType.ARRAY: list,
            ParameterType.OBJECT: dict
        }
        
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)


@dataclass
class ToolCall:
    """
    工具调用实例
    """
    id: str
    tool_name: str
    parameters: Dict[str, Any]
    # 调用元数据
    timestamp: float
    # 调用来源消息ID
    source_message_id: Optional[str] = None

    def to_openai_format(self) -> dict:
        """转换为OpenAI格式"""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.tool_name,
                "arguments": json.dumps(self.parameters, ensure_ascii=False)
            }
        }


@dataclass
class ToolResult:
    """
    工具执行结果
    """
    tool_call_id: str
    tool_name: str
    # 执行结果
    content: Any
    # 是否成功
    success: bool
    # 错误信息（如果失败）
    error: Optional[str] = None
    # 执行时间（毫秒）
    execution_time_ms: int = 0
    # 额外元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_openai_format(self) -> dict:
        """转换为OpenAI格式"""
        content = self.content if self.success else f"Error: {self.error}"
        
        # 确保content是字符串
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.tool_name,
            "content": content
        }

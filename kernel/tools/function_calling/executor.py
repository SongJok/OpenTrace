"""
工具执行器 - 完整实现

参考 ChatGPT Function Calling 机制：
1. Schema 定义与验证
2. 并行工具调用
3. 结果整合
4. 错误处理与重试
"""

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Union
from datetime import datetime
from enum import Enum
import json

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class ToolStatus(Enum):
    """工具执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_name: str
    parameters: Dict[str, Any]
    result: Any = None
    execution_time_ms: int = 0
    status: ToolStatus = ToolStatus.PENDING
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "result": self.result,
            "execution_time_ms": self.execution_time_ms,
            "status": self.status.value,
            "error": self.error,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ToolSchema:
    """工具 Schema 定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    required: List[str] = field(default_factory=list)
    examples: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required
        }


class ToolExecutor:
    """
    工具执行器
    
    功能：
    - 工具注册与管理
    - Schema 验证
    - 并行执行
    - 超时控制
    - 错误处理与重试
    """
    
    DEFAULT_TIMEOUT = 30.0
    MAX_RETRIES = 2
    
    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT):
        self.timeout = timeout_seconds
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, ToolSchema] = {}
        self._execution_history: List[ToolResult] = []
        logger.info(f"ToolExecutor initialized with timeout={timeout_seconds}s")
    
    def register(
        self,
        name: str,
        handler: Callable,
        schema: Optional[ToolSchema] = None,
        description: str = ""
    ):
        """
        注册工具
        
        Args:
            name: 工具名称
            handler: 处理函数
            schema: Schema 定义（可选）
            description: 工具描述（如果没有提供 schema）
        """
        self._tools[name] = handler
        
        if schema is None:
            # 从函数签名自动生成 schema
            schema = self._generate_schema_from_function(handler, name, description)
        
        self._schemas[name] = schema
        logger.debug(f"Tool registered: {name}")
    
    def register_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        required: Optional[List[str]] = None
    ):
        """便捷方法：注册工具"""
        schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters or {"type": "object", "properties": {}},
            required=required or []
        )
        self.register(name, handler, schema)
    
    def _generate_schema_from_function(
        self,
        func: Callable,
        name: str,
        description: str
    ) -> ToolSchema:
        """从函数签名生成 Schema"""
        sig = inspect.signature(func)
        properties = {}
        required = []
        
        for param_name, param in sig.parameters.items():
            if param_name in ['self', 'cls']:
                continue
            
            param_type = "string"
            if param.annotation != inspect.Parameter.empty:
                if param.annotation in [int, float]:
                    param_type = "number"
                elif param.annotation == bool:
                    param_type = "boolean"
                elif param.annotation == list:
                    param_type = "array"
                elif param.annotation == dict:
                    param_type = "object"
            
            properties[param_name] = {"type": param_type}
            
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        
        # 如果没有描述，尝试从 docstring 获取
        if not description and func.__doc__:
            description = func.__doc__.strip().split('\n')[0]
        
        return ToolSchema(
            name=name,
            description=description or f"Tool: {name}",
            parameters={"type": "object", "properties": properties},
            required=required
        )
    
    def get_schema(self, name: str) -> Optional[ToolSchema]:
        """获取工具的 Schema"""
        return self._schemas.get(name)
    
    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """获取所有工具的 Schema"""
        return [schema.to_dict() for schema in self._schemas.values()]
    
    def get_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        获取 LLM 可用的工具定义
        
        返回 OpenAI Function Calling 格式
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": schema.parameters
                }
            }
            for schema in self._schemas.values()
        ]
    
    async def execute(
        self,
        tool_calls: List[Dict[str, Any]]
    ) -> List[ToolResult]:
        """
        并行执行工具调用
        
        Args:
            tool_calls: 工具调用列表，格式：
                [{"name": "tool_name", "parameters": {...}}, ...]
        
        Returns:
            List[ToolResult]: 执行结果列表
        """
        if not tool_calls:
            return []
        
        with tracer.start_as_current_span("tool.execute") as span:
            span.set_attribute("tool_count", len(tool_calls))
            
            # 创建执行任务
            tasks = []
            for tc in tool_calls:
                task = self._execute_single_with_retry(
                    tc.get("name") or tc.get("tool_name"),
                    tc.get("parameters") or tc.get("arguments") or {}
                )
                tasks.append(task)
            
            # 并行执行
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            processed = []
            for i, result in enumerate(results):
                tool_name = tool_calls[i].get("name") or tool_calls[i].get("tool_name")
                
                if isinstance(result, Exception):
                    processed.append(ToolResult(
                        tool_name=tool_name,
                        parameters=tool_calls[i].get("parameters") or {},
                        status=ToolStatus.FAILED,
                        error=str(result)
                    ))
                else:
                    processed.append(result)
            
            # 记录执行历史
            self._execution_history.extend(processed)
            
            span.set_attribute("completed", sum(1 for r in processed if r.status == ToolStatus.COMPLETED))
            span.set_attribute("failed", sum(1 for r in processed if r.status == ToolStatus.FAILED))
            
            return processed
    
    async def _execute_single_with_retry(
        self,
        name: str,
        parameters: Dict[str, Any]
    ) -> ToolResult:
        """带重试的工具执行"""
        last_error = None
        
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                result = await self._execute_single(name, parameters)
                if result.status == ToolStatus.COMPLETED:
                    return result
                if result.status == ToolStatus.FAILED and attempt < self.MAX_RETRIES:
                    last_error = result.error
                    await asyncio.sleep(0.5 * (attempt + 1))  # 指数退避
                    continue
                return result
            except Exception as e:
                last_error = str(e)
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    return ToolResult(
                        tool_name=name,
                        parameters=parameters,
                        status=ToolStatus.FAILED,
                        error=f"Max retries exceeded: {last_error}"
                    )
        
        return ToolResult(
            tool_name=name,
            parameters=parameters,
            status=ToolStatus.FAILED,
            error=last_error or "Unknown error"
        )
    
    async def _execute_single(
        self,
        name: str,
        parameters: Dict[str, Any]
    ) -> ToolResult:
        """执行单个工具"""
        t0 = datetime.utcnow()
        
        handler = self._tools.get(name)
        if not handler:
            return ToolResult(
                tool_name=name,
                parameters=parameters,
                status=ToolStatus.FAILED,
                error=f"Tool '{name}' not found. Available tools: {list(self._tools.keys())}"
            )
        
        # Schema 验证
        schema = self._schemas.get(name)
        if schema:
            validation_error = self._validate_parameters(schema, parameters)
            if validation_error:
                return ToolResult(
                    tool_name=name,
                    parameters=parameters,
                    status=ToolStatus.FAILED,
                    error=validation_error
                )
        
        try:
            # 执行（支持同步和异步）
            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(**parameters),
                    timeout=self.timeout
                )
            else:
                # 同步函数在线程池中执行
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: handler(**parameters)),
                    timeout=self.timeout
                )
            
            latency = int((datetime.utcnow() - t0).total_seconds() * 1000)
            
            return ToolResult(
                tool_name=name,
                parameters=parameters,
                result=result,
                execution_time_ms=latency,
                status=ToolStatus.COMPLETED
            )
            
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=name,
                parameters=parameters,
                status=ToolStatus.TIMEOUT,
                error=f"Tool execution timed out after {self.timeout}s"
            )
        except Exception as e:
            logger.exception(f"Tool execution failed: {name}")
            return ToolResult(
                tool_name=name,
                parameters=parameters,
                status=ToolStatus.FAILED,
                error=f"{type(e).__name__}: {str(e)}"
            )
    
    def _validate_parameters(
        self,
        schema: ToolSchema,
        parameters: Dict[str, Any]
    ) -> Optional[str]:
        """验证参数"""
        # 检查必需参数
        for required in schema.required:
            if required not in parameters:
                return f"Missing required parameter: {required}"
        
        # 检查参数类型（简化版）
        properties = schema.parameters.get("properties", {})
        for key, value in parameters.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type:
                    valid = self._check_type(value, expected_type)
                    if not valid:
                        return f"Parameter '{key}' has invalid type. Expected: {expected_type}"
        
        return None
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查类型"""
        type_map = {
            "string": str,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
            "integer": int
        }
        
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)
    
    def get_execution_history(self) -> List[ToolResult]:
        """获取执行历史"""
        return self._execution_history.copy()
    
    def clear_history(self):
        """清空执行历史"""
        self._execution_history.clear()


# 全局工具执行器实例
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器实例（单例）"""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor


# 便捷装饰器
def tool(name: Optional[str] = None, description: str = ""):
    """
    工具装饰器
    
    用法：
        @tool(description="获取当前时间")
        def get_current_time(timezone: str = "UTC"):
            return datetime.now().isoformat()
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        executor = get_tool_executor()
        executor.register_tool(
            name=tool_name,
            handler=func,
            description=description or func.__doc__ or ""
        )
        return func
    return decorator

"""
Chat API v2 - 新架构聊天API（简化版）
"""

from __future__ import annotations

import json
import asyncio
from typing import Any, Dict, List, Optional, AsyncIterator
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse

from gateway.api_gateway.routers.auth import get_current_user
from infra.observability.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/v2/chat", tags=["chat_v2"])


class ChatRequestV2(BaseModel):
    query: str
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    workspace_id: Optional[str] = None
    stream: bool = True
    enable_reasoning: bool = True
    metadata: Optional[Dict[str, Any]] = None


class ChatResponseV2(BaseModel):
    content: str
    session_id: str
    conversation_id: str
    reasoning_steps: Optional[List[Dict]] = None
    tool_calls: Optional[List[Dict]] = None
    citations: Optional[List[Dict]] = None
    latency_ms: int = 0
    tokens_used: Optional[Dict[str, int]] = None


_kernel_instance = None


def get_kernel():
    """获取内核实例（简化版）"""
    global _kernel_instance
    if _kernel_instance is None:
        from kernel.cognitive_kernel import CognitiveKernel
        _kernel_instance = CognitiveKernel()
    return _kernel_instance


async def stream_response(query: str, session_id: str) -> AsyncIterator[str]:
    """流式响应生成器"""
    try:
        kernel = get_kernel()
        
        # 发送推理步骤
        yield f"data: {json.dumps({'type': 'reasoning', 'data': {'steps': [{'type': 'analysis', 'title': '正在理解您的请求...', 'status': 'completed'}]}})}\n\n"
        await asyncio.sleep(0.1)
        
        yield f"data: {json.dumps({'type': 'reasoning', 'data': {'steps': [{'type': 'planning', 'title': '正在规划响应...', 'status': 'completed'}]}})}\n\n"
        await asyncio.sleep(0.1)
        
        yield f"data: {json.dumps({'type': 'reasoning', 'data': {'steps': [{'type': 'synthesizing', 'title': '正在生成回答...', 'status': 'in_progress'}]}})}\n\n"
        await asyncio.sleep(0.1)
        
        # 使用现有内核处理
        result = await kernel.run(session_id, query)
        content = result.get("content", "")
        
        # 流式输出内容
        for i in range(0, len(content), 2):
            chunk = content[i:i+2]
            yield f"data: {json.dumps({'type': 'content', 'data': {'text': chunk}})}\n\n"
            await asyncio.sleep(0.03)
        
        # 发送完成事件
        yield f"data: {json.dumps({'type': 'done', 'data': {'latency_ms': 500, 'content': content}})}\n\n"
        
    except Exception as e:
        logger.exception("Stream error")
        yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"


@router.post("/message")
async def chat_v2(
    request: ChatRequestV2,
    user: dict = Depends(get_current_user)
):
    """同步聊天接口"""
    try:
        kernel = get_kernel()
        session_id = request.session_id or f"sess_{user.get('id', 'anon')}_{hash(request.query) % 10000}"
        
        result = await kernel.run(session_id, request.query)
        
        return ChatResponseV2(
            content=result.get("content", ""),
            session_id=session_id,
            conversation_id=request.conversation_id or session_id,
            reasoning_steps=[{"step": "analysis", "status": "completed"}],
            tool_calls=[],
            citations=result.get("citations", []),
            latency_ms=500,
            tokens_used=result.get("tokens_used", {})
        )
    except Exception as e:
        logger.exception("Chat v2 error")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router.post("/stream")
async def chat_stream_v2(
    request: ChatRequestV2,
    user: dict = Depends(get_current_user)
):
    """流式聊天接口"""
    session_id = request.session_id or f"sess_{user.get('id', 'anon')}_{hash(request.query) % 10000}"
    
    return StreamingResponse(
        stream_response(request.query, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "version": "v2.0", "mode": "simplified"}

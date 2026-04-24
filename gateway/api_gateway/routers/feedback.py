"""
Feedback router — collect user feedback for data flywheel.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from evolution.feedback.collector import FeedbackCollector, FeedbackType
from infra.message_bus.cognitive_event_bus import cognitive_event_bus
from infra.observability.logger import get_logger
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import Feedback

logger = get_logger(__name__)
router = APIRouter()

_collector = FeedbackCollector()


class FeedbackRequest(BaseModel):
    session_id: str
    query: str
    response: str
    feedback_type: FeedbackType
    score: Optional[float] = None
    correction: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, db: AsyncSession = Depends(get_db)) -> dict:
    await _collector.collect(
        session_id=req.session_id,
        query=req.query,
        response=req.response,
        feedback_type=req.feedback_type,
        score=req.score,
        correction=req.correction,
    )

    db.add(
        Feedback(
            id=str(uuid.uuid4()),
            session_id=req.session_id,
            query=req.query,
            response=req.response,
            feedback_type=req.feedback_type.value,
            score=req.score,
            correction=req.correction,
            feedback_metadata=json.dumps({"source": "api_feedback"}, ensure_ascii=False),
        )
    )
    await db.commit()
    await cognitive_event_bus.publish(
        cognitive_event_bus.emit_feedback(
            trace_id=req.session_id,
            session_id=req.session_id,
            payload={
                "query": req.query,
                "response": req.response,
                "feedback_type": req.feedback_type.value,
                "score": req.score,
                "correction": req.correction,
                "source": "api_feedback",
            },
            source="feedback_router",
        )
    )
    return {"status": "accepted"}

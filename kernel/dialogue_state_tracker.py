"""Dialogue state tracker stub."""

from __future__ import annotations

from typing import Any


class DialogueStateTracker:

    async def track(
        self,
        query: str,
        previous_plan: Any = None,
        previous_results: Any = None,
    ) -> dict:
        return {}

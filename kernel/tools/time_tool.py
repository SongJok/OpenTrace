from __future__ import annotations

from datetime import datetime

from .base import BaseTool


class TimeTool(BaseTool):
    name = "get_current_time"
    description = "Get current system time"

    def run(self, timezone: str = "local", **kwargs) -> dict[str, object]:
        now = datetime.now()
        return {
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": int(now.timestamp()),
            "timezone": timezone,
        }

from .registry import tool_registry
from .time_tool import TimeTool
from .weather_tool import WeatherTool


def register_default_tools() -> None:
    tool_registry.register(TimeTool())
    tool_registry.register(WeatherTool())

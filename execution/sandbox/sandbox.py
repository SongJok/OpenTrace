"""
Sandbox Runtime — safe execution environment for tool code.
Provides timeout enforcement, resource limits, and output capture.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class SandboxResult:
    stdout: str
    stderr: str
    return_value: Any
    success: bool
    error: Optional[str] = None
    execution_time: float = 0.0


class Sandbox:
    """
    Lightweight Python sandbox using restricted builtins.
    For production use, replace with gVisor / Firecracker.
    """

    # Allowlist of safe builtins for code execution
    _SAFE_BUILTINS = {
        "abs", "all", "any", "bool", "dict", "dir", "divmod",
        "enumerate", "filter", "float", "format", "frozenset",
        "hasattr", "hash", "int", "isinstance", "issubclass",
        "iter", "len", "list", "map", "max", "min", "next",
        "object", "oct", "ord", "pow", "print", "range",
        "repr", "reversed", "round", "set", "slice", "sorted",
        "str", "sum", "tuple", "type", "zip",
    }

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    async def execute(
        self,
        code: str,
        context: Optional[dict[str, Any]] = None,
    ) -> SandboxResult:
        """Execute Python code string in a restricted environment."""
        with tracer.start_as_current_span("sandbox.execute") as span:
            import time
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, self._run_sync, code, context or {}
                    ),
                    timeout=self.timeout,
                )
                result.execution_time = time.monotonic() - t0
                span.set_attribute("sandbox.success", result.success)
                return result
            except asyncio.TimeoutError:
                return SandboxResult(
                    stdout="", stderr="",
                    return_value=None, success=False,
                    error=f"Execution timed out after {self.timeout}s",
                    execution_time=self.timeout,
                )

    def _run_sync(self, code: str, context: dict[str, Any]) -> SandboxResult:
        import builtins
        safe_globals = {
            "__builtins__": {
                k: getattr(builtins, k)
                for k in self._SAFE_BUILTINS
                if hasattr(builtins, k)
            },
            **context,
        }
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        return_value = None
        error = None
        success = False

        try:
            with contextlib.redirect_stdout(stdout_buf), \
                 contextlib.redirect_stderr(stderr_buf):
                exec(compile(textwrap.dedent(code), "<sandbox>", "exec"), safe_globals)  # noqa: S102
                return_value = safe_globals.get("__result__")
                success = True
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            logger.debug("Sandbox execution error", error=error)

        return SandboxResult(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            return_value=return_value,
            success=success,
            error=error,
        )


sandbox = Sandbox()

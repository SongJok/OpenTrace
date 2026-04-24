"""
KernelGuard — enforce that request handlers route through CognitiveKernel
instead of calling ModelGateway directly.
"""
from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterable

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class KernelGuardError(RuntimeError):
    pass


FORBIDDEN_PATTERNS = (
    "get_model_gateway(",
    "LLMRole.",
    ".complete(",
    ".stream(",
)


def require_kernel_entrypoint(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator marker for kernel-routed endpoints."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        logger.debug("Kernel guard check", handler=func.__name__)
        return await func(*args, **kwargs)

    return wrapper


def enforce_no_direct_model_calls(
    routers_dir: str,
    allowed_files: Iterable[str] = (),
    strict: bool = False,
) -> None:
    """
    Scan router files to ensure they don't call ModelGateway directly.
    `allowed_files` are basename exemptions (e.g. admin.py for diagnostics).
    """
    allowed = set(allowed_files)
    base = Path(routers_dir)
    violations: list[str] = []

    for file in base.glob("*.py"):
        if file.name in allowed:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except Exception:
            continue

        if any(p in text for p in FORBIDDEN_PATTERNS):
            violations.append(file.name)

    if not violations:
        logger.info("Kernel guard scan passed", routers_dir=str(base))
        return

    msg = f"Direct model-call patterns found in routers: {', '.join(sorted(violations))}"
    if strict:
        raise KernelGuardError(msg)
    logger.warning(msg)

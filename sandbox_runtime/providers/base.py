from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Any


@dataclass
class SandboxRequest:
    code: str
    session_id: str
    work_dir: Path
    timeout_seconds: float = 30.0
    packages: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    output_files: list[str] = field(default_factory=list)
    provider: str = "local_ast"
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxProvider(Protocol):
    name: str

    async def run(self, req: SandboxRequest) -> SandboxResult: ...

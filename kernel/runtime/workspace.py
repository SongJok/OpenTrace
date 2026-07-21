"""
Workspace — Isolated working environment for an agent or session.

A workspace holds temporary state (variables, files, checkpoints) scoped
to a session or turn.  WorkspaceManager handles lifecycle: create, snapshot,
restore, destroy.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Workspace:
    """Isolated working environment for a session."""

    workspace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    name: str = "default"
    state: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)  # paths to workspace files
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def set(self, key: str, value: Any) -> None:
        self.state[key] = value
        self.updated_at = datetime.now(timezone.utc)

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "session_id": self.session_id,
            "state": dict(self.state),
            "files": list(self.files),
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
        }

    def add_artifact(self, artifact: Any) -> None:
        """Store a reference to an Artifact produced during this session."""
        artifacts: list[dict[str, Any]] = self.state.setdefault("_artifacts", [])
        artifacts.append({
            "artifact_id": getattr(artifact, "artifact_id", ""),
            "name": getattr(artifact, "name", ""),
            "artifact_type": getattr(artifact, "artifact_type", "text"),
            "tags": getattr(artifact, "tags", []),
        })
        self.updated_at = datetime.now(timezone.utc)

    def get_artifacts(self) -> list[dict[str, Any]]:
        return self.state.get("_artifacts", [])


class WorkspaceManager:
    """Manage workspace lifecycle for multiple sessions."""

    def __init__(self) -> None:
        self._workspaces: dict[str, Workspace] = {}

    def get_or_create(self, session_id: str, name: str = "default") -> Workspace:
        key = f"{session_id}:{name}"
        if key not in self._workspaces:
            self._workspaces[key] = Workspace(session_id=session_id, name=name)
        return self._workspaces[key]

    def get(self, session_id: str, name: str = "default") -> Workspace | None:
        return self._workspaces.get(f"{session_id}:{name}")

    def destroy(self, session_id: str, name: str = "default") -> None:
        key = f"{session_id}:{name}"
        self._workspaces.pop(key, None)
        logger.debug("Workspace destroyed", session_id=session_id, name=name)

    def list_sessions(self) -> list[str]:
        seen: set[str] = set()
        for key in self._workspaces:
            sid = key.split(":")[0]
            seen.add(sid)
        return list(seen)

    def snapshot_session(self, session_id: str) -> dict[str, Any]:
        """Snapshot all workspaces for a session — used by RewriteEngine for context."""
        workspaces: dict[str, dict[str, Any]] = {}
        for key, ws in self._workspaces.items():
            if not key.startswith(session_id + ":"):
                continue
            name = key.split(":", 1)[1] if ":" in key else "default"
            workspaces[name] = ws.snapshot()
        return {
            "session_id": session_id,
            "workspaces": workspaces,
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_state_summary(self, session_id: str) -> dict[str, Any]:
        """Return a concise summary of workspace state for the CognitivePlanner.

        Includes artifact references and key state variables so the planner
        can reason about what already exists in the session.
        """
        workspaces: dict[str, Any] = {}
        for key, ws in self._workspaces.items():
            if not key.startswith(session_id + ":"):
                continue
            name = key.split(":", 1)[1] if ":" in key else "default"
            workspaces[name] = {
                "artifact_count": len(ws.state.get("_artifacts", [])),
                "artifact_names": [a.get("name", "") for a in ws.get_artifacts()],
                "state_keys": [k for k in ws.state if not k.startswith("_")],
            }
        return {
            "session_id": session_id,
            "active_workspace_count": len(workspaces),
            "workspaces": workspaces,
        }

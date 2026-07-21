"""
FileSandboxPlugin — session-scoped read/write/list/delete under work dir (path traversal safe).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


def _base_dir(session_id: str) -> Path:
    import tempfile

    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id or "default")[:80]
    d = Path(tempfile.gettempdir()) / "opentrace_sandbox" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def _safe_path(base: Path, rel: str) -> Path:
    p = (base / rel.lstrip("/")).resolve()
    try:
        p.relative_to(base)
    except ValueError as exc:
        raise ValueError("path escapes sandbox") from exc
    return p


def resolve_readable_sandbox_file(session_id: str, rel_path: str) -> Path:
    """供 HTTP 下载：返回沙箱内已存在文件的绝对路径，否则抛错。"""
    base = _base_dir(session_id)
    fp = _safe_path(base, rel_path)
    if not fp.is_file():
        raise FileNotFoundError(rel_path)
    return fp


def run_file_sandbox(query: str, session_id: str = "") -> str:
    with tracer.start_as_current_span("plugin.file_sandbox"):
        q = (query or "").strip()
        if not q.startswith("{"):
            return json.dumps(
                {
                    "error": "expected JSON",
                    "hint": '{"operation":"read|write|list|delete","path":"rel/path","content":"..."}',
                },
                ensure_ascii=False,
            )
        spec = json.loads(q)
        op = spec.get("operation", "list")
        path = str(spec.get("path", "") or ".")
        base = _base_dir(session_id)

        try:
            if op == "list":
                target = _safe_path(base, path)
                if not target.exists():
                    return json.dumps({"operation": op, "entries": [], "error": "not found"}, ensure_ascii=False)
                if target.is_file():
                    return json.dumps({"operation": op, "entries": [path]}, ensure_ascii=False)
                entries = sorted(
                    str(p.relative_to(base)) for p in target.rglob("*") if p.is_file()
                )
                return json.dumps({"operation": op, "entries": entries[:500]}, ensure_ascii=False)

            if op == "read":
                fp = _safe_path(base, path)
                if not fp.is_file():
                    return json.dumps({"error": "not a file", "path": path}, ensure_ascii=False)
                text = fp.read_text(encoding="utf-8", errors="replace")
                return json.dumps({"operation": op, "path": path, "content": text[:200_000]}, ensure_ascii=False)

            if op == "write":
                fp = _safe_path(base, path)
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(str(spec.get("content", "")), encoding="utf-8")
                return json.dumps({"operation": op, "ok": True, "path": path}, ensure_ascii=False)

            if op == "delete":
                fp = _safe_path(base, path)
                if fp.is_file():
                    fp.unlink()
                    return json.dumps({"operation": op, "ok": True, "path": path}, ensure_ascii=False)
                return json.dumps({"error": "not a file", "path": path}, ensure_ascii=False)

            return json.dumps({"error": f"unknown operation: {op}"}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("file_sandbox error", error=str(exc))
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

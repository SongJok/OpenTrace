"""规则引擎 — 基于 YAML 的业务规则增删改查。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from gateway.api_gateway.routers.auth import get_current_user
from infra.observability.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

RULES_DIR = Path(os.getenv("RULES_DIR", "/app/data/rules"))

# ── helpers ──────────────────────────────────────────────────────────────


def _ensure_dir() -> None:
    RULES_DIR.mkdir(parents=True, exist_ok=True)


def _rule_path(filename: str) -> Path:
    safe = os.path.basename(filename)
    if safe != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return RULES_DIR / safe


# ── endpoints ────────────────────────────────────────────────────────────


@router.get("/rules")
async def list_rules(request: Request):
    _ensure_dir()
    items = []
    for p in sorted(RULES_DIR.glob("*.yml")):
        items.append(
            {
                "filename": p.name,
                "name": p.stem,
                "size": p.stat().st_size,
                "modified_at": p.stat().st_mtime,
            }
        )
    return items


@router.get("/rules/{filename}")
async def get_rule(filename: str, request: Request):
    _ensure_dir()
    path = _rule_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rule not found")
    raw = path.read_text(encoding="utf-8")
    return {"filename": filename, "yaml_raw": raw, "name": path.stem}


@router.post("/rules")
async def create_rule(request: Request):
    _ensure_dir()
    body = await request.json()
    name = (body.get("name") or "untitled").strip()
    yaml_raw = (body.get("yaml_raw") or body.get("yaml_content") or "").strip()
    filename = name.lower().replace(" ", "_") + ".yml"
    path = _rule_path(filename)
    path.write_text(yaml_raw, encoding="utf-8")
    logger.info("Rule created", filename=filename)
    return {"filename": filename, "status": "created"}


@router.put("/rules/{filename}")
async def update_rule(filename: str, request: Request):
    _ensure_dir()
    path = _rule_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rule not found")
    body = await request.json()
    yaml_raw = (body.get("yaml_raw") or body.get("yaml_content") or "").strip()
    path.write_text(yaml_raw, encoding="utf-8")
    logger.info("Rule updated", filename=filename)
    return {"filename": filename, "status": "updated"}


@router.delete("/rules/{filename}")
async def delete_rule(filename: str):
    _ensure_dir()
    path = _rule_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Rule not found")
    path.unlink()
    logger.info("Rule deleted", filename=filename)
    return {"filename": filename, "status": "deleted"}


@router.post("/rules/generate")
async def generate_rule(request: Request):
    body = await request.json()
    name = (body.get("name") or "generated_rule").strip()
    desc = (body.get("description") or "").strip()
    trigger = (body.get("trigger") or "").strip()
    yaml_content = f"name: {name}\ntrigger: {trigger}\ndescription: {desc}\nconditions: []\nactions: []\n"
    filename = name.lower().replace(" ", "_") + ".yml"
    return {
        "filename": filename,
        "yaml_content": yaml_content,
        "rule": {
            "name": name,
            "trigger": trigger,
            "description": desc,
            "conditions": [],
            "outputs": [],
        },
    }

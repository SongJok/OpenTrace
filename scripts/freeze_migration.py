#!/usr/bin/env python3
"""在迁移内容完成后冻结校验和；CI 拒绝任何未冻结或被修改的 revision。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "alembic" / "migration_policy.json"
VERSIONS = ROOT / "alembic" / "versions"


def _revision(path: Path) -> str | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "revision" for target in node.targets
        ):
            value_node = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "revision"
        ):
            value_node = node.value
        if value_node is not None:
            return str(ast.literal_eval(value_node))
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("revision")
    args = parser.parse_args()

    matches = [path for path in VERSIONS.glob("*.py") if _revision(path) == args.revision]
    if len(matches) != 1:
        parser.error(f"expected exactly one migration for {args.revision}, got {matches}")
    path = matches[0]
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    frozen = policy["frozen_migrations"]
    if any(entry["revision"] == args.revision for entry in frozen):
        parser.error(f"revision already frozen: {args.revision}")
    frozen.append(
        {
            "revision": args.revision,
            "file": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "governed_format": "r-sequence",
            "frozen_on": date.today().isoformat(),
        }
    )
    frozen.sort(key=lambda entry: entry["file"])
    POLICY.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"frozen {args.revision}: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

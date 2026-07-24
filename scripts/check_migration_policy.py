#!/usr/bin/env python3
"""校验 Alembic 单头、冻结历史、无日期新 revision 与独立发布元数据。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "alembic" / "migration_policy.json"
RELEASES_PATH = ROOT / "alembic" / "revision_releases.json"
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
            value: Any = ast.literal_eval(value_node)
            return str(value)
    return None


def validate_policy(policy_path: Path = POLICY_PATH) -> list[str]:
    errors: list[str] = []
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    releases = json.loads(RELEASES_PATH.read_text(encoding="utf-8")).get("revisions", {})
    frozen = {entry["revision"]: entry for entry in policy["frozen_migrations"]}
    discovered: dict[str, Path] = {}

    for path in sorted(VERSIONS.glob("*.py")):
        revision = _revision(path)
        if not revision:
            continue
        if revision in discovered:
            errors.append(f"重复 revision: {revision}")
        discovered[revision] = path

    for revision, entry in frozen.items():
        path = ROOT / entry["file"]
        if not path.exists():
            errors.append(f"冻结迁移被删除: {entry['file']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            errors.append(f"冻结迁移被修改: {entry['file']}")
        if discovered.get(revision) != path:
            errors.append(f"冻结 revision/file 映射漂移: {revision}")

    pattern = re.compile(policy["new_revision_format"])
    new_sequences: list[int] = []
    for revision, path in discovered.items():
        if revision in frozen:
            entry = frozen[revision]
            if entry.get("governed_format") != "r-sequence":
                continue
        else:
            errors.append(f"迁移尚未冻结，请运行 scripts/freeze_migration.py: {revision}")
        if not pattern.fullmatch(revision):
            errors.append(f"新 revision 必须使用无日期单调格式 rNNNN_slug: {revision}")
            continue
        sequence = int(revision[1:5])
        new_sequences.append(sequence)
        metadata = releases.get(revision)
        if not isinstance(metadata, dict):
            errors.append(f"新 revision 缺少独立发布元数据: {revision}")
        elif not metadata.get("release"):
            errors.append(f"新 revision 缺少 release 字段: {revision}")
        if not path.name.startswith(revision):
            errors.append(f"迁移文件名必须以 revision 开头: {path.name}")

    if new_sequences:
        expected = list(range(1, max(new_sequences) + 1))
        if sorted(new_sequences) != expected:
            errors.append(f"新 revision 序列不连续: {sorted(new_sequences)} != {expected}")
        if policy["next_sequence"] != max(new_sequences) + 1:
            errors.append("migration_policy.next_sequence 未更新")
    elif policy["next_sequence"] != 1:
        errors.append("尚无新 revision 时 next_sequence 必须为 1")

    baseline = policy["production_baseline_revision"]
    if baseline not in discovered:
        errors.append(f"生产基线 revision 不存在: {baseline}")

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        errors.append(f"alembic heads 执行失败: {proc.stderr or proc.stdout}")
    else:
        heads = [line for line in proc.stdout.splitlines() if "(head)" in line]
        if len(heads) != 1:
            errors.append(f"Alembic 必须保持单头，当前: {heads}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    args = parser.parse_args()
    errors = validate_policy(args.policy)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("OK: Alembic 单头、冻结历史与新 revision 治理策略通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

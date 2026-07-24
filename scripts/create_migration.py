#!/usr/bin/env python3
"""按 rNNNN_slug 创建迁移，并登记独立发布元数据。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "alembic" / "migration_policy.json"
RELEASES = ROOT / "alembic" / "revision_releases.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("message", help="迁移说明，例如 add_response_trace_id")
    parser.add_argument("--release", default="unreleased", help="发布日期或版本，默认 unreleased")
    parser.add_argument("--autogenerate", action="store_true")
    args = parser.parse_args()

    slug = re.sub(r"[^a-z0-9]+", "_", args.message.lower()).strip("_")
    if not slug:
        parser.error("message 必须包含字母或数字")

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    sequence = int(policy["next_sequence"])
    revision = f"r{sequence:04d}_{slug}"
    command = [
        sys.executable,
        "-m",
        "alembic",
        "revision",
        "--rev-id",
        revision,
        "-m",
        args.message,
    ]
    if args.autogenerate:
        command.append("--autogenerate")
    subprocess.run(command, cwd=ROOT, check=True)

    releases = json.loads(RELEASES.read_text(encoding="utf-8"))
    releases.setdefault("revisions", {})[revision] = {"release": args.release}
    RELEASES.write_text(json.dumps(releases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    policy["next_sequence"] = sequence + 1
    POLICY.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"created {revision}; release={args.release}")
    print(f"完成迁移内容后运行: python scripts/freeze_migration.py {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

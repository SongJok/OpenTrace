"""将已发布知识物化为可直接用 Obsidian 打开的 Vault。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge.workspace import KnowledgeWorkspace  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--workspace-id", default="default")
    parser.add_argument("--owner-id")
    parser.add_argument("--include-raw-assets", action="store_true")
    return parser


async def _run() -> None:
    args = _parser().parse_args()
    result = await KnowledgeWorkspace().materialize(
        args.output_dir,
        tenant_id=args.tenant_id,
        workspace_id=args.workspace_id,
        owner_id=args.owner_id,
        include_raw_assets=args.include_raw_assets,
    )
    print(
        f"vault={result.root} pages={result.page_count} "
        f"relations={result.relation_count} sources={result.source_count}"
    )


if __name__ == "__main__":
    asyncio.run(_run())

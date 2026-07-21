from __future__ import annotations

import asyncio
import json
import sys

from infra.replay.manifest import build_replay_manifest, manifest_to_dict
from infra.storage.database import AsyncSessionLocal


async def _main(trace_id: str) -> int:
    async with AsyncSessionLocal() as db:
        m = await build_replay_manifest(db, trace_id)
        d = manifest_to_dict(m)

    print(f"Replay Manifest: {d['version']}")
    print(f"Trace: {d['trace_id']}  Session: {d['session_id']}")
    print(f"Decision: {d['decision_type']}  Total Latency: {d['total_latency_ms']}ms")
    print("\n=== QUERY ===")
    print(d['query'])
    print("\n=== STEPS ===")
    for i, s in enumerate(d['steps'], 1):
        print(f"[{i}] phase={s['phase']} model={s.get('model')} latency={s.get('latency_ms')}")
        out = s.get('output') or {}
        content = str(out.get('content', ''))[:300]
        if content:
            print(f"    output: {content}")
    print("\n=== FINAL RESPONSE ===")
    print(d['response'])
    print("\n=== RAW MANIFEST(JSON) ===")
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python scripts/opentrace_replay.py <trace_id>')
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(sys.argv[1])))

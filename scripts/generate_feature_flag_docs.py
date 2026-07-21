#!/usr/bin/env python3
"""Regenerate docs/FEATURE_FLAG_REGISTRY.md kernel section from infra.config.flag_registry."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "FEATURE_FLAG_REGISTRY.md"
MARKER_START = "<!-- KERNEL_REGISTRY_AUTO_START -->"
MARKER_END = "<!-- KERNEL_REGISTRY_AUTO_END -->"


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from infra.config.flag_registry import KERNEL_FLAG_REGISTRY

    rows = [
        "| Flag | 默认 | Phase | 依赖 | 影响面 |",
        "|------|------|-------|------|--------|",
    ]
    for spec in KERNEL_FLAG_REGISTRY:
        req = ", ".join(spec.requires) if spec.requires else "—"
        default = "true" if spec.default else "false"
        rows.append(
            f"| `{spec.name}` | {default} | {spec.phase} | {req} | {spec.affects} |"
        )
    block = "\n".join(rows)

    if not DOC.exists():
        header = (
            "# OpenTrace — Feature Flag 注册表（内核与数据）\n\n"
            "新增开关请在本表追加一行。完整列表见 `infra/config/settings.py` 与 `.env.example`。\n\n"
            "## 内核注册表（自动生成）\n\n"
        )
        DOC.write_text(header + MARKER_START + "\n" + block + "\n" + MARKER_END + "\n", encoding="utf-8")
        print(f"=== CREATED {DOC} ===")
        return 0

    text = DOC.read_text(encoding="utf-8")
    if MARKER_START in text and MARKER_END in text:
        before = text.split(MARKER_START)[0]
        after = text.split(MARKER_END, 1)[1]
        new_text = before + MARKER_START + "\n" + block + "\n" + MARKER_END + after
    else:
        new_text = (
            text.rstrip()
            + "\n\n## 内核注册表（自动生成）\n\n"
            + MARKER_START
            + "\n"
            + block
            + "\n"
            + MARKER_END
            + "\n"
        )
    DOC.write_text(new_text, encoding="utf-8")
    print(f"=== UPDATED {DOC} ({len(KERNEL_FLAG_REGISTRY)} flags) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
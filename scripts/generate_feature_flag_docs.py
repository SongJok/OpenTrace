#!/usr/bin/env python3
"""从高影响开关注册表生成治理文档；实验开关缺元数据时失败。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "FEATURE_FLAG_REGISTRY.md"


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from infra.config.flag_registry import (
        ENTERPRISE_CONTROL_REGISTRY,
        KERNEL_FLAG_REGISTRY,
        validate_registry_governance,
    )

    errors = validate_registry_governance()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    rows = [
        "# OpenTrace — 高影响 Feature Flag 注册表",
        "",
        "> 产品成熟度：**Alpha**。能力组合优先使用 `CAPABILITY_PROFILE`；本表只保留少量紧急熔断、迁移与实验例外。旧 Cognitive Runtime 细粒度字段仅兼容读取，不属于产品配置面。",
        "",
        "## 能力 Profile（默认组合不超过 5 套）",
        "",
        "| Profile | 内置 Agent | 用途 |",
        "|---|---|---|",
        "| `core` | tool / skills / rules | 最小 Responses 工具执行 |",
        "| `data` | core + data | DataAgent / Text2SQL |",
        "| `knowledge` | core + rag | 企业知识问答 |",
        "| `data_knowledge` | data + knowledge + web_intelligence + vision | 默认完整产品闭环 |",
        "",
        "## 公开高影响开关（自动生成）",
        "",
        "| Flag | 默认 | 阶段 | Owner | 引入版本 | 退出条件 | 最晚删除版本 | 影响面 | 依赖 |",
        "|---|---:|---|---|---|---|---|---|---|",
    ]
    for spec in KERNEL_FLAG_REGISTRY:
        requires = ", ".join(spec.requires) if spec.requires else "—"
        exit_criteria = spec.exit_criteria or "—"
        remove_by = spec.remove_by or "—"
        default = "true" if spec.default else "false"
        rows.append(
            f"| `{spec.name}` | {default} | {spec.phase} | {spec.owner} | "
            f"{spec.introduced} | {exit_criteria} | {remove_by} | {spec.affects} | {requires} |"
        )
    rows.extend(
        [
            "",
            "## 企业协议上线控制（自动生成）",
            "",
            "| Control | 默认 | 阶段 | Owner | 引入版本 | 退出条件 | 最晚删除版本 | 影响面 |",
            "|---|---:|---|---|---|---|---|---|",
        ]
    )
    for spec in ENTERPRISE_CONTROL_REGISTRY:
        default = "true" if spec.default else "false"
        rows.append(
            f"| `{spec.name}` | {default} | {spec.phase} | {spec.owner} | "
            f"{spec.introduced} | {spec.exit_criteria or '—'} | {spec.remove_by or '—'} | "
            f"{spec.affects} |"
        )
    rows.extend(
        [
            "",
            "## 治理规则",
            "",
            "- 新能力优先加入现有 Profile，不新增布尔开关。",
            "- 实验开关必须同时声明 owner、引入版本、退出条件和最晚删除版本。",
            "- deprecated 开关只用于滚动升级，禁止在新部署模板中默认开启。",
            "- `development/staging/production` 决定安全强度；`CAPABILITY_PROFILE` 决定能力集合。",
            "",
        ]
    )
    DOC.write_text("\n".join(rows), encoding="utf-8")
    print(
        f"OK: generated {DOC} ({len(KERNEL_FLAG_REGISTRY)} public flags, "
        f"{len(ENTERPRISE_CONTROL_REGISTRY)} enterprise controls)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

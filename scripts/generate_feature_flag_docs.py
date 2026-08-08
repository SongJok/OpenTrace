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
        "> 产品成熟度：**受控企业 Beta**。能力组合优先使用 `CAPABILITY_PROFILE`；本表只保留少量紧急熔断、迁移与实验例外。旧 Cognitive Runtime 细粒度字段仅兼容读取，不属于产品配置面。",
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
            "## 数据库 Schema 运行预算（非 Feature Flag）",
            "",
            "| 配置 | 默认值 | 说明 |",
            "|---|---:|---|",
            "| `DATABASE_SCHEMA_SYNC_PAGE_SIZE` | 2000 | 元数据源端每批读取行数，不影响业务 SQL 返回上限 |",
            "| `DATABASE_SCHEMA_SYNC_MAX_TABLES` | 100000 | 单数据源单次同步的表安全预算，达到后显式标记截断 |",
            "| `DATABASE_SCHEMA_SYNC_MAX_COLUMNS` | 1000000 | 单数据源单次同步的列安全预算，达到后显式标记截断 |",
            "",
            "这些数值控制不是能力开关。表目录 API 固定采用有界分页响应，不能通过提高同步预算改回一次性",
            "返回完整 Schema；生产调整预算前必须先验证 API 内存、目标数据库元数据查询和 PostgreSQL",
            "`DataSourceSchema` 体积。",
            "",
            "钉钉企业数据接入不是运行时 Feature Flag；它以 `DINGTALK_DWS_BINARY` 和有效只读认证是否可用作为显式部署门禁。未配置时同步请求失败关闭，不会回退到模拟数据或绕过企业知识/目录治理链。",
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

#!/usr/bin/env python3
"""
Migrate metrics from existing data_source_schemas.semantic_mappings JSONB
into the new metric_definitions table.

A metric in semantic_mappings is keyed by business name and has:
  { "column": "orders.paid_amount", "agg": "SUM", "definition": "..." }

Usage:
  python scripts/migrate_metrics.py --data-source-id <UUID> [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.database import SessionLocal
from infra.storage.models import DataSourceSchema, MetricDefinition


def _parse_column_ref(column_str: str) -> tuple[str | None, str | None]:
    """Parse 'table.column' or 'column' into (table, column)."""
    if "." in column_str:
        parts = column_str.split(".", 1)
        return parts[0], parts[1]
    return None, column_str


def _build_formula(column_str: str, agg: str | None) -> str:
    """Build a formula string from column reference and aggregation."""
    col = column_str.strip()
    agg_upper = (agg or "").upper().strip()

    if agg_upper in ("SUM", "COUNT", "AVG", "MAX", "MIN"):
        return f"{agg_upper}({col})"
    elif agg_upper == "COUNT_DISTINCT" or agg_upper == "COUNT DISTINCT":
        return f"COUNT(DISTINCT {col})"
    else:
        return col


def _extract_underlying_columns(column_str: str) -> list[str]:
    """Extract qualified column references."""
    return [column_str.strip()]


async def migrate_metrics(data_source_id: str, dry_run: bool = False) -> dict:
    """Migrate metrics from semantic_mappings JSONB to metric_definitions."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(DataSourceSchema).where(DataSourceSchema.data_source_id == data_source_id)
        )
        schema_row = result.scalar_one_or_none()

        if not schema_row:
            raise ValueError(f"No DataSourceSchema found for data_source_id={data_source_id}")

        mappings = schema_row.semantic_mappings or {}
        print(f"Found {len(mappings)} entries in semantic_mappings")

        migrated = 0
        skipped = 0
        dry_run_log: list[dict] = []

        for metric_name, metric_def in mappings.items():
            if not isinstance(metric_def, dict):
                print(f"  Skip '{metric_name}': not a dict (value={metric_def!r})")
                skipped += 1
                continue

            column_ref = metric_def.get("column", "")
            if not column_ref:
                print(f"  Skip '{metric_name}': missing 'column' field")
                skipped += 1
                continue

            agg = metric_def.get("agg") or metric_def.get("aggregation")
            definition = metric_def.get("definition") or metric_def.get("description", "")
            category = metric_def.get("category")
            unit = metric_def.get("unit")
            aliases_list = metric_def.get("aliases", [])
            if isinstance(aliases_list, str):
                aliases_list = [aliases_list]
            tags_list = metric_def.get("tags", [])
            if isinstance(tags_list, str):
                tags_list = [tags_list]

            formula = metric_def.get("formula") or _build_formula(column_ref, agg)
            underlying_columns = metric_def.get("underlying_columns") or _extract_underlying_columns(column_ref)

            entry = {
                "name": metric_name,
                "formula": formula,
                "underlying_columns": underlying_columns,
                "agg_function": agg,
                "business_definition": definition,
                "unit": unit,
                "category": category,
                "aliases": aliases_list,
                "tags": tags_list,
            }

            if dry_run:
                dry_run_log.append(entry)
                migrated += 1
                continue

            # Check for existing metric with same name
            result_existing = await session.execute(
                select(MetricDefinition).where(
                    MetricDefinition.data_source_id == data_source_id,
                    MetricDefinition.name == metric_name,
                )
            )
            existing = result_existing.scalar_one_or_none()

            if existing:
                print(f"  Skip '{metric_name}': already exists (id={existing.id})")
                skipped += 1
                continue

            session.add(
                MetricDefinition(
                    data_source_id=data_source_id,
                    name=metric_name,
                    aliases=aliases_list,
                    formula=formula,
                    underlying_columns=underlying_columns,
                    agg_function=agg,
                    business_definition=definition,
                    unit=unit,
                    category=category,
                    tags=tags_list,
                    status="draft",  # migrated as draft for review
                    version=1,
                )
            )
            migrated += 1

        if not dry_run:
            await session.commit()

        if dry_run:
            print("\n── Dry-run output ──")
            for entry in dry_run_log:
                print(json.dumps(entry, ensure_ascii=False, indent=2))
            print("─────────────────────")

        status = "dry-run preview" if dry_run else "committed"
        print(f"✓ {status}: {migrated} metrics migrated, {skipped} skipped")
        return {"migrated": migrated, "skipped": skipped}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate metrics from semantic_mappings")
    parser.add_argument("--data-source-id", required=True, help="UUID of the data source")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    await migrate_metrics(data_source_id=args.data_source_id, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())

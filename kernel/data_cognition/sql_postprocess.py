from __future__ import annotations

import re

from kernel.data_cognition.sql_dialect import SQLDialectSpec


class SQLPostprocessError(ValueError):
    pass


def normalize_sql_for_dialect(sql: str, dialect: SQLDialectSpec | None = None) -> str:
    text = (sql or "").strip().strip("`")
    if not text:
        raise SQLPostprocessError("empty sql")

    if dialect is None:
        return text

    lowered = text.lower()

    # Normalize top-level LIMIT/TOP-ish inconsistencies.
    if dialect.name in {"clickhouse", "doris"}:
        text = re.sub(r"\btop\s+(\d+)\b", r"LIMIT \1", text, flags=re.IGNORECASE)
    elif dialect.name == "postgres":
        text = re.sub(r"\btop\s+(\d+)\b", "", text, flags=re.IGNORECASE)

    # Make backticks compatible with postgres-style identifiers.
    if dialect.name == "postgres":
        text = text.replace("`", '"')

    # Ensure a reasonable default limit if the model forgot one.
    if " limit " not in text.lower() and dialect.name != "postgres":
        text = f"{text} LIMIT 100"

    # Clean repeated whitespace from rewrites.
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text

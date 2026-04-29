from __future__ import annotations

import re
from dataclasses import dataclass

from kernel.data_cognition.sql_dialect import SQLDialectSpec


ENGLISH_DATABASE_PATTERN = re.compile(
    r"\b(sql|query|database|schema|tables?|columns?|describe|desc|show tables|table list|list tables|table count|data source|analysis|report|stats|group by|count|sum|avg|limit)\b",
    re.IGNORECASE,
)
CHINESE_DATABASE_PATTERN = re.compile(
    r"(数据库|数据源|库下|数据表|表结构|字段|列名|几张表|多少张表|多少个表|表数量|有哪些表|有什么表|列出表|表名|查询|统计|分析|图表|条数|总数|报表|分组|近\s*\d+\s*天|最近|最新|多少|销量|订单|收入|金额)"
)
TABLE_COUNT_PATTERN = re.compile(
    r"(几张表|多少张表|多少个表|表数量|多少表|table count|how many tables)",
    re.IGNORECASE,
)
TABLE_LIST_PATTERN = re.compile(
    r"(有哪些表|有什么表|列出表|表名|show tables|table list|list tables)",
    re.IGNORECASE,
)
TABLE_SCHEMA_PATTERN = re.compile(
    r"(表结构|字段|列名|schema|columns?|describe|desc\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StructuredDatabaseQuery:
    intent: str
    sql: str
    table_name: str | None = None


def is_database_question(query: str) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    # Exclude SQL generation intent — user wants to write SQL, not execute query
    sql_gen_keywords = [
        "帮我写一段sql", "帮我写个sql", "帮我写sql",
        "写一个sql", "写一段sql", "写sql",
        "生成sql", "生成一段sql",
        "sql语句", "sql代码", "sql查询语句",
        "write a sql", "create a sql", "generate sql",
    ]
    if any(kw in text.lower() for kw in sql_gen_keywords):
        return False
    return bool(
        ENGLISH_DATABASE_PATTERN.search(text)
        or CHINESE_DATABASE_PATTERN.search(text)
    )


def _metadata_database_name(dialect: SQLDialectSpec, database_name: str) -> str:
    if dialect.name in {"postgres"}:
        return dialect.schema_name
    if dialect.name == "clickhouse":
        return (database_name or "").strip() or dialect.schema_name
    return (database_name or "").strip() or dialect.schema_name


def _pick_table_name(query: str, table_names: list[str]) -> str | None:
    if not table_names:
        return None
    lowered_query = (query or "").lower()
    for table_name in table_names:
        candidate = str(table_name or "").strip()
        if candidate and candidate.lower() in lowered_query:
            return candidate
    for table_name in table_names:
        candidate = str(table_name or "").strip()
        if candidate and not re.search(r"^(information_schema|sys|pg_|mysql\.|system\.)", candidate, re.IGNORECASE):
            return candidate
    return str(table_names[0] or "").strip() or None


def _table_count_sql(dialect: SQLDialectSpec, database_name: str) -> str:
    schema_name = _metadata_database_name(dialect, database_name)
    if dialect.name == "clickhouse":
        return f"SELECT COUNT(*) AS table_count FROM system.tables WHERE database = '{schema_name}'"
    return (
        "SELECT COUNT(*) AS table_count FROM information_schema.tables "
        f"WHERE table_schema = '{schema_name}'"
    )


def _table_list_sql(dialect: SQLDialectSpec, database_name: str) -> str:
    schema_name = _metadata_database_name(dialect, database_name)
    if dialect.name == "clickhouse":
        return (
            "SELECT name AS table_name FROM system.tables "
            f"WHERE database = '{schema_name}' "
            "ORDER BY name"
        )
    return (
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema = '{schema_name}' "
        "ORDER BY table_name"
    )


def _table_schema_sql(dialect: SQLDialectSpec, database_name: str, table_name: str) -> str:
    schema_name = _metadata_database_name(dialect, database_name)
    if dialect.name == "clickhouse":
        return (
            "SELECT table AS table_name, name AS column_name, type AS data_type "
            "FROM system.columns "
            f"WHERE database = '{schema_name}' AND table = '{table_name}' "
            "ORDER BY position"
        )
    return (
        "SELECT table_name, column_name, data_type "
        "FROM information_schema.columns "
        f"WHERE table_schema = '{schema_name}' AND table_name = '{table_name}' "
        "ORDER BY ordinal_position"
    )


def build_structured_database_query(
    query: str,
    *,
    table_names: list[str],
    database_name: str,
    dialect: SQLDialectSpec,
) -> StructuredDatabaseQuery | None:
    text = (query or "").strip()
    if not text:
        return None

    if TABLE_COUNT_PATTERN.search(text):
        return StructuredDatabaseQuery(
            intent="table_count",
            sql=_table_count_sql(dialect, database_name),
        )

    if TABLE_LIST_PATTERN.search(text):
        return StructuredDatabaseQuery(
            intent="table_list",
            sql=_table_list_sql(dialect, database_name),
        )

    if TABLE_SCHEMA_PATTERN.search(text):
        table_name = _pick_table_name(text, table_names)
        if not table_name:
            return None
        return StructuredDatabaseQuery(
            intent="table_schema",
            sql=_table_schema_sql(dialect, database_name, table_name),
            table_name=table_name,
        )

    return None

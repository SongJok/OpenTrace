from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SQLDialectSpec:
    name: str
    schema_name: str
    supports_interval_days: bool
    limit_keyword: str = 'LIMIT'


def detect_sql_dialect(source_type: str) -> SQLDialectSpec:
    t = (source_type or '').lower()
    if t == 'clickhouse':
        return SQLDialectSpec(name='clickhouse', schema_name='default', supports_interval_days=True)
    if t == 'doris':
        return SQLDialectSpec(name='doris', schema_name='default', supports_interval_days=True)
    if t in {'postgres', 'postgresql', 'pg'}:
        return SQLDialectSpec(name='postgres', schema_name='public', supports_interval_days=True)
    return SQLDialectSpec(name='mysql', schema_name='information_schema', supports_interval_days=False)


def render_time_window(dialect: SQLDialectSpec, date_column: str | None, period_days: int) -> str:
    if not date_column:
        return ''
    col = date_column
    if dialect.name == 'postgres':
        return f" WHERE {col} >= NOW() - INTERVAL '{period_days} days'"
    if dialect.name in {'clickhouse', 'doris'}:
        return f" WHERE {col} >= now() - INTERVAL {period_days} DAY"
    return f" WHERE {col} >= DATE_SUB(NOW(), INTERVAL {period_days} DAY)"

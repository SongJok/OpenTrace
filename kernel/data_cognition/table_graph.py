from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from infra.observability.metrics import (
    JOIN_PATH_DEPTH,
    JOIN_PATH_INFERENCE_SUCCESS,
    JOIN_PATH_INFERENCE_TOTAL,
)


@dataclass(frozen=True)
class JoinStep:
    left_table: str
    right_table: str
    left_key: str
    right_key: str


class TableRelationshipGraph:
    # Dialect-specific column naming patterns for heuristic JOIN matching
    DIALECT_PATTERNS = {
        'clickhouse': [
            (r'^(.*)_ids?$', r'\1_id'),   # user_ids/user_id → user_id
            (r'^(.+?)id$', r'\1_id'),      # userid → user_id
            (r'^(.*)_id$', r'\1_id'),      # user_id → user_id (identity)
        ],
        'doris': [
            (r'^(.+?)_key$', r'\1_id'),    # user_key → user_id
            (r'^(.*)_id$', r'\1_id'),
            (r'^(.+?)id$', r'\1_id'),
        ],
        'mysql': [
            (r'^(.*)_id$', r'\1_id'),
            (r'^(.+?)id$', r'\1_id'),
        ],
        'postgresql': [
            (r'^(.+?)_fk$', r'\1_id'),     # user_fk → user_id
            (r'^(.*)_id$', r'\1_id'),
            (r'^(.+?)id$', r'\1_id'),
        ],
    }
    
    EXCLUDED_COLUMNS = {
        'created_at', 'updated_at', 'deleted_at', 'created_time', 'updated_time',
        'version', 'is_deleted', 'is_active', 'status', 'type', 'category',
        'description', 'content', 'note', 'remark', 'extra', 'metadata',
        '_version', '_partition_id', '_shard_num',
        '__doris_version', '__doris_unique_key',
    }

    def __init__(self, dialect: str = 'generic') -> None:
        self.foreign_keys: dict[str, list[JoinStep]] = {}
        self.column_index: dict[str, list[str]] = {}
        self.dialect = dialect.lower()

    def register_fk(self, left_table: str, right_table: str, left_key: str, right_key: str) -> None:
        self.foreign_keys.setdefault(left_table, []).append(
            JoinStep(left_table=left_table, right_table=right_table, left_key=left_key, right_key=right_key)
        )
        self.foreign_keys.setdefault(right_table, []).append(
            JoinStep(left_table=right_table, right_table=left_table, left_key=right_key, right_key=left_key)
        )

    def register_columns(self, table_name: str, columns: list[str]) -> None:
        self.column_index[table_name] = [c.lower() for c in columns]

    def _normalize_column(self, col: str) -> str:
        """Normalize column name for comparison with dialect-specific rules."""
        col = col.lower()
        
        # Apply dialect-specific patterns in order
        patterns = self.DIALECT_PATTERNS.get(self.dialect, self.DIALECT_PATTERNS['mysql'])
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, col)
            if normalized != col:
                return normalized
        
        # Generic fallback: strip common suffixes
        col = re.sub(r'(_id|id_|_key|key_)$', '', col)
        col = re.sub(r'^tbl_', '', col)
        
        return col

    def _column_similarity(self, col_a: str, col_b: str) -> float:
        """Compute similarity with dialect-aware normalization."""
        a, b = col_a.lower(), col_b.lower()
        
        # Exact match
        if a == b:
            return 1.0
        
        # Normalize and compare
        norm_a = self._normalize_column(a)
        norm_b = self._normalize_column(b)
        if norm_a == norm_b:
            return 0.95
        
        # Handle plural/singular: user_ids ↔ user_id
        if a.rstrip('s') == b or b.rstrip('s') == a:
            return 0.9
        
        # Base name match: user_id ↔ users.id pattern
        base_a = re.sub(r'(_id|id_)$', '', a)
        base_b = re.sub(r'(_id|id_)$', '', b)
        if base_a == base_b:
            return 0.9
        
        # Substring match
        if a in b or b in a:
            return 0.7 * min(len(a), len(b)) / max(len(a), len(b))
        
        # Character-level similarity
        max_len = max(len(a), len(b))
        if max_len == 0:
            return 0.0
        matches = sum(1 for x, y in zip(a, b) if x == y)
        return matches / max_len * 0.5

    def _is_join_candidate(self, col: str) -> bool:
        """Check if column is a plausible JOIN key."""
        col_lower = col.lower()
        if col_lower in self.EXCLUDED_COLUMNS:
            return False
        if '_id' in col_lower or col_lower.endswith('id') or '_key' in col_lower or col_lower.endswith('key'):
            return True
        if self.dialect == 'clickhouse' and col_lower.startswith('_'):
            return False
        return False

    def _find_heuristic_join(self, table_a: str, table_b: str) -> Optional[JoinStep]:
        """Find JOIN step via column similarity with dialect awareness."""
        cols_a = self.column_index.get(table_a, [])
        cols_b = self.column_index.get(table_b, [])
        if not cols_a or not cols_b:
            return None

        best_score = 0.0
        best_match: Optional[tuple[str, str]] = None

        for col_a in cols_a:
            if not self._is_join_candidate(col_a):
                continue
            for col_b in cols_b:
                if not self._is_join_candidate(col_b):
                    continue
                if col_a.lower() in ('created_at', 'updated_at') and col_b.lower() in ('created_at', 'updated_at'):
                    continue
                    
                score = self._column_similarity(col_a, col_b)
                threshold = 0.75 if self.dialect in ('clickhouse', 'doris') else 0.7
                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = (col_a, col_b)

        if best_match:
            return JoinStep(
                left_table=table_a, right_table=table_b,
                left_key=best_match[0], right_key=best_match[1]
            )
        return None

    def _verify_join_semantics(self, path: list[JoinStep], schema_hint: str = "") -> bool:
        if len(path) <= 2:
            return True
        if self.dialect in ('clickhouse', 'doris') and len(path) > 3:
            return False
        if schema_hint:
            hint_tables = set(self.infer_tables_from_schema_hint(schema_hint))
            if hint_tables:
                path_tables = {step.left_table for step in path} | {path[-1].right_table}
                return path_tables.issubset(hint_tables)
        return True

    def infer_tables_from_schema_hint(self, schema_hint: str) -> list[str]:
        hint = (schema_hint or "").strip()
        if not hint:
            return []
        try:
            payload = json.loads(hint)
        except Exception:
            payload = None
        tables: list[str] = []
        if isinstance(payload, dict):
            raw_tables = payload.get("tables")
            if isinstance(raw_tables, list):
                for item in raw_tables:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("table_name") or "").strip()
                    if name:
                        tables.append(name)
                    for fk in item.get("foreign_keys", []) if isinstance(item.get("foreign_keys", []), list) else []:
                        if isinstance(fk, dict):
                            src = str(fk.get("table") or name).strip()
                            dst = str(fk.get("ref_table") or fk.get("references_table") or "").strip()
                            if src:
                                tables.append(src)
                            if dst:
                                tables.append(dst)
        else:
            for line in hint.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("table:"):
                    tables.append(line.split(":", 1)[1].strip())
                elif "(" in line and ")" in line:
                    tables.append(line.split("(", 1)[0].strip())
        return [t for t in dict.fromkeys(tables) if t]

    def find_join_path(self, table_a: str, table_b: str, schema: Optional[dict] = None, schema_hint: str = "") -> Optional[list[JoinStep]]:
        if table_a == table_b:
            JOIN_PATH_INFERENCE_TOTAL.labels(method="fk").inc()
            JOIN_PATH_INFERENCE_SUCCESS.labels(method="fk").inc()
            JOIN_PATH_DEPTH.observe(0)
            return []
        
        JOIN_PATH_INFERENCE_TOTAL.labels(method="fk").inc()
        queue: list[tuple[str, list[JoinStep]]] = [(table_a, [])]
        visited = {table_a}
        while queue:
            current, path = queue.pop(0)
            for step in self.foreign_keys.get(current, []):
                if step.right_table in visited:
                    continue
                next_path = path + [step]
                if step.right_table == table_b:
                    JOIN_PATH_INFERENCE_SUCCESS.labels(method="fk").inc()
                    JOIN_PATH_DEPTH.observe(len(next_path))
                    return next_path
                visited.add(step.right_table)
                queue.append((step.right_table, next_path))
        
        JOIN_PATH_INFERENCE_TOTAL.labels(method="heuristic").inc()
        heuristic_step = self._find_heuristic_join(table_a, table_b)
        if heuristic_step:
            path = [heuristic_step]
            if self._verify_join_semantics(path, schema_hint):
                JOIN_PATH_INFERENCE_SUCCESS.labels(method="heuristic").inc()
                JOIN_PATH_DEPTH.observe(len(path))
                return path
        return None

    def find_path_for_tables(self, tables: Iterable[str], schema_hint: str = "") -> list[JoinStep]:
        tables = [t for t in tables if t]
        if len(tables) < 2:
            return []
        path: list[JoinStep] = []
        current = tables[0]
        for nxt in tables[1:]:
            segment = self.find_join_path(current, nxt, schema_hint=schema_hint)
            if not segment:
                return []
            path.extend(segment)
            current = nxt
        if len(path) > 2 and not self._verify_join_semantics(path, schema_hint):
            return []
        return path

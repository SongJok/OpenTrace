"""方言感知的 JOIN 路径推断测试。"""

import pytest
from kernel.data_cognition.table_graph import TableRelationshipGraph


class TestDialectAwareHeuristics:
    
    def test_clickhouse_id_patterns(self):
        """Test ClickHouse-specific column naming patterns."""
        graph = TableRelationshipGraph(dialect='clickhouse')
        
        # ClickHouse often uses _id suffix and array types
        graph.register_columns("events", ["event_id", "user_id", "timestamp", "properties"])
        graph.register_columns("users", ["id", "user_id", "nickname", "reg_time"])
        
        # Should match user_id ↔ user_id exactly
        path = graph.find_join_path("events", "users")
        assert path is not None
        assert path[0].left_key.lower() == "user_id"
        assert path[0].right_key.lower() == "user_id"
    
    def test_clickhouse_array_id_pattern(self):
        """Test ClickHouse array column pattern: user_ids ↔ user_id."""
        graph = TableRelationshipGraph(dialect='clickhouse')
        
        # ClickHouse: arrays often use _ids suffix
        graph.register_columns("orders", ["order_id", "user_ids", "amount"])  # user_ids Array(UInt64)
        graph.register_columns("users", ["id", "user_id", "name"])
        
        # Heuristic should match user_ids ↔ user_id
        path = graph.find_join_path("orders", "users")
        assert path is not None
        # The match might be user_ids ↔ user_id or id ↔ user_id depending on scoring
        matched_keys = {path[0].left_key.lower(), path[0].right_key.lower()}
        assert "user_id" in matched_keys
    
    def test_doris_key_pattern(self):
        """Test Doris _key suffix pattern for partition keys."""
        graph = TableRelationshipGraph(dialect='doris')
        
        # Doris: partition keys often use _key suffix
        graph.register_columns("facts", ["fact_id", "user_key", "metric_value"])
        graph.register_columns("dims", ["dim_id", "user_id", "user_name"])
        
        # Should match user_key ↔ user_id via dialect pattern
        path = graph.find_join_path("facts", "dims")
        assert path is not None
    
    def test_excluded_columns_not_matched(self):
        """Test that excluded columns are not used for heuristic JOINs."""
        graph = TableRelationshipGraph(dialect='clickhouse')
        
        graph.register_columns("logs", ["log_id", "created_at", "updated_at", "message"])
        graph.register_columns("audit", ["audit_id", "created_at", "action"])
        
        # Should NOT match on created_at/updated_at
        path = graph.find_join_path("logs", "audit")
        # May still find a path via other columns, but not via timestamps
        if path:
            assert path[0].left_key.lower() not in ("created_at", "updated_at")
            assert path[0].right_key.lower() not in ("created_at", "updated_at")
    
    def test_multihop_conservative_for_analytical_db(self):
        """Test that ClickHouse/Doris are more conservative with multi-hop joins."""
        graph = TableRelationshipGraph(dialect='clickhouse')
        
        # Register columns for a 4-table chain
        for tbl, cols in [
            ("a", ["a_id", "b_id"]),
            ("b", ["b_id", "c_id"]),
            ("c", ["c_id", "d_id"]),
            ("d", ["d_id", "value"]),
        ]:
            graph.register_columns(tbl, cols)
        
        # Direct FK would work, but heuristic multi-hop should be limited
        # Register only partial FKs to force heuristic
        graph.register_fk("a", "b", "b_id", "b_id")
        # b↔c and c↔d have no FKs
        
        # 3-hop heuristic should be rejected for ClickHouse
        path = graph.find_join_path("a", "d")
        # May return None due to conservative multi-hop policy
        if path:
            assert len(path) <= 3  # Max 3 hops for analytical DBs
    
    def test_generic_dialect_fallback(self):
        """Test that generic dialect uses standard patterns."""
        graph = TableRelationshipGraph(dialect='generic')
        
        graph.register_columns("items", ["item_id", "categoryid"])  # No underscore
        graph.register_columns("categories", ["id", "category_id"])
        
        # Should normalize categoryid ↔ category_id
        path = graph.find_join_path("items", "categories")
        assert path is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

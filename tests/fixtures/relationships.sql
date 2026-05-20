-- Test fixture: Pre-defined table relationships (6 FK + 4 inferred)
-- Rows 1-6: Verified FK from information_schema
-- Rows 7-10: Inferred relationships for testing

INSERT INTO table_relationships (id, data_source_id, left_table, left_column, right_table, right_column, join_type, cardinality, amplification_risk, is_verified, usage_count, success_rate)
VALUES
-- Verified FK relationships
('r001', 'test-ds-001', 'orders', 'user_id', 'users', 'id', 'LEFT', 'N:1', 'low', true, 150, 0.98),
('r002', 'test-ds-001', 'sessions', 'user_id', 'users', 'id', 'LEFT', 'N:1', 'low', true, 200, 0.99),
('r003', 'test-ds-001', 'documents', 'user_id', 'users', 'id', 'LEFT', 'N:1', 'low', true, 80, 0.97),
('r004', 'test-ds-001', 'order_items', 'order_id', 'orders', 'id', 'INNER', 'N:1', 'medium', true, 120, 0.95),
('r005', 'test-ds-001', 'order_items', 'product_id', 'products', 'id', 'LEFT', 'N:1', 'low', true, 100, 0.96),
('r006', 'test-ds-001', 'orders', 'id', 'order_items', 'order_id', 'LEFT', '1:N', 'medium', true, 90, 0.94),

-- Inferred / unverified relationships
('r007', 'test-ds-001', 'users', 'id', 'orders', 'user_id', 'LEFT', '1:N', 'low', false, 45, 0.88),
('r008', 'test-ds-001', 'sessions', 'id', 'documents', 'user_id', 'LEFT', 'N:M', 'high', false, 10, 0.60),
('r009', 'test-ds-001', 'products', 'category', 'orders', 'status', 'LEFT', 'N:M', 'critical', false, 3, 0.20),
('r010', 'test-ds-001', 'users', 'created_at', 'sessions', 'created_at', 'LEFT', 'N:M', 'critical', false, 5, 0.15)
ON CONFLICT DO NOTHING;

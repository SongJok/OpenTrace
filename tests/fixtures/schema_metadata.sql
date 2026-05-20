-- Test fixture: Schema metadata with business annotations for 6 test tables
-- Covers time columns, metric columns, dimension columns, sensitive columns, value maps

INSERT INTO schema_metadata (id, data_source_id, table_name, column_name, business_name, semantic_type, is_time_column, is_metric_column, is_dimension_column, is_sensitive, time_grain, lifecycle_stage, sample_values)
VALUES
-- users table
('s001', 'test-ds-001', 'users', 'id', '用户ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s002', 'test-ds-001', 'users', 'name', '用户名称', 'name', false, false, true, true, NULL, NULL, ARRAY['张三', '李四', '王五']),
('s003', 'test-ds-001', 'users', 'email', '邮箱', 'name', false, false, true, true, NULL, NULL, ARRAY['user@example.com']),
('s004', 'test-ds-001', 'users', 'level', '用户等级', 'category', false, false, true, false, NULL, NULL, ARRAY['NORMAL', 'VIP', 'SVIP']),
('s005', 'test-ds-001', 'users', 'status', '账户状态', 'category', false, false, true, false, NULL, NULL, ARRAY['active', 'disabled', 'pending']),
('s006', 'test-ds-001', 'users', 'created_at', '注册时间', 'time', true, false, true, false, 'day', 'creation', NULL),
('s007', 'test-ds-001', 'users', 'updated_at', '更新时间', 'time', true, false, false, false, 'day', 'modification', NULL),

-- orders table
('s008', 'test-ds-001', 'orders', 'id', '订单ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s009', 'test-ds-001', 'orders', 'user_id', '用户ID', 'id', false, true, true, false, NULL, NULL, NULL),
('s010', 'test-ds-001', 'orders', 'paid_amount', '实付金额', 'amount', false, true, false, false, NULL, NULL, ARRAY['99.00', '199.00', '299.00']),
('s011', 'test-ds-001', 'orders', 'total_amount', '订单原价', 'amount', false, true, false, false, NULL, NULL, NULL),
('s012', 'test-ds-001', 'orders', 'cost_amount', '成本金额', 'amount', false, true, false, false, NULL, NULL, NULL),
('s013', 'test-ds-001', 'orders', 'status', '订单状态', 'category', false, false, true, false, NULL, NULL, ARRAY['pending', 'paid', 'completed', 'refunded', 'cancelled']),
('s014', 'test-ds-001', 'orders', 'created_at', '下单时间', 'time', true, false, true, false, 'day', 'creation', NULL),
('s015', 'test-ds-001', 'orders', 'updated_at', '更新时间', 'time', true, false, false, false, 'day', 'modification', NULL),

-- sessions table
('s016', 'test-ds-001', 'sessions', 'id', '会话ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s017', 'test-ds-001', 'sessions', 'user_id', '用户ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s018', 'test-ds-001', 'sessions', 'title', '会话标题', 'name', false, false, true, false, NULL, NULL, NULL),
('s019', 'test-ds-001', 'sessions', 'turn_count', '对话轮次', 'count', false, true, false, false, NULL, NULL, ARRAY['1', '3', '5', '10', '25']),
('s020', 'test-ds-001', 'sessions', 'created_at', '创建时间', 'time', true, false, true, false, 'day', 'creation', NULL),
('s021', 'test-ds-001', 'sessions', 'last_active', '最后活跃', 'time', true, false, false, false, 'day', NULL, NULL),

-- documents table
('s022', 'test-ds-001', 'documents', 'id', '文档ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s023', 'test-ds-001', 'documents', 'user_id', '上传用户ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s024', 'test-ds-001', 'documents', 'filename', '文件名', 'name', false, false, true, false, NULL, NULL, NULL),
('s025', 'test-ds-001', 'documents', 'file_size', '文件大小', 'count', false, true, false, false, NULL, NULL, ARRAY['1024', '20480', '1048576']),
('s026', 'test-ds-001', 'documents', 'mime_type', '文件类型', 'category', false, false, true, false, NULL, NULL, ARRAY['application/pdf', 'text/plain', 'image/png']),
('s027', 'test-ds-001', 'documents', 'created_at', '上传时间', 'time', true, false, true, false, 'day', 'creation', NULL),

-- products table
('s028', 'test-ds-001', 'products', 'id', '产品ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s029', 'test-ds-001', 'products', 'name', '产品名称', 'name', false, false, true, false, NULL, NULL, NULL),
('s030', 'test-ds-001', 'products', 'category', '产品分类', 'category', false, false, true, false, NULL, NULL, ARRAY['电子产品', '服装', '食品']),
('s031', 'test-ds-001', 'products', 'price', '单价', 'amount', false, true, false, false, NULL, NULL, NULL),
('s032', 'test-ds-001', 'products', 'stock', '库存', 'count', false, true, false, false, NULL, NULL, NULL),
('s033', 'test-ds-001', 'products', 'created_at', '创建时间', 'time', true, false, true, false, 'day', 'creation', NULL),

-- order_items table
('s034', 'test-ds-001', 'order_items', 'id', '明细ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s035', 'test-ds-001', 'order_items', 'order_id', '订单ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s036', 'test-ds-001', 'order_items', 'product_id', '产品ID', 'id', false, false, true, false, NULL, NULL, NULL),
('s037', 'test-ds-001', 'order_items', 'quantity', '数量', 'count', false, true, false, false, NULL, NULL, ARRAY['1', '2', '5']),
('s038', 'test-ds-001', 'order_items', 'unit_price', '成交单价', 'amount', false, true, false, false, NULL, NULL, NULL),
('s039', 'test-ds-001', 'order_items', 'subtotal', '小计', 'amount', false, true, false, false, NULL, NULL, NULL)
ON CONFLICT DO NOTHING;

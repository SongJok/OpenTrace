-- Test fixture: 20+ pre-defined metrics for integration testing
-- Covers SUM, COUNT, AVG, MAX, MIN, COUNT_DISTINCT, and composite formulas

INSERT INTO metric_definitions (id, data_source_id, name, aliases, formula, underlying_columns, agg_function, business_definition, unit, category, tags, status, version)
VALUES
-- Revenue metrics
('m001', 'test-ds-001', 'GMV', ARRAY['营收', '交易额', '总成交额'], 'SUM(orders.paid_amount) FILTER (WHERE orders.status NOT IN (''refunded'', ''cancelled''))', ARRAY['orders.paid_amount', 'orders.status'], 'SUM', '实付金额求和，排除退款和取消订单', '元', '营收', ARRAY['核心指标', '日报'], 'published', 3),
('m002', 'test-ds-001', 'ARPU', ARRAY['客单价', '人均消费'], 'SUM(orders.paid_amount) / COUNT(DISTINCT orders.user_id)', ARRAY['orders.paid_amount', 'orders.user_id'], NULL, '每用户平均消费金额', '元', '营收', ARRAY['核心指标'], 'published', 2),
('m003', 'test-ds-001', '付费用户数', ARRAY['付费人数', 'paying_users'], 'COUNT(DISTINCT orders.user_id) FILTER (WHERE orders.paid_amount > 0)', ARRAY['orders.user_id', 'orders.paid_amount'], 'COUNT_DISTINCT', '有实付金额的去重用户数', '人', '用户', ARRAY['核心指标', '日报'], 'published', 2),
('m004', 'test-ds-001', '订单数', ARRAY['订单量', 'order_count'], 'COUNT(orders.id)', ARRAY['orders.id'], 'COUNT', '订单总数（含所有状态）', '笔', '订单', ARRAY['核心指标', '日报'], 'published', 1),
('m005', 'test-ds-001', '退款率', ARRAY['refund_rate'], 'COUNT(orders.id) FILTER (WHERE orders.status = ''refunded'') * 100.0 / NULLIF(COUNT(orders.id), 0)', ARRAY['orders.id', 'orders.status'], NULL, '退款订单占总订单的百分比', '%', '订单', ARRAY['质量指标'], 'published', 1),

-- User metrics
('m006', 'test-ds-001', '新注册用户数', ARRAY['新用户', 'new_users'], 'COUNT(users.id) FILTER (WHERE users.created_at >= CURRENT_DATE - INTERVAL ''7 days'')', ARRAY['users.id', 'users.created_at'], 'COUNT', '最近7天新注册的用户数', '人', '用户', ARRAY['日报'], 'published', 1),
('m007', 'test-ds-001', 'DAU', ARRAY['日活', '日活跃用户'], 'COUNT(DISTINCT sessions.user_id) FILTER (WHERE sessions.created_at::date = CURRENT_DATE)', ARRAY['sessions.user_id', 'sessions.created_at'], 'COUNT_DISTINCT', '当天有会话的去重用户数', '人', '用户', ARRAY['核心指标', '日报'], 'published', 2),
('m008', 'test-ds-001', 'MAU', ARRAY['月活', '月活跃用户'], 'COUNT(DISTINCT sessions.user_id) FILTER (WHERE date_trunc(''month'', sessions.created_at) = date_trunc(''month'', CURRENT_DATE))', ARRAY['sessions.user_id', 'sessions.created_at'], 'COUNT_DISTINCT', '当月有会话的去重用户数', '人', '用户', ARRAY['核心指标', '月报'], 'published', 1),
('m009', 'test-ds-001', '次日留存率', ARRAY['day1_retention', '次日留存'], 'COUNT(DISTINCT CASE WHEN d2.user_id IS NOT NULL THEN d1.user_id END) * 100.0 / NULLIF(COUNT(DISTINCT d1.user_id), 0)', ARRAY['users.id'], NULL, '注册次日回访的用户比例', '%', '用户', ARRAY['核心指标'], 'published', 2),

-- Content metrics
('m010', 'test-ds-001', '文档上传数', ARRAY['上传文档数', 'doc_uploads'], 'COUNT(documents.id)', ARRAY['documents.id'], 'COUNT', '用户上传的文档总数', '个', '内容', ARRAY['周报'], 'published', 1),
('m011', 'test-ds-001', '会话数', ARRAY['对话数', 'session_count'], 'COUNT(sessions.id)', ARRAY['sessions.id'], 'COUNT', '用户发起的对话会话总数', '次', '内容', ARRAY['日报'], 'published', 1),
('m012', 'test-ds-001', '平均会话轮次', ARRAY['avg_turns'], 'AVG(sessions.turn_count)', ARRAY['sessions.turn_count'], 'AVG', '每个会话的平均对话轮次', '轮', '内容', ARRAY['周报'], 'draft', 1),

-- Composite / advanced
('m013', 'test-ds-001', '总营收', ARRAY['total_revenue'], 'SUM(orders.paid_amount) FILTER (WHERE orders.status = ''completed'')', ARRAY['orders.paid_amount', 'orders.status'], 'SUM', '已完成订单的实付金额总计', '元', '营收', ARRAY['财报'], 'published', 1),
('m014', 'test-ds-001', '毛利率', ARRAY['gross_margin'], '(SUM(orders.paid_amount) - SUM(orders.cost_amount)) * 100.0 / NULLIF(SUM(orders.paid_amount), 0)', ARRAY['orders.paid_amount', 'orders.cost_amount'], NULL, '毛利占营收的百分比', '%', '营收', ARRAY['财报'], 'draft', 1),
('m015', 'test-ds-001', '转化率', ARRAY['conversion_rate', '付费转化率'], 'COUNT(DISTINCT orders.user_id) * 100.0 / NULLIF(COUNT(DISTINCT users.id), 0)', ARRAY['orders.user_id', 'users.id'], NULL, '注册用户中有过付费行为的用户比例', '%', '用户', ARRAY['核心指标'], 'published', 3),
('m016', 'test-ds-001', '复购率', ARRAY['repurchase_rate'], 'COUNT(DISTINCT CASE WHEN user_orders.order_count >= 2 THEN user_orders.user_id END) * 100.0 / NULLIF(COUNT(DISTINCT user_orders.user_id), 0)', ARRAY['orders.user_id'], NULL, '有2次及以上付费的用户比例', '%', '用户', ARRAY['月报'], 'published', 1),

-- Time-series metrics
('m017', 'test-ds-001', '周环比增长率', ARRAY['WoW_growth'], '(SUM(orders.paid_amount) FILTER (WHERE orders.created_at >= CURRENT_DATE - INTERVAL ''7 days'') - SUM(orders.paid_amount) FILTER (WHERE orders.created_at BETWEEN CURRENT_DATE - INTERVAL ''14 days'' AND CURRENT_DATE - INTERVAL ''7 days'')) * 100.0 / NULLIF(SUM(orders.paid_amount) FILTER (WHERE orders.created_at BETWEEN CURRENT_DATE - INTERVAL ''14 days'' AND CURRENT_DATE - INTERVAL ''7 days''), 0)', ARRAY['orders.paid_amount', 'orders.created_at'], NULL, '本周GMV相对于上周的变化率', '%', '营收', ARRAY['周报'], 'published', 1),
('m018', 'test-ds-001', '同比增长率', ARRAY['YoY_growth', '同比'], '(SUM(orders.paid_amount) FILTER (WHERE orders.created_at >= date_trunc(''year'', CURRENT_DATE)) - SUM(orders.paid_amount) FILTER (WHERE orders.created_at >= date_trunc(''year'', CURRENT_DATE - INTERVAL ''1 year'') AND orders.created_at < date_trunc(''year'', CURRENT_DATE))) * 100.0 / NULLIF(SUM(orders.paid_amount) FILTER (WHERE orders.created_at >= date_trunc(''year'', CURRENT_DATE - INTERVAL ''1 year'') AND orders.created_at < date_trunc(''year'', CURRENT_DATE)), 0)', ARRAY['orders.paid_amount', 'orders.created_at'], NULL, '今年至今GMV相对于去年同期的变化率', '%', '营收', ARRAY['月报', '季报'], 'published', 1),

-- Safety / edge-case metrics (deprecated)
('m019', 'test-ds-001', '旧版GMV', ARRAY['old_gmv'], 'SUM(orders.total_amount)', ARRAY['orders.total_amount'], 'SUM', '已废弃的旧版GMV计算方式', '元', '营收', ARRAY['废弃'], 'deprecated', 2),
('m020', 'test-ds-001', '留存率(7日)', ARRAY['day7_retention'], 'COUNT(DISTINCT CASE WHEN d7.user_id IS NOT NULL THEN d1.user_id END) * 100.0 / NULLIF(COUNT(DISTINCT d1.user_id), 0)', ARRAY['users.id'], NULL, '注册7日后仍活跃的用户比例', '%', '用户', ARRAY['周报'], 'draft', 1),

-- Sensitivity-tagged metrics
('m021', 'test-ds-001', 'VIP用户GMV', ARRAY['vip_gmv'], 'SUM(orders.paid_amount) FILTER (WHERE users.level = ''VIP'')', ARRAY['orders.paid_amount', 'users.level'], 'SUM', 'VIP等级用户的GMV总和', '元', '营收', ARRAY['敏感'], 'published', 1)
ON CONFLICT DO NOTHING;

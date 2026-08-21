# Production Intelligence 受控上线手册

## 适用范围

本手册用于将 Production、Data、Config、RAG 四类在线能力和 Connector Gateway 放量到
staging 或生产租户。外部系统权限、网络和 Secret Manager 由部署方提供；代码
完整不等于这些组织级前置条件已完成。

## 上线前检查

- 使用托管 PostgreSQL/Redis，完成备份恢复和 Worker 接管演练。
- 配置 `CAPABILITY_PROFILE=production_intelligence`，为 API 和 Worker 使用同一能力拓扑版本。
- 轮换 `APP_SECRET_KEY`、`JWT_SECRET`、`DATA_SECRET_KEY`，连接器只填写 Secret 引用。
- 开启受信租户上下文和 RLS，限制 CORS、Ingress、NetworkPolicy 和对外 egress。
- 确认 OTel Collector、Prometheus 告警、审计保留和事件响应负责人。
- 在 staging 使用真实主链输出跑八类 Production Intelligence 评测。

## 升级顺序

1. 备份数据库，记录当前应用镜像、拓扑 manifest 和 Alembic head。
2. 执行迁移到 `r0033_config_intelligence_invariants`，确认只有一个 head，然后检查新增业务表的
   tenant/workspace 索引、RLS 策略，以及 `response_approvals.required_approvals` 和
   `approval_decisions` 字段及人数约束；同时确认每个配置资产只有一个 published 策略、每个
   资产/环境只有一个 current 快照。
3. 为每个 Connector 评审 `runtime_policy`，并验证 Redis 限流库可用；写 Connector 必须
   声明下游幂等支持，且演练控制存储故障时的失败关闭。
4. 先更新 API，再更新 Worker；期间 API 只提交命令，不在请求进程执行新能力。
5. 验证 `/api/v1/health/deps`、Worker 租约领取、SSE 续传、证据事件和审批恢复。
6. 先放量资产图和只读 Connector，再放量 Config 校验，最后才放量需审批的生产操作。

## 连接器上线节奏

1. 以 `disabled` 状态创建目录，只声明当前需要的最小操作集。
2. 导入资产与关系，核对 service/repository/deployment/config/database/owner 连边。
3. 使用 staging 身份测试超时、脱敏、输出上限、证据可定位性和拒绝路径。
4. 启用后观察 connector execution 计数、延迟、错误和证据数量，有异常立即停用目录。
5. 对写操作单独演练审批、断线恢复、执行后验证与 reconciliation；删除、回滚和生产变更必须
   用两个不同账号完成，验证第一份批准不唤醒 Worker，第二份批准才恢复执行，同一账号重复批准
   不计数。

CMDB/Git/Kubernetes 等资产源通过 `/production/asset-graph/sync` 提交稳定的
`Idempotency-Key`、游标和 `source_key`。首次权威同步前先以非权威模式核对差异；
`adopt_existing` 会转移资产所有权，只能在人工审计后开启。

## 回滚

- 优先停用具体 Connector 或将 `CAPABILITY_PROFILE` 退回 `data_knowledge`，然后滚动重启
  API 和 Worker。
- 不删除 Response、Event、Approval、Tool Ledger 或 Evidence，以保留恢复和审计能力。
- 不在紧急回滚中执行 Alembic downgrade。旧版应忽略新表；结构回退需独立备份和变更窗口。
- 已进入 `reconciliation` 的生产操作必须人工核对下游真实状态，不得重新点击执行。
- 监控 `pending_secondary` 数量与最老等待时长；超过 30 分钟的破坏性请求必须重新确认时效，
  不得通过同账号重复批准、复制请求或调整数据库字段绕过四眼审批。

## 放量成功标准

- 无租户越权、无重复副作用、无明文凭据或未脱敏输出。
- 高影响结论包含结论、证据、置信度、影响和建议；缺证时稳定进入无法确认。
- 破坏性生产动作不存在单账号执行记录，审批复核队列不存在超时积压。
- 八类真实场景评测达到组织设定门槛，安全拒绝用例 100% 通过。
- P95/P99 延迟、Connector 错误率、Evidence Gate 拒绝率和 reconciliation 积压符合 SLO。

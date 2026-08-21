# Production Intelligence 需求追踪矩阵

## 1. 改造前审计基线

| 需求域 | 当前状态 | 关键差距 | 目标落点 |
| --- | --- | --- | --- |
| Responses 可恢复执行 | 已有，主路径稳定 | 无 | 保持 API/Worker 边界 |
| Intent/Planner | 已有严格工具调用规划 | 只认识 Data/RAG | 扩展受控生产与配置意图 |
| IAM/Policy | 有租户、资源 ACL、审批 | 角色与连接器操作矩阵不完整 | 统一 Capability Policy |
| Capability Router | 有可信目录与发现 | 在线白名单仅 Data/RAG | Manifest 驱动的最小能力集 |
| Data | 已有受治理 DataAgent | 需要关联资产与影响估算 | 复用，不开放任意 SQL |
| Knowledge | 已有 RAG、企业上下文、公司 Skill | 缺生产资产关联 | 作为 Knowledge 能力与上下文 |
| Observability | 有平台自身 OTel/Prometheus | 没有外部可查询连接器 | Connector + 标准 Evidence |
| Code/Git/CI/CD/Business | 目录为空 | 无连接器契约和实现 | MCP/Native 双通道 |
| Production Asset Graph | 无在线事实模型 | 诊断依赖猜测 | PostgreSQL 资产与关系表 |
| Evidence | 有 Response 内证据账本 | 只覆盖五源问答，未标准化生产证据 | Evidence v2 + 持久化投影 |
| Fusion/Critic | 旧 Runtime 有多个实现 | 未接 Responses 主路径且规则不完整 | Worker 主路径的确定性审查 |
| Config Intelligence | 无 | 缺 Schema/规则/历史/容量/Dry Run | Config Policy 与验证运行 |
| Web Workspace | 有 Chat/Data/Knowledge 页面 | 无资产、连接器、诊断页面 | Production Workspace |

## 1.1 本次实现验收状态

| 交付项 | 实现状态 | 验收入口 |
| --- | --- | --- |
| Production Asset Graph | 已实现范围化 CRUD、邻域查询和原子批量导入 | `/api/v2/production/assets`、`/asset-graph` |
| Connector Gateway | 已实现 MCP v2、Native SDK、目录白名单、Policy、脱敏、超时、证据与审计 | `connectors/`、生产智能控制台 |
| 四类 Tier-1 能力 | Production、Data、Config、RAG 已进入 Manifest/bootstrap/worker 单一拓扑 | `agent_topology_manifest.yaml` v5 |
| Evidence/Fusion/Critic | 已实现生产证据持久化、冲突/时效/环境检查和标准答案契约 | Response Evidence Ledger |
| Config Intelligence | 已实现严格封闭 Schema、规则、历史、容量、冲突、可核验 dry-run，以及唯一已发布策略/当前快照 | `/api/v2/production/config-assets/*`、`r0033_config_intelligence_invariants` |
| 受治理生产操作 | 已实现 action catalog、持久审批、破坏性操作双人四眼、服务端参数绑定、幂等账本和执行后验证 | `execute_production_action`、`r0032_four_eye_production_approvals` |
| Connector 运行韧性 | 已实现分布式滑窗限流、并发租约、熔断/半开、读降级/写失败关闭和下游幂等透传 | `connectors/runtime.py`、`connectors/gateway.py` |
| 资产长期同步 | 已实现来源所有权、游标连续性、持久租约、请求幂等、权威退役和失败事实 | `asset_sync.py`、`r0031_production_asset_sync_runtime` |
| 历史与容量校验 | 已实现 P05/P25/P50/P75/P95 历史基线、倍率/波动阈值和受限容量公式 | `config_intelligence.py` |
| Web Workspace | 已实现管理员资产、连接器、策略和验证工作台 | `/production-intelligence` |

企业内部 Git、Observability、CI/CD、CMDB、配置中心和业务 API 的凭据与资源级 ACL 属于
部署方集成项，通过已实现的 Connector 契约接入，不在开源仓库中伪造真实凭据。

## 2. 用户场景与验收证据

| 场景 | 必要步骤 | 最低证据要求 | 失败行为 |
| --- | --- | --- | --- |
| 线上 Bug | 业务事实→Trace→日志→部署/代码 | 业务事实 + 运行时证据 | 明确缺少哪一环 |
| 业务查询 | 指标→语义→SQL→校验→执行 | 指标定义 + SQL + 结果快照 | 不生成估算数字 |
| 配置检查 | Schema→规则→历史→容量→Dry Run | 规则版本 + 快照 + 校验结果 | 禁止直接发布 |
| 发布问题 | Deployment→Diff→错误率→Trace | 部署版本 + 观测变化 | 仅表述相关而非因果 |
| 系统异常 | Metric→Trace→Log→依赖 | 至少两个独立信号 | 降低置信度 |
| 客服问题 | 用户状态→资格→配置→领取→错误 | 用户范围授权 + 业务记录 | 脱敏或拒绝 |
| 运营问题 | 漏斗→配置→流量→服务 | 聚合数据 + 配置/运行证据 | 不泄露用户明细 |
| 产品问题 | SLI/SLO→Metric→Trace→数据 | SLO 定义 + 当前观测 | 不以单个日志判断健康 |

## 3. 不可回归的项目约束

1. PostgreSQL 是 Response、Item、Event、Approval、Tool Ledger 和资产关系的事实来源。
2. Redis 只用于投递与唤醒，不能成为证据或执行状态的唯一来源。
3. 所有资源读取同时验证 user、tenant、workspace 与数据分类。
4. 副作用操作使用持久化审批和幂等账本；破坏性操作必须由两个不同账号批准；未知结果进入 reconciliation。
5. 模型统一通过 Model Gateway；连接器统一通过 Connector Gateway。
6. Tier-1 拓扑只通过 Manifest 扩展，并同步 bootstrap、worker 和合约测试。
7. 企业认知、公司 Skill、个人记忆继续由 ContextAssembler 注入，不注册成自由调用 Agent。
8. API 请求进程不得使用 background task 执行模型或外部工具。

## 4. Definition of Done

- 每个需求都有模型、服务、API/Worker 接入、迁移、测试、文档和可观测性中的适用项。
- 新增 API 有租户越权、角色拒绝、输入边界、幂等与审计测试。
- 新增 Connector 有契约、超时、结果上限、脱敏、风险级别与故障语义测试。
- 新增 Evidence 有环境、版本、时间、来源、权限、哈希与冲突测试。
- 所有配置变更同步配置真相文档；所有迁移保持单头并通过幂等验证。
- `python -m pytest -q`、架构边界脚本、前端 `npm test` 和 `npm run build` 通过。

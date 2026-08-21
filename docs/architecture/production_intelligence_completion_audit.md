# Production Intelligence 完整需求复核

本文把需求附件的十七个主题和企业入口流程图逐项映射到当前代码事实。它是发布验收清单，
不是愿景文档；“已实现”仅表示仓库具备可执行实现和回归入口，真实供应商网络、账号、凭据与
资源级 ACL 仍必须由部署方在 staging 验证。

## 流程图端到端映射

| 流程层 | 当前实现 | 关键事实与验收入口 |
| --- | --- | --- |
| WorkBuddy / Web / 企业 IM | Web Workspace 已接主链；外部渠道统一提交 Responses 命令 | `frontend/src/`、`POST /api/v2/responses`；渠道不得旁路执行 |
| Enterprise AI Gateway | 身份、租户、工作区、资源范围、幂等与持久 Outbox | `gateway/api_gateway/routers/responses.py`、`infra/responses/` |
| Intent / Planner | 严格 `IntentPlan`、最小能力发现、依赖执行图和恢复检查点 | `kernel/agent_loop/runner.py`、`intent_policy.py`、`contracts.py` |
| IAM / Policy | 默认拒绝的角色/领域/风险/分类矩阵；写操作持久审批 | `services/production_intelligence/policy.py`、`response_aux.py` |
| Capability Router | Manifest 是 Production、Data、Config、RAG 在线资格单一真相 | `kernel/agent_runtime/agent_topology_manifest.yaml` v5 |
| Data | 受治理草案、候选、静态校验、EXPLAIN、只读执行和验证 | `agents/data_agent.py`、`data_agent/`、`services/sql_assets.py` |
| Observability | Connector 操作目录统一接 metric/log/trace/alert/incident 证据；内置真实 Prometheus 查询 | `connectors/`、`agents/production_agent.py` |
| Knowledge | RAG 返回引用证据；企业认知、公司 Skill、个人记忆按上下文注入 | `agents/rag_agent.py`、`knowledge/`、`kernel/agent_loop/context.py` |
| Code / Git / CI/CD | MCP/Native 双通道、封闭输入 Schema、允许操作交集与服务端参数绑定 | `connectors/mcp.py`、`connectors/sdk/native.py`、`actions.py` |
| Business / Config | 业务 Connector、资产关系、确定性配置规则、历史、容量与 dry-run | `asset_graph.py`、`config_intelligence.py`、`agents/config_agent.py` |
| Evidence / Critic | 标准证据、范围/时间/环境/冲突检查；只有 `pass` 可满足门禁 | `evidence_critic.py`、`kernel/agent_loop/evidence.py` |

## 附件十七项逐条复核

| # | 需求主题 | 实现结论 | 代码与测试证据 |
| ---: | --- | --- | --- |
| 1 | 八类员工问题 | 已覆盖生产 Bug、问数、配置、发布、系统、客服、运营、产品评测样本，并另设十类失败关闭对抗用例 | `evals/datasets/production_intelligence.jsonl`、`evals/datasets/production_intelligence_security.jsonl`、`evals/runner.py` |
| 2 | AI Control Plane 自主掌握 | 已保持 Responses Worker 为唯一模型/工具执行面，MCP 不是平台中心 | Responses 路由、Worker 与 AgentLoop 合约测试 |
| 3 | MCP 的正确定位 | 已实现本地可信目录、MCP JSON-RPC、证据归一化、审计与超时 | `connectors/contracts.py`、`mcp.py`、`gateway.py` |
| 4 | 不全部 MCP 化 | 已提供 Native SDK/entry point 与真实 Prometheus 适配器；MCP 与原生适配器共用治理边界 | `connectors/sdk/native.py`、`prometheus.py`、`bootstrap.py` |
| 5 | 线上 Bug Agent | 已实现资产收敛、依赖步骤、跨源证据和高影响回答协议 | `agents/production_agent.py`、`production_tools.py` |
| 6 | Production Asset Graph | 已实现范围化节点/边、原子导入、来源所有权、游标、租约和权威退役 | `asset_graph.py`、`asset_sync.py`、迁移 r0029/r0031 |
| 7 | 不开放任意 execute_sql | 已复用 DataAgent 治理链，仅执行已验证候选且保持只读/审批账本 | `agents/data_agent.py`、`sql_draft_policy.py` |
| 8 | Config Intelligence | 已实现 Schema、引用、业务规则、冲突、历史、容量与受控 dry-run | `config_intelligence.py`、`agents/config_agent.py` |
| 9 | 历史成功配置 | 已提供 P05/P25/P50/P75/P95 基线、倍率与波动阈值；拒绝无样本猜测 | 配置智能服务和 foundation tests |
| 10 | 精简 Agent 拓扑 | 在线仅四类 Tier-1 能力，企业上下文不注册为自由调用 Agent | 拓扑 manifest、bootstrap/worker 合约测试 |
| 11 | 可恢复 Runtime | 已用 PostgreSQL 事实、Outbox、租约、检查点和 SSE 序列恢复长流程 | `infra/responses/`、Responses contract tests |
| 12 | 统一 Observability | 已提供平台与 Connector 指标、OTel spans、SLO 和 Prometheus 告警 | `infra/observability/`、`deploy/observability/prometheus-rules.yml` |
| 13 | Evidence Engine | 已持久化 source/asset/environment/time/authority/hash，并执行 Critic 门禁 | `ProductionEvidence`、`evidence_critic.py`、evidence tests |
| 14 | 权限从第一天设计 | 默认只读/拒绝；生产写审批；破坏性操作由两个不同账号批准并审计 | `policy.py`、ResponseApproval、迁移 r0032、审批合约测试 |
| 15 | 推荐技术栈 | 保持 React/FastAPI/PostgreSQL/Redis/OTel；OPA/CUE/Temporal 作为部署扩展边界 | ADR 004、平台架构文档 |
| 16 | 分阶段交付 | 三阶段能力均进入同一主链；上线仍按只读、配置、生产写顺序渐进放量 | `docs/runbooks/production_intelligence_rollout.md` |
| 17 | 最终架构选择 | Data、Production、Config 与 Knowledge 复用统一 Capability/Evidence/Policy/Runtime | 主 manifest、AgentLoop 与管理工作台 |

## 非演示化与开放扩展边界

- 仓库不伪造 Git、APM、Kubernetes、配置中心或业务系统结果。未配置真实连接器时，目录为空
  或调用失败关闭；证据缺失时 Critic 返回 `blocked/incomplete`。
- Native Adapter 与 Secret Resolver 只从显式 allowlist entry point 加载，缺失、冲突或非法
  注册会在启动时失败；默认 Secret Resolver 只接受 `env://` 引用。
- Connector 执行具备 Redis 原子滑窗限流、分布式并发租约、熔断/半开；控制存储故障时仅
  只读可按策略降级，任何写操作失败关闭。
- 副作用一旦可能触达下游，超时、适配器错误或返回后验证失败都进入 reconciliation，绝不
  伪装成可安全自动重试的普通失败。
- 开源仓库提供协议、治理、扩展点和本地回归；真实供应商客户端、商业凭据、网络 egress、
  RLS 与组织审批职责属于部署配置，不能用假数据替代验收。

## 发布判定

完成发布前必须同时通过：迁移单头与不可变策略、架构/import 边界、静默失败扫描、后端全量
pytest、前端全量 Vitest 与 TypeScript build、公开发布检查、企业评测，以及 staging 中带真实
连接器的最小权限、恢复、故障注入和四眼审批演练。演练入口会恢复目标服务并输出脱敏、不可
覆盖的审计证据，但真实 staging 结果仍必须由发布负责人归档。任何一项缺失都只能判定为“代码已就绪，
部署未验收”，不能宣称生产完成。

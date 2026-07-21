# OpenTrace — 能力成熟度（对外与 README 对齐）

| 模块 | 状态 | 说明 |
|------|------|------|
| vNext 主路径（Supervisor + Gateway + Executive） | **生产** | 契约测试覆盖 |
| V5 路由（L0/L1/语义缓存） | **生产** | 启发式 + 小模型 |
| RAG Agent + 混合检索/Rerank | **生产** | 需 pgvector + Key |
| DataAgent V2 核心（Intent→SQL→Verify） | **生产** | Supervisor + DAG |
| DataAgent V2 Phase4（insight/stat/viz） | **auto/stub 混合** | `data_agent_v2_advanced_analytics_mode` |
| Memory Fabric + Redis graph | **生产**（单集群） | 跨进程 World Model ⚠️ |
| Agent Runtime V3（Manifest / Contribution / UnifiedEvidence） | **生产** | DAG + Executive + Worker 统一 invoke；`attach_evidence_objects` 热路径 |
| Data 凭据解密 | **生产** | `infra/security/data_source_secrets`（Agent/API 共用，无 gateway 依赖） |
| Agent Bus 资格门控 | **生产** | manifest `bus_eligible`；`rules` 仅进程内 |
| RuntimeContribution（统一 evidence/goal/memory/world/risks） | **生产** | `runtime_contribution.py` + executor trace |
| CognitiveStateGraph（Goal→Evidence→Memory→World） | **生产**（单集群 + Redis 可选） | `bus.apply_runtime_contribution_to_bus` 单写；`KERNEL_COGNITIVE_STATE_GRAPH_PERSIST_ENABLED` / `turn_envelope` 见 `docs/architecture/turn_envelope_field_mapping.md` |
| Tier-1 vision / skills / rules | **生产** | manifest 3.1.0 + bootstrap；rules 仅 API 进程 |
| Web 单轨（web_intelligence） | **生产** | legacy `web` bootstrap off，alias 解析到 WI |
| Capability Intelligence P1/P2 | **生产** | 可 flag 关闭降本 |
| Cognitive Replay | **生产** | 审计向 |
| V4 Orchestrator | **legacy** | 默认关闭 |
| `context_composer` / DST / reference_resolver | **部分 stub** | 不影响主路径 |
| `file_parser.parse_attachment_content` | **stub** | 附件多模态部分可用 |

更新本表时同步 README「当前能力」一节。
# OpenTrace 产品愿景

## 定位

OpenTrace 是面向企业数据、知识与生产系统的受治理提问平台。用户进入平台后首先看到提问页，
围绕七类受治理信息获得可解释答案：个人记忆、企业大脑上下文、公司上传 Skill、RAG 检索、
DataAgent、Production 生产证据和 Config 确定性校验。

普通员工以统一提问页为主工作面；管理员使用 Production Intelligence 控制台维护资产、连接器、
配置策略、同步运行与四眼审批。治理事实仍统一进入 Responses、审计、Evidence 与工具账本，
控制台不能成为旁路执行面。

## 产品主链

```text
用户提问
  -> Responses API 持久化 Response / Event / Outbox
  -> Worker 租约领取与可恢复 Agent Loop
  -> ContextAssembler 注入授权企业大脑上下文
  -> ContextAssembler 召回与问题相关的公司上传 Skill 业务片段
  -> ContextAssembler 按当前用户边界召回个人记忆
  -> IntentPlan 选择最小充分的 RAG / DataAgent / Production / Config 组合并在 Loop 中迭代
  -> Production/Config 通过 Connector Gateway、资产图和确定性 Critic 收敛外部不可信数据
  -> DataAgent 草案经用户明确选择后进入持久审批、执行、验证和受控学习
  -> PostgreSQL 持久化答案、引用、SQL 与运行事件
  -> SSE 流式返回并支持断点续传
```

企业大脑只提供当前用户可见的公司、部门和术语上下文，不替代企业知识库或实时数据库；公司 Skill
提供从线上实现预先蒸馏并审核的流程、表结构、字段语义和代码规则，但不代表数据库当前记录；
个人记忆只提供当前 user/tenant/workspace 下的稳定偏好与已确认事实；RAG 返回带引用的已发布
知识；DataAgent 先找到公司认可的指标和可信数据源，再研究业务规则、规划并验证 SQL；Production
只使用通过范围、时效、环境和冲突检查的线上证据；Config 只使用已发布策略、版本化快照和可核验
dry-run。聊天中
首次问数只生成草案；用户明确选择候选并完成持久审批后，系统重新校验 Schema 和语义版本，
执行 EXPLAIN 与只读查询，验证结果后返回带本次结果证据的答案，并只学习完整验证通过的模式。

每个 Response 的意图不只记录“调用哪个 Agent”，还持久化七类来源需求、事实新鲜度、证据要求
和问数阶段。这样恢复、审批和审计都能区分稳定个人上下文、企业上下文、已发布文档证据、当前或
历史数据事实，并严格区分 `research_and_draft`、`select_candidate`、`execute_and_verify`：
草案阶段永远不能被表述为已经得到业务数字，只有执行与结果验证完成后才形成最终数据答案。

意图规划默认先利用当前 Response 父链、已确认个人记忆、企业认知、企业大脑、公司 Skill、附件
和个人业务状态补全省略信息。规划器错误地要求用户重新提供平台已有资料时，确定性策略会消解该
澄清；缺少制度或文档证据但 RAG 可用时，先执行受治理只读检索，而不是把检索工作转给用户。
每轮处理结果记录在 `context_manifest.intent_resolution`，包含可用上下文来源、只读研究能力、
澄清是否被消解及原因。只有互斥候选必须由用户选择、关键目标或范围确实缺失、来源冲突、权限
不足，以及写入或破坏性操作可能作用于错误对象时，系统才保留一个最小必要澄清问题。SQL 候选
选择和审批阶段始终属于必须保留的用户决定，不能被上下文自动替代。

## 产品页面

普通用户可访问：提问、我的资料、数据库、个人记忆、任务、Skills、设置。

管理员额外可访问：企业大脑、企业知识库、知识库质量中心、Production Intelligence、权限。

所有其他旧入口均已移除，未知前端路径回到提问页，非管理员访问管理员路径会回到提问页。

## 工程原则

- PostgreSQL 是 Response、Item、Event、Outbox、审批和工具账本的事实来源。
- API 只提交命令，模型和工具只在 Worker 中执行。
- 资源查询同时受 user、tenant、workspace 和数据源授权约束。
- 企业大脑、RAG 和 DataAgent 均通过统一 Model Gateway 与 Agent Loop 执行。
- 只读能力自动执行；任何未来写能力都必须经过持久化审批和幂等账本。
- 任何能力收敛都必须同时删除用户入口、API 暴露、Worker 循环和运行时注册。

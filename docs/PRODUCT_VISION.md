# OpenTrace 产品愿景

## 定位

OpenTrace 是面向企业数据与知识的受治理提问系统。用户进入平台后首先看到提问页，围绕
三类能力获得可解释答案：RAG 检索、企业大脑上下文和 DataAgent/Text2SQL。

平台不再提供企业 AI 工作台，也不提供经验报告、审计、主动预警、通用规则或通用集成等
独立产品模块。复杂的治理和执行能力保留在后端作为提问链路的安全边界，不形成额外的
用户工作面。

## 产品主链

```text
用户提问
  -> Responses API 持久化 Response / Event / Outbox
  -> Worker 租约领取与可恢复 Agent Loop
  -> ContextAssembler 注入授权企业大脑上下文
  -> IntentPlan 仅选择 RAG 或 DataAgent/Text2SQL
  -> PostgreSQL 持久化答案、引用、SQL 与运行事件
  -> SSE 流式返回并支持断点续传
```

企业大脑只提供当前用户可见的公司、部门和术语上下文，不替代企业知识库或实时数据库；
RAG 返回带引用的已发布知识；Text2SQL 只访问授权数据源并执行只读 SQL。

## 产品页面

普通用户可访问：提问、我的资料、数据库、个人记忆、任务、Skills、设置。

管理员额外可访问：企业大脑、企业知识库、知识库质量中心、权限。

所有其他旧入口均已移除，未知前端路径回到提问页，非管理员访问管理员路径会回到提问页。

## 工程原则

- PostgreSQL 是 Response、Item、Event、Outbox、审批和工具账本的事实来源。
- API 只提交命令，模型和工具只在 Worker 中执行。
- 资源查询同时受 user、tenant、workspace、Project 和数据源授权约束。
- 企业大脑、RAG 和 DataAgent 均通过统一 Model Gateway 与 Agent Loop 执行。
- 只读能力自动执行；任何未来写能力都必须经过持久化审批和幂等账本。
- 任何能力收敛都必须同时删除用户入口、API 暴露、Worker 循环和运行时注册。

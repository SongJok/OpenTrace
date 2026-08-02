# 个人日历与时间型记忆架构

## 产品定位

个人日历是 OpenTrace 的一级业务资源，也是 Agent 上下文中的**时间型记忆来源**。它与普通用户记忆、定时 Agent 任务的职责不同：

- `UserMemory` 保存稳定偏好、事实和工作方式。
- `CalendarEvent` 保存确定的时间安排、地点、重复规则和提醒设置。
- `TaskDefinition` 按计划主动执行完整 Agent Loop，不用于表达“用户明天要做什么”。

因此，“明天下午三点客户复盘，帮我记录”进入个人日历；“每天九点生成经营日报”进入定时任务。

## 自然语言到日历的链路

```text
用户输入
  → 前端提交客户端 IANA timezone
  → ContextAssembler 注入当前本地时间和未来 14 天日历
  → Manager 识别“查看日历”或“明确记录日程”意图
  → list_calendar_events（只读，可直接执行）
     或 create/update/cancel_calendar_event（写操作）
  → 写操作生成 ResponseApproval 持久化暂停点
  → 用户确认后 Worker 执行工具
  → PostgreSQL calendar_events 成为事实来源
  → 后续对话自动获得最新时间型记忆
```

在当前日期 **2026 年 7 月 29 日**、时区 `Asia/Shanghai` 下，“明天 09:00”必须解析为
**2026 年 7 月 30 日 09:00 +08:00**，存储为 UTC 后再按用户时区展示。

## 数据模型

`calendar_events`：

- `user_id / tenant_id / workspace_id`：三层资源边界。
- `start_at / end_at`：统一 UTC 持久化。
- `timezone`：保留事件原始 IANA 时区。
- `all_day`：全天事件按用户时区自然日边界保存。
- `recurrence_rule`：RFC5545 RRULE，查询时展开实例。
- `event_type`：普通日程、会议、专注、提醒。
- `source`：区分用户手工创建和 AI 经审批创建。
- `source_response_id`：保留 AI 写入来源，便于审计。
- `reminder_minutes`：一个事件最多五个提醒偏移。
- `revision / cancelled_at`：当前版本和取消时间；取消是状态变化，不物理删除事件。

`calendar_event_revisions` 是只追加的修订账本。每次创建、改期和取消都保存当时快照、
变更字段、操作来源与 Response 证据；`CalendarEvent` 仍是最新事实来源，修订账本只用于
“原安排是什么、何时改期、是否取消”等历史问题，不能反向覆盖当前状态。

`calendar_reminder_deliveries` 是提醒幂等账本，以
`event_id + occurrence_start + reminder_minutes` 唯一约束防止 Worker 重启或重复轮询产生重复通知。

## Agent 治理规则

1. 查看日历属于只读工具，可以直接执行。
2. 创建和修改属于 `write`，取消属于 `destructive`，必须经过 Responses 持久化审批。
3. 只有用户明确表达“记录、添加到日历、安排、提醒我”时才调用写工具；讨论计划不等于写入日历。
4. 时间信息不足时必须追问，不能猜测日期或开始时间。
5. 用户只给开始时间时，普通日程默认一小时，全天日程默认一个自然日。
6. 工具只接收 Worker 注入的用户、租户、工作区和 Response 来源，模型不能自行指定作用域。

## 时间型记忆生命周期

日历与长期 `UserMemory` 采用不同生命周期，避免旧日程污染跨会话回答：

- `upcoming / in_progress`：当前计划，进入未来 14 天上下文并可直接参与回答。
- `completed`：已发生的历史经历，事件本身继续保留，但只在用户查询过去日程时按需检索。
- `cancelled`：已撤销事实，默认查询和上下文均排除；用户明确查询取消记录时才返回。
- 重复事件：按每个 occurrence 计算时间状态，不能因为首个实例过期而失效整个规则。
- 改期：只更新当前事件并追加修订；旧时间仅作为历史证据，不再参与当前计划回答。

具体日期的一次性日程不会复制到长期语义记忆。稳定的时区、工作时间、默认会议时长和
重复工作习惯仍可进入 `UserMemory`；这保证动态事实始终跟随业务资源状态变化。

## 前端交互

个人日历入口为 `/calendar`，采用企业日历常见的信息结构：

- 月视图：六周网格、今天高亮、事件色块、双击快速创建。
- 日程视图：按日期分组的连续清单。
- 右侧日面板：查看选中日期全部安排。
- 新建/编辑抽屉：类型、日期、起止时间、全天、重复、提醒、地点和备注。
- AI 来源标识：经对话审批创建的日程显示“AI 记录”。
- “通过 AI 添加”：跳转对话并预填日程请求。

## 提醒与通知

Agent Worker 的 scheduler 角色每 30 秒扫描到期提醒：

1. 展开未来最多七天内的重复实例。
2. 根据 `reminder_minutes` 计算到期时间。
3. 检查提醒投递账本。
4. 写入统一 `TaskNotification` 通知中心。
5. 用户点击通知后进入个人日历，通知已读状态持久化。

## 当前边界

本阶段提供用户个人主日历，不包含企业共享日历、参会人响应、会议室预订和第三方日历双向同步。后续可在不改变 `CalendarEvent` 个人事实源的前提下增加 calendar book、attendee、free/busy 和 connector 层。

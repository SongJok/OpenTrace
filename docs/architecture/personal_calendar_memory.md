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

`calendar_reminder_deliveries` 是提醒幂等账本，以
`event_id + occurrence_start + reminder_minutes` 唯一约束防止 Worker 重启或重复轮询产生重复通知。

## Agent 治理规则

1. 查看日历属于只读工具，可以直接执行。
2. 创建和修改属于 `write`，取消属于 `destructive`，必须经过 Responses 持久化审批。
3. 只有用户明确表达“记录、添加到日历、安排、提醒我”时才调用写工具；讨论计划不等于写入日历。
4. 时间信息不足时必须追问，不能猜测日期或开始时间。
5. 用户只给开始时间时，普通日程默认一小时，全天日程默认一个自然日。
6. 工具只接收 Worker 注入的用户、租户、工作区和 Response 来源，模型不能自行指定作用域。

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

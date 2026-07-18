# 测试问题记录：问答主链路外键违反（5001）

> 状态：**已修复**。Responses 创建父记录后已显式 `flush()`，2026-07-18 的 Docker
> 主链路验收已覆盖同步回答、持久化事件、文档检索与历史投影。下文保留为故障复盘，
> 不代表当前运行状态。
>
> 记录时间：2026-07-13
> 测试方式：端到端 HTTP 调用（Docker 运行中的 API 14100）+ 数据库核对 + 后端 traceback 分析
> 角色：测试（仅记录，未修改代码）

## 一、严重问题（阻断）

### P0-1：问答主链路全部不可用，`/api/v2/responses` 任何模式均返回 5001

**现象**

前端问答请求（`POST /api/v2/responses`）无论 sync / background / stream 哪种模式，都返回：

```json
{
  "code": 5001,
  "message": "服务内部错误",
  "details": "(sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.ForeignKeyViolationError'>: insert or update on table \"response_events\" violates foreign key constraint \"response_events_response_id_fkey\"\nDETAIL:  Key (response_id)=(resp_xxx) is not present in table \"responses\".\n[SQL: INSERT INTO response_events (...) VALUES (... 'response.created', ...)]"
}
```

**复现命令**

```bash
TOKEN=$(curl -s -X POST http://localhost:14100/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"songts@tuwan.com","password":"123456"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# sync
curl -s -X POST http://localhost:14100/api/v2/responses -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{"input":"你好","stream":false}'
# stream（前端默认路径）
curl -s -N -X POST http://localhost:14100/api/v2/responses -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{"input":"你好","stream":true}'
# background
curl -s -X POST http://localhost:14100/api/v2/responses -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{"input":"你好","stream":false,"background":true}'
```

三种模式均复现，request_id 每次不同（非幂等命中）。

**根因分析（仅记录，待修复）**

- 位置：`gateway/api_gateway/routers/responses.py` 的 `create_response`，约 `db.add(record)` 之后、`await db.commit()`（行 ~751-781）。
- `infra/storage/models.py` 中 `ResponseRecord`(表 `responses`) 与 `ResponseItem` / `ResponseEvent` / `ResponseToolExecution` / `ResponseModelCall` **仅通过 `ForeignKey` 列关联，未定义 `relationship()`**。
- SQLAlchemy 的 UnitOfWork 只按 `relationship()` 建立 mapper 级依赖排序，**纯外键列不会自动排序 flush 顺序**。
- `create_response` 在同一事务内先后 `db.add(record)`、`db.add(ResponseItem(...))`、`db.add(ResponseEvent(...))`，首次 `commit()` 触发 flush 时，`response_events` 的 INSERT 可能先于 `responses` 父行执行，命中外键约束 `response_events_response_id_fkey`。
- 外键违反导致整个事务回滚，因此数据库 `responses` 表 0 行、无孤儿 event（事务原子性，回滚干净）。
- traceback 栈确认：`unitofwork.execute -> persistence.save_obj -> _emit_insert_statements` 在 flush 阶段抛出，对应应用层 `create_response` 首次 commit。

**数据库核对（佐证）**

```
responses 表行数：0（事务回滚，父行未落库）
孤儿 response_events 行数：0（回滚干净，无脏数据）
schema 正常：responses 列齐全（含 request_payload / lease_* / attempt_count / max_attempts）
response_metadata 类型为 json（非 jsonb），与模型一致，非 schema 缺陷
```

**影响面**

- 前端 `frontend/src/api/client.ts` 默认走 `POST /api/v2/responses`（stream=true），即用户在 UI 发任何消息都会失败。
- `/api/v1/chat` 已停用（见 P1-1），无 fallback。**问答主链路完全不可用**。

**修复方向建议（供后续修复参考）**

- 方案 A（最小改动）：`db.add(record)` 之后加 `await db.flush()`，强制父行先落库。
- 方案 B（根因）：在 models 的 `ResponseRecord` 与各子表间补 `relationship()`，让 UnitOfWork 自动排序。
- 注意：其他路径（`_run_background_response` / `_persist_stream_event` / `approve_response_tool`）均先 `db.get`/`select` 确认 record 已存在再追加事件，不受此问题影响。

---

### P0-2：合约测试存在覆盖盲区，未能拦截 P0-1

**现象**

`pytest tests/test_responses_contract.py` 12 个用例全部通过，但线上问答仍 5001。

**原因（仅记录）**

- 合约测试大概率使用 SQLite / 隔离 DB 或 mock，未覆盖真实 PostgreSQL 外键约束下的首次 commit flush 顺序。
- SQLite 默认不强制外键（`PRAGMA foreign_keys=OFF`），即使顺序错误也不会报外键违反。
- 因此纯外键无 relationship 导致的 flush 顺序问题，在测试套件里无法暴露。

**建议**

- 关键写入路径（`create_response` 首次 commit）补一条针对 Postgres 的集成测试（用真实 PG 或至少 `PRAGMA foreign_keys=ON` 的 SQLite），断言 `responses` 父行先于 `response_events` 落库。

## 二、次要问题

### P1-1：`/api/v1/chat` 已停用返回 410，无 fallback 可用

**现象**

```bash
curl -s -X POST http://localhost:14100/api/v1/chat -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN" -d '{"query":"你好"}'
# {"detail":{"code":"chat_endpoint_retired","message":"请迁移到 /api/v2/responses；旧 Chat 执行链已停用。"}}  HTTP 410
```

**说明**

- 这是设计上的迁移决策（CLAUDE.md 也说 V4/legacy chat 仅作 fallback）。本身非 bug。
- 但当前 `/api/v2/responses` 因 P0-1 完全不可用，导致迁移目标不可用、又无 fallback，属关联风险，记录在此。

## 三、已验证正常的流程（排除项）

| 端点 | 方法 | 结果 |
|------|------|------|
| `/api/v1/auth/login` | POST | 200，正常返回 token |
| `/api/v1/auth/me` | GET | 200 |
| `/api/v1/conversations` | GET | 200，返回会话列表 |
| `/api/v1/knowledge/sources` | GET | 200，返回 `[]` |
| `/api/v1/memories` | GET | 200，返回记忆列表 |
| `tests/test_responses_contract.py` | pytest | 12/12 通过（但见 P0-2 盲区） |

容器健康状态：`opentrace_api` / `opentrace_agent_worker` / `opentrace_redis` / `opentrace_postgres` 全部 healthy，约 1 小时前启动。

## 四、环境信息

- API：`opentrace_api` 容器，端口 14100，容器内 `responses.py` md5 与宿主机一致（源码同步）。
- 前端：14108（node 进程在监听）。
- DB：`opentrace_postgres`，库名 `opentrace_v2`。
- 测试账号：`songts@tuwan.com / 123456`（seed_user.py 创建的超管）。

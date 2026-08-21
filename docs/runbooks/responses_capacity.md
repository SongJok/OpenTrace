# Responses v2 容量与发布证据手册

## 目标与口径

本手册只验证 `/api/v2/responses` 持久主链。HTTP 2xx 表示命令已提交，不表示 Agent 已完成；
容量工具会继续读取持久投影和事件，分别统计：

- 命令接收率与接收 P50/P95/P99；
- `response.in_progress` 首持久事件覆盖率与延迟；
- `completed` 完成率、终态分布、端到端 P50/P95/P99 和完成吞吐；
- 每个工作负载场景的独立接收率、完成率和三类延迟，禁止用总体平均掩盖单能力退化。

终态计时在首次观察到终态投影时结束，后续事件证据查询不会混入端到端 SLO。报告不保存
Token、输入正文或原始 `response_id`，只保存工作负载规范化哈希和 Response ID 集合哈希。

## 前置条件

1. 使用与候选版本完全相同、工作区干净的提交部署独立 staging 栈；不得对生产租户直接压测。
   候选镜像必须在构建时注入 `OPENTRACE_RELEASE_REVISION`；正式工具会先通过
   `/api/v1/health` 核对运行服务修订，不一致时不会发送任何工作负载。
2. 使用专用测试租户、最小权限 Token、稳定数据夹具和只读场景；写操作与审批吞吐另行演练。
3. staging 必须通过 HTTPS 暴露，目标主机通过 `OPENTRACE_LOAD_API_HOST` 精确绑定。
4. PostgreSQL、Redis、模型和 Connector 配额必须与计划容量一致，并启用正式观测栈。
5. 工作负载至少覆盖四类实际能力组合，例如 RAG、Data、Production 只读诊断和 Config
   只读校验；每个场景至少获得 10 个样本。

## 工作负载合同

工作负载是严格 JSONL。每行只能包含 `id`、`input` 和可选的整数 `weight`：

```json
{"id":"knowledge-policy-read","input":"<稳定知识夹具上的只读问题>","weight":2}
{"id":"data-kpi-read","input":"<稳定数据夹具上的只读指标问题>","weight":2}
{"id":"production-incident-read","input":"<稳定观测夹具上的只读诊断问题>","weight":1}
{"id":"config-policy-read","input":"<稳定配置夹具上的只读校验问题>","weight":1}
```

`id` 必须唯一且只含小写字母、数字、点、下划线或短横线；输入为 1..4000 字符；单个权重
为 1..100。工具使用平滑加权轮询，避免低权重场景集中在尾部或没有得到样本。租户业务问题
可能包含敏感信息，工作负载文件应放在受控证据库，不应提交到公共仓库。

## 分级执行

先以 10、25、50 等递增并发执行阶梯压测，每一级至少覆盖一个稳定观测窗口。正式证据示例：

```bash
export OPENTRACE_LOAD_API_HOST=staging.example.com
export OPENTRACE_LOAD_TOKEN='<short-lived-token>'

python scripts/load_responses.py \
  --base-url https://staging.example.com \
  --workload-file /secure/capacity/responses-v2.jsonl \
  --total 1000 \
  --concurrency 50 \
  --release-gate \
  --release-subject "$(git rev-parse HEAD)" \
  --output /secure/evidence/capacity-$(git rev-parse HEAD).json

unset OPENTRACE_LOAD_TOKEN
```

发布运行固定底线为：接收率 ≥ 99%、完成率 ≥ 99%、接收 P95 ≤ 2 秒、首持久事件 P95
≤ 2 秒、端到端完成 P95 ≤ 120 秒。命令可以收紧阈值，正式证据验证器拒绝任何放宽阈值、
少于 100 个总样本、少于四个场景、单场景少于 10 个样本、非 HTTPS 目标、重复/原始
Response ID、超过 72 小时的报告，以及与当前候选提交或运行服务修订不匹配的报告。

## 证据复核与发布门禁

在干净的候选提交上独立复核：

```bash
python scripts/load_responses.py \
  --verify-report /secure/evidence/capacity-<revision>.json \
  --release-subject "$(git rev-parse HEAD)"
```

随后把证据路径与真实 Golden Results 一并传给发布门禁：

```bash
ENTERPRISE_CAPACITY_REPORT=/secure/evidence/capacity-<revision>.json \
ENTERPRISE_EVAL_RESULTS_DIR=/secure/evidence/golden-results \
  bash scripts/run_product_beta_gate.sh --release
```

报告采用独占创建，工具拒绝覆盖同名证据。发布负责人还应归档同窗口的 Worker 并发、数据库
连接池、Redis lag、模型/Connector 限流、成本和资源曲线；若容量结果失败，不得通过重跑同一
低负载、删除失败样本或放宽阈值取得放量批准，应先定位瓶颈并重新执行完整阶梯。

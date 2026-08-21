# Enterprise Connector 开发指南

OpenTrace 的 Connector 是企业系统接入面，不是 Agent 编排器。所有外部调用都必须经过
`GovernedConnectorGateway`，由平台统一完成租户范围、操作白名单、角色策略、输入
Schema、超时、输出上限、脱敏、证据持久化和审计。

## 选择接入方式

| 场景 | 推荐通道 | 原因 |
| --- | --- | --- |
| 通用 AI Tool、外部产品已有 MCP | MCP Streamable HTTP | 统一契约，接入快 |
| 高频查询、流式日志、大规模代码索引 | Native SDK/API | 能够使用分页、流控和专用协议 |
| 数据库业务查询 | DataAgent | 保留语义层、静态校验和只读执行 |
| 内部服务 | REST/RPC Native Adapter | 复用内网鉴权、限流和可观测性 |

MCP 远端发现不会自动扩大本地操作目录。管理员必须在控制台显式声明每个
operation，未声明的工具不可调用。

## 必要契约

```python
ConnectorOperationSpec(
    name="query_service_health",
    description="查询服务健康摘要",
    domain="observability",
    risk="read",
    input_schema={
        "type": "object",
        "properties": {"service": {"type": "string", "maxLength": 128}},
        "required": ["service"],
        "additionalProperties": False,
    },
    required_permissions=("role:sre",),
    timeout_seconds=30,
    max_output_bytes=262_144,
    evidence_types=("metric",),
    verification_evidence_types=(),
    supports_idempotency=False,
)
```

- operation 名称必须稳定，禁止将 URL、SQL 或 Shell 指令当作操作名。
- `input_schema` 必须是封闭对象：`additionalProperties: false`。
- 写操作必须声明 `evidence_types` 和其子集 `verification_evidence_types`；无显式后置条件证据的
  变更不得上线。验证证据必须在 payload 的 `verification` 中返回 `status=verified/passed` 和
  与本次调用完全相同的 `idempotency_key`，环境与目标资产也必须匹配。
- 写操作还必须声明 `supports_idempotency: true`，Adapter 必须使用
  `context.idempotency_key` 调用下游。MCP 通道由平台发送标准 `Idempotency-Key` 请求头。
- 凭据只保存 `env://`、`vault://`、KMS 或 Kubernetes Secret 引用，不得放入
  Connector `config`、返回数据或证据引用。
- Adapter 只负责专用协议与数据转换，不自行绕过 Gateway 做权限判定。

## MCP 目录示例

```json
{
  "name": "grafana-prod",
  "connector_kind": "observability",
  "transport": "mcp",
  "endpoint": "https://grafana.example.com/mcp",
  "secret_ref": "vault://opentrace/grafana-prod",
  "status": "disabled",
  "allowed_operations": ["query_metrics"],
  "allowed_environments": ["prod"],
  "data_classification": "internal",
  "config": {
    "adapter_key": "mcp",
    "allowed_hosts": ["grafana.example.com"],
    "runtime_policy": {
      "enabled": true,
      "requests_per_minute": 120,
      "max_concurrency": 8,
      "failure_threshold": 5,
      "recovery_seconds": 60,
      "half_open_max_calls": 1,
      "lease_grace_seconds": 5,
      "read_fail_open": true
    },
    "operation_specs": [
      {
        "name": "query_metrics",
        "description": "查询受控服务指标",
        "domain": "observability",
        "risk": "read",
        "input_schema": {
          "type": "object",
          "properties": {
            "service": {"type": "string", "maxLength": 128},
            "environment": {"type": "string", "enum": ["prod"]}
          },
          "required": ["service", "environment"],
          "additionalProperties": false
        },
        "timeout_seconds": 30,
        "max_output_bytes": 262144,
        "evidence_types": ["metric"]
      }
    ]
  }
}
```

新建 Connector 默认保持 `disabled`。完成网络 allowlist、Secret Resolver、最小权限和
测试环境验收后才能在控制台启用。启用时平台强制要求非空操作集、显式环境范围、HTTPS
endpoint（仅显式本地开发例外）以及包含 endpoint 主机的 `allowed_hosts`；MCP transport 只能
绑定内置 `mcp` Adapter，Native/REST/RPC 必须绑定启动期已注册的 Adapter，不能等到执行时才
发现目录与运行时不一致。

`runtime_policy` 由目录服务补齐并严格校验。平台使用 Redis Lua 在所有 Worker 之间原子
执行 60 秒滑窗限流、并发租约、连续失败熔断和半开探测。控制存储不可用时，只读操作可按
`read_fail_open` 明确降级；任何写操作一律失败关闭。租约会按 operation 超时自动过期，
进程崩溃不会永久占用并发名额。

## Native SDK

`connectors.sdk.NativeConnectorBuilder` 用于绑定确定性操作声明与异步 handler。完整的
第三方 Adapter 由安装包的 bootstrap 注册到 `connector_registry`；不要在业务模块导入时产生
隐式注册副作用。仓库内置的 `connectors/prometheus.py` 是可运行的生产参考实现：它调用真实
Prometheus HTTP API、限制响应大小与时间序列数量、复用网络目标校验和 Secret Resolver，并且
只暴露受控的 HTTP 5xx 比率模板，不接受任意 PromQL，也不会生成模拟健康结论。

创建内置 Prometheus Connector 时使用 `transport=native`、`config.adapter_key=prometheus`、
`allowed_operations=["query_http_error_ratio"]`。`endpoint` 指向 Prometheus 根地址；内网地址必须
显式设置 `allow_private_network=true` 并配置 `allowed_hosts`，生产环境仍应通过 egress policy
限制目标。指标名及 service/environment/status label 可在配置中覆盖，但都会经过 PromQL 名称
校验。

第三方包应声明受控 entry point：

```toml
[project.entry-points."opentrace.connectors"]
company_observability = "company_connectors.observability:build_adapter"
```

`build_adapter` 返回一个 Adapter。部署镜像安装并固定该包版本后，再配置
`CONNECTOR_ADAPTER_ENTRYPOINTS=company_observability`。平台只在进程启动期加载 allowlist 中的
名称；未列入的已安装包不会执行，缺失、非法对象和 adapter key 冲突会启动失败。扩展代码与
核心服务拥有相同进程权限，因此必须进入依赖签名、SBOM、漏洞扫描和代码审查。

内置 MCP Adapter 默认只解析 `env://VARIABLE`。Vault/KMS 包可另行声明：

```toml
[project.entry-points."opentrace.connector_secret_resolvers"]
company_vault = "company_connectors.secrets:build_resolver"
```

Resolver 实现异步 `resolve_headers(secret_ref)`，并配置
`CONNECTOR_SECRET_RESOLVER_ENTRYPOINT=company_vault`。只能启用一个 Resolver；缺失或契约非法会
启动失败。Resolver 应签发短期凭据，不得把 Secret 放入日志、异常、返回数据或 Connector 配置。

## 证据输出

证据必须包含可定位的 `source_ref`、由来源系统给出的可解析观测时间、环境、权威来源和
0–1 置信度。平台不会用接收时间替代缺失/非法的观测时间，也不会从普通工具文本自动合成
证据；不满足契约的条目只作为受控工具数据返回，不能解锁 Evidence Gate。
原始大日志、Trace 或指标集不复制进 PostgreSQL，只持久化受控摘要、引用和内容哈希。
受限角色会在 Gateway 层执行字段与文本脱敏。

## 测试清单

1. 只能调用已声明操作，未知字段被 JSON Schema 拒绝。
2. 租户、工作区、环境、角色和数据分类均有拒绝用例。
3. 超时、远端错误、过大输出、非法证据和敏感字段都会显式失败。
4. 写操作未审批时不会进入 Adapter，执行后缺验证证据进入 `incomplete`。
5. 写操作的验证证据类型、环境、目标资产和幂等键任一不匹配时进入 reconciliation。
6. 副作用工具的超时或未知结果不自动重试，通过 reconciliation 人工确认。
7. 覆盖限流、并发上限、熔断/半开、控制存储不可用和幂等键透传。

# Knowledge Orchestration

OpenTrace 的知识编排采用“数据库事实源 + Obsidian Vault 投影”设计：

```text
data/Document + Chunk
        │
        ▼
KnowledgeSource/Version → Page/Claim/Relation
        │                         │
        │                         ├─ RAG knowledge lane（在线查询）
        │                         ├─ lint / merge / trace / evolution
        │                         └─ meta/wiki/data Vault（可读投影）
        ▼
durable compilation jobs
```

## 在产品页面中使用

1. 在问答页选择一个 Project，再进入侧边栏的“知识编排”；页面会沿用当前 Project。
2. 将 PDF、DOCX、Markdown 或 TXT 拖入上传区。
3. 选择“自动纳入问答”或“人工审核后纳入问答”。自动模式会在编译成功后发布；审核模式需要调用发布接口。
4. 在实体图谱、依赖关系、来源网络间切换，查看当前 Project 的节点、关系与可追溯来源。
5. 如需立即扫描所有已上传文件，点击“立即编排”。Worker 还会按 `KNOWLEDGE_RECONCILE_SECONDS` 周期兜底扫描变更。

主问答的 RAG Agent 默认按 `knowledge → documents → semantic_memory` 检索，并携带当前
`project_id`。因此已发布知识无需手工添加到 prompt；切换 Project 后检索边界也会同步切换。

部署时必须运行数据库迁移和 Agent Worker：

```bash
alembic upgrade head
docker compose up -d api agent-worker
```

关键配置：

```dotenv
KNOWLEDGE_ORCHESTRATION_ENABLED=true
KNOWLEDGE_QUERY_ENABLED=true
KNOWLEDGE_AUTO_COMPILE_ENABLED=true
KNOWLEDGE_AUTO_PUBLISH=true
KNOWLEDGE_JOB_POLL_SECONDS=2
KNOWLEDGE_RECONCILE_SECONDS=300
```

## 分层

- 数据层：`Document`、`DocumentChunk` 和 `.manifest.json`。
- Wiki 层：已发布的 `KnowledgePage/Claim/Relation`，支持摘要→页面→事实→来源渐进披露。
- 元数据层：`KnowledgeRule`、Schema、合并规则、构建与调度说明。
- 元认知层：lint、feedback、observation 和需人工批准的 evolution proposal。
- 交互层：RAG Agent 自动启用 knowledge lane；显式命令才允许摄入、建链、合并或演化。

## Python API

```python
from knowledge.orchestration import (
    IngestPipeline,
    KnowledgeWorkspace,
    LintChecker,
    QueryPipeline,
)

await IngestPipeline().ingest_workspace(
    tenant_id="default",
    workspace_id="workspace-a",
    owner_id="user-a",
)

result = await QueryPipeline().query(
    "退款流程如何办理？",
    user_id="user-a",
    tenant_id="default",
    workspace_id="workspace-a",
)

lint = await LintChecker().check_workspace(
    tenant_id="default",
    workspace_id="workspace-a",
    owner_id="user-a",
)

vault = await KnowledgeWorkspace().materialize(
    ".runtime/knowledge-vault/workspace-a",
    tenant_id="default",
    workspace_id="workspace-a",
    owner_id="user-a",
    include_raw_assets=False,
)
```

生成的 Vault：

```text
vault/
├── .obsidian/
├── meta/
│   ├── usage.md
│   ├── merge-rules.md
│   ├── entity-schema.md
│   ├── scheduler.md
│   └── wiki-build-guide.md
├── wiki/
│   ├── index.md
│   ├── hot.md
│   ├── concepts/
│   ├── actions/
│   └── ...
└── data/
    ├── .manifest.json
    └── sources/       # 仅 include_raw_assets=True 时生成
```

`managed_by: opentrace` 的 Markdown 是投影视图，不是第二事实源。需要修订知识时，
通过反馈、审核、规则或源文档更新进入治理主链。

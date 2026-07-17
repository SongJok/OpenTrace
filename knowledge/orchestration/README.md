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

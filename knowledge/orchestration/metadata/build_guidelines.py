"""知识编排构建阶段、调度建议与自描述元数据文档。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from knowledge.orchestration.metadata.schema_manager import SchemaManager


class BuildStage(StrEnum):
    VALIDATE = "validate"
    COMPILE = "compile"
    LINK = "link"
    INDEX = "index"
    PUBLISH = "publish"
    LINT = "lint"
    MATERIALIZE = "materialize"


@dataclass(frozen=True, slots=True)
class ScheduledKnowledgeTask:
    name: str
    schedule: str
    action: str


class BuildGuidelines:
    stages = tuple(BuildStage)
    scheduled_tasks = (
        ScheduledKnowledgeTask("知识摄入", "每 2 小时", "扫描就绪文档并提交增量编译"),
        ScheduledKnowledgeTask("健康检查", "每周日 02:00", "运行 lint 并同步问题状态"),
        ScheduledKnowledgeTask("过期治理", "每周日 03:00", "复核 stale 来源与受影响页面"),
        ScheduledKnowledgeTask("Vault 物化", "每小时", "刷新 index.md、hot.md 与 manifest"),
    )

    @classmethod
    def metadata_documents(cls) -> dict[str, str]:
        allowed = "、".join(sorted(SchemaManager().schemas))
        tasks = "\n".join(
            f"| {task.name} | {task.schedule} | {task.action} |" for task in cls.scheduled_tasks
        )
        return {
            "usage.md": """# Wiki 系统使用手册

## 查询路由

- “什么是 X”走定义查询。
- “X 与 Y 的关系/区别”走关系图查询。
- “如何做 X”优先检索 procedure、policy 与可溯源 claim。
- 查询顺序为 hot → page summary → claim/relation → source evidence。

## 写操作

摄入、合并、建链、规则演化均为显式命令；普通问答只有读取权限。
""",
            "merge-rules.md": """# 知识合并与更新策略

- 内容相同：保留权威级别更高、置信度更高且更新更晚的候选。
- 内容冲突：创建 merge case，必须人工选择保留、合并或并存。
- 新版本发布后：旧版本归档，引用仍可通过 source/version 追溯。
- 原始文档、Wiki 页面、claim 不互相覆盖，各自保持独立版本语义。
""",
            "entity-schema.md": f"""# 知识页面 Schema

允许的页面类型：{allowed}。

所有页面必须包含 type、title、status、authority、confidence、source_docs、
updated、stale 与 managed_by。所有事实 claim 必须绑定 evidence chunk 和字符区间。
""",
            "scheduler.md": f"""# 知识任务调度

| 任务 | 建议周期 | 操作 |
|---|---|---|
{tasks}

生产环境由 Agent Worker 与外部调度器执行；本文档只描述策略，不作为进程内定时器。
""",
            "wiki-build-guide.md": """# Wiki 层构建指南

构建顺序：validate → compile → link → index → publish → lint → materialize。

数据库中的 KnowledgeSource/Version/Page/Claim/Relation 是在线事实源；
Obsidian Vault 是只读投影视图。人工修订应通过规则、反馈或审核接口回写，
不要直接修改 managed_by=opentrace 的生成文件。
""",
        }

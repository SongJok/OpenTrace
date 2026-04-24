## 4. 代码目录结构

```
opentrace/
├── bin/                    # 运维脚本
│   ├── _common.sh          #   共享工具函数
│   ├── start.sh            #   一键启动
│   ├── stop.sh             #   一键停止
│   └── restart.sh          #   一键重启
├── docs/                   # 项目文档
├── gateway/                # API 网关层 (端口 14101)
│   ├── api_gateway/
│   │   ├── main.py         #   FastAPI 应用入口
│   │   └── routers/
│   │       ├── auth.py     #   认证接口
│   │       ├── chat.py     #   AI 对话接口
│   │       ├── conversations.py  # 会话管理
│   │       ├── health.py   #   健康检查
│   │       ├── feedback.py #   反馈
│   │       └── admin.py    #   管理
│   └── cognitive_gateway/gateway.py  # 认知路由
├── kernel/                 # 认知内核
│   ├── orchestrator.py     #   主编排器
│   ├── reasoning/          #   推理引擎
│   ├── intent_engine/      #   意图理解
│   ├── prompt_engine/      #   Prompt 构建
│   ├── meta_cognition/     #   元认知
│   └── policy/             #   策略(bandit/RL)
├── agent_runtime/          # Agent 运行时
│   ├── agent_core/         #   BaseAgent
│   ├── planner/            #   任务规划
│   ├── executor/           #   工具执行
│   ├── critic/             #   质量评估
│   ├── reflector/          #   自我反思
│   └── market/             #   Agent 市场
├── model/                  # 模型层
│   ├── model_gateway/      #   多模型路由+熔断
│   ├── llm_adapter/        #   LLM 适配器
│   ├── embedding/          #   向量嵌入
│   └── reranker/           #   重排序
├── memory/                 # 记忆系统
│   ├── memory_router/      #   统一路由
│   ├── working_memory/     #   工作记忆(Redis)
│   ├── episodic_memory/    #   情景记忆(PG)
│   ├── semantic_memory/    #   语义记忆(pgvector)
│   └── procedural_memory/  #   程序性记忆
├── execution/              # 执行引擎
│   ├── dag_engine/         #   DAG 调度
│   ├── workflow_engine/    #   工作流
│   ├── tool_router/        #   工具路由
│   ├── sandbox/            #   沙箱
│   └── scheduler/          #   调度器
├── safety/                 # 安全层
│   ├── guardrails/         #   输入/输出守卫
│   ├── policy_engine/      #   策略引擎
│   └── audit/              #   审计日志
├── evolution/              # 自我进化
│   ├── meta_learning/      #   元学习
│   ├── self_play/          #   自我对弈
│   ├── data_flywheel/      #   数据飞轮
│   ├── feedback/           #   反馈收集
│   ├── evaluation/         #   评估引擎
│   └── learning/           #   持续学习
├── infra/                  # 基础设施
│   ├── config/settings.py  #   Pydantic Settings
│   ├── storage/            #   数据库引擎+ORM
│   ├── cache/              #   Redis 客户端
│   ├── message_bus/        #   消息总线
│   └── observability/      #   日志/指标/追踪
├── tools/                  # 工具系统
│   ├── registry/           #   工具注册表
│   ├── builtin_tools/      #   内置工具
│   └── adapters/           #   外部工具适配
├── sdk/                    # SDK
│   ├── python_sdk/         #   Python 客户端
│   └── plugin_sdk/         #   插件系统
├── frontend/               # React 前端 (端口 14108)
│   └── src/
│       ├── api/client.ts   #   所有 API 调用
│       ├── store/          #   Zustand 状态
│       ├── pages/          #   页面组件
│       └── components/     #   UI 组件
├── scripts/
│   ├── seed_user.py        #   初始化用户
│   └── test_llm.py         #   LLM 连通测试
├── deploy/docker/          # Docker 配置
├── alembic/                # 数据库迁移
├── .env                    # 环境变量
├── requirements.txt        # Python 依赖
└── docker-compose.yml      # 容器编排
```

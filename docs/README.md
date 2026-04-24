# OpenTrace — 完整项目文档

> 版本: 0.1.0 | Python 3.13 + Node 25 | PostgreSQL + Redis

---

## 目录

1. [项目简介](#1-项目简介)
2. [快速启动](#2-快速启动)
3. [功能列表](#3-功能列表)
4. [代码目录结构](#4-代码目录结构)
5. [服务架构拓扑图](#5-服务架构拓扑图)
6. [请求流水图](#6-请求流水图)
7. [核心模块详解](#7-核心模块详解)
8. [API 接口文档](#8-api-接口文档)
9. [前端页面说明](#9-前端页面说明)
10. [环境配置说明](#10-环境配置说明)
11. [数据库模型](#11-数据库模型)
12. [运维脚本](#12-运维脚本)

---

## 1. 项目简介

**OpenTrace** 是一个分布式认知操作系统（Distributed Cognitive Operating System），基于大型语言模型构建，提供完整的 AI 对话、多 Agent 协作、多级记忆管理、安全策略和自我进化能力。

### 核心理念

| 层 | 描述 |
|----|------|
| 认知内核 | 推理、意图理解、策略决策 |
| 多级记忆 | 工作/情景/语义/程序性记忆 |
| Agent 运行时 | 多 Agent 协作、工具调用、自我反思 |
| 安全层 | 输入/输出守卫、策略引擎、审计 |
| 自我进化 | 元学习、自我对弈、数据飞轮 |

### 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind + Zustand |
| 后端 | FastAPI + Python 3.13 + asyncio + uvicorn |
| 数据库 | PostgreSQL 14+ (asyncpg + SQLAlchemy 2.0) |
| 缓存 | Redis 7（多 DB 分区） |
| LLM | 阿里云 DashScope / Qwen3（OpenAI 兼容） |
| 可观测 | OpenTelemetry + Prometheus + structlog |
| 容器化 | Docker + Docker Compose |

---

## 2. 快速启动

> ⚠️ **必须从系统终端（iTerm/Terminal.app）运行**，不要在 Cursor 内置终端运行。
> Cursor 内置终端注入代理会阻断 DashScope API 连接。

### 一键启动

```bash
cd /path/to/opentrace
bash bin/start.sh     # 启动
bash bin/stop.sh      # 停止
bash bin/restart.sh   # 重启
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:14108 |
| 后端 API | http://localhost:14101 |
| Swagger 文档 | http://localhost:14101/docs |
| Prometheus 指标 | http://localhost:14101/metrics |

### 默认账号

```
邮箱: songts@tuwan.com
密码: 123456
```

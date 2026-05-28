# 01. 项目概述

## 1.1 背景

传统 NL2SQL 方案采用"自然语言 → LLM → SQL → 数据库"的直译模式，在企业生产环境中存在 SQL 不可校验、权限不可控、查询性能不可治理、多数据库方言适配困难等问题。

本方案采用"自然语言 → LLM → DSL → 校验 → 权限注入 → Query Planner → SQLAlchemy → 标准 SQL → sqlglot 方言转换 → 执行"的分层架构，实现可治理、可审计、可优化的企业级 AI Query Engine。

## 1.2 核心设计目标

| 目标 | 说明 |
|------|------|
| 可校验 | 所有查询必须经过字段合法性、指标合法性、操作符合法性、LIMIT 合法性校验 |
| 可优化 | 支持谓词下推、投影下推、聚合重写、查询重写 |
| 可治理 | 支持行级权限、列级权限、数据脱敏、租户隔离、审计日志 |
| 可扩展 | 支持多数据库方言、多指标体系、多语义模型 |

## 1.3 技术选型

| 模块 | 技术 |
|------|------|
| API 框架 | FastAPI |
| 工作流编排 | LangGraph |
| LLM 调用 | OpenAI / Claude / 通义千问 API |
| DSL 校验 | Pydantic v2 |
| 语义层 | 自定义 YAML 配置 |
| Query Planner | 自定义实现 |
| SQL 表达式构建 | SQLAlchemy Core |
| SQL 方言转换 | sqlglot |
| 向量库 | Milvus Lite（本地文件，每域独立），预留 Milvus Server 切换 |
| 文本嵌入 | SentenceTransformers（BGE-base-zh-v1.5，跨域共享） |
| 数据库 | SQLite（每域独立文件，存储于 `data/` 目录） |

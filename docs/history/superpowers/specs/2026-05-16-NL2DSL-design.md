# NL2DSL 设计文档（索引）

> 本文档已拆分为多个独立文档，按职责分类存放在不同目录下。
> 请根据角色选择阅读：

---

## 按角色阅读

| 角色 | 推荐阅读 |
|------|---------|
| **架构师 / 技术负责人** | [architecture/01-overview](../../architecture/01-overview.md) → [architecture/02-system-architecture](../../architecture/02-system-architecture.md) → [agent/34-llm-risks](../../agent/34-llm-risks.md) |
| **后端开发** | [architecture/02-system-architecture](../../architecture/02-system-architecture.md) → [architecture/03-sql-engine](../../architecture/03-sql-engine.md) → [agent/31-langgraph-workflow](../../agent/31-langgraph-workflow.md) |
| **数据工程师** | [business/10-semantic-layer](../../business/10-semantic-layer.md) → [agent/32-metadata-sync](../../agent/32-metadata-sync.md) |
| **业务方 / 产品经理** | [business/10-semantic-layer](../../business/10-semantic-layer.md) → [business/13-business-rules](../../business/13-business-rules.md) |
| **前端 / 接入方** | [api/20-dsl-spec](../../api/20-dsl-spec.md) → [api/21-api-contract](../../api/21-api-contract.md) |
| **测试** | [agent/33-testing](../../agent/33-testing.md) → [api/22-error-handling](../../api/22-error-handling.md) |
| **运维 / SRE** | [architecture/04-deployment](../../architecture/04-deployment.md) |

---

## 完整文档索引

### 架构（architecture/）

| 文档 | 内容 |
|------|------|
| [01-overview](../../architecture/01-overview.md) | 项目背景、核心目标、技术选型 |
| [02-system-architecture](../../architecture/02-system-architecture.md) | 整体架构图、数据流、目录结构 |
| [03-sql-engine](../../architecture/03-sql-engine.md) | SQLAlchemy 构建、sqlglot 方言转换、Query Planner |
| [04-deployment](../../architecture/04-deployment.md) | 部署方案、环境变量、性能参数 |

### 业务规则（business/）

| 文档 | 内容 |
|------|------|
| [10-semantic-layer](../../business/10-semantic-layer.md) | 语义层配置、枚举映射、可选值样本维护 |
| [11-dsl-validation](../../business/11-dsl-validation.md) | DSL 校验规则、风险控制约束 |
| [12-permission](../../business/12-permission.md) | 行级/列级权限、脱敏、租户隔离 |
| [13-business-rules](../../business/13-business-rules.md) | 术语表、同义词歧义处理、语义层风险 |

### API 契约（api/）

| 文档 | 内容 |
|------|------|
| [20-dsl-spec](../../api/20-dsl-spec.md) | DSL JSON Schema、字段定义、示例 |
| [21-api-contract](../../api/21-api-contract.md) | RESTful 接口、请求/响应格式 |
| [22-error-handling](../../api/22-error-handling.md) | 错误码、HTTP 状态码、响应格式 |

### Agent 执行（agent/）

| 文档 | 内容 |
|------|------|
| [30-rag-design](../../agent/30-rag-design.md) | 向量库设计、检索策略、Prompt 组装、检索优化 |
| [31-langgraph-workflow](../../agent/31-langgraph-workflow.md) | 工作流节点、调用链路追踪、错误回溯 |
| [32-metadata-sync](../../agent/32-metadata-sync.md) | 数据库元数据提取、初始化脚本、自动同步 |
| [33-testing](../../agent/33-testing.md) | 单元/集成/E2E 测试策略 |
| [34-llm-risks](../../agent/34-llm-risks.md) | LLM 成本、延迟、幻觉、稳定性、版本漂移 |

---

*本文档为索引文件，原内容已拆分至上述独立文档。*
*设计文档版本: 2.0*
*日期: 2026-05-16*

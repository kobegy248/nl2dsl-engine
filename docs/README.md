# NL2DSL 设计文档

## 文档索引

### 架构（architecture/）

| 文档 | 内容 | 读者 |
|------|------|------|
| [01-overview](architecture/01-overview.md) | 项目背景、核心目标、技术选型 | 所有人 |
| [02-system-architecture](architecture/02-system-architecture.md) | 整体架构、数据流、目录结构 | 开发、架构师 |
| [03-sql-engine](architecture/03-sql-engine.md) | SQLAlchemy 构建、sqlglot 方言转换、Query Planner | 后端开发 |
| [04-deployment](architecture/04-deployment.md) | 部署方案、环境变量、性能参数 | 运维、SRE |

### 业务规则（business/）

| 文档 | 内容 | 读者 |
|------|------|------|
| [10-semantic-layer](business/10-semantic-layer.md) | 语义层配置、枚举映射、可选值样本维护 | 数据工程师、业务方 |
| [11-dsl-validation](business/11-dsl-validation.md) | DSL 校验规则、风险控制约束 | 后端开发 |
| [12-permission](business/12-permission.md) | 行级/列级权限、脱敏、租户隔离 | 后端开发、安全 |
| [13-business-rules](business/13-business-rules.md) | 术语表、同义词歧义处理、语义层风险 | 业务方、产品经理 |

### API 契约（api/）

| 文档 | 内容 | 读者 |
|------|------|------|
| [20-dsl-spec](api/20-dsl-spec.md) | DSL JSON Schema、字段定义、示例 | 前后端、测试 |
| [21-api-contract](api/21-api-contract.md) | RESTful 接口、请求/响应格式 | 前后端、接入方 |
| [22-error-handling](api/22-error-handling.md) | 错误码、HTTP 状态码、响应格式 | 前后端、接入方 |

### Agent 执行（agent/）

| 文档 | 内容 | 读者 |
|------|------|------|
| [30-rag-design](agent/30-rag-design.md) | 向量库设计、检索策略、Prompt 组装、检索优化 | 算法、后端 |
| [31-langgraph-workflow](agent/31-langgraph-workflow.md) | 工作流节点、调用链路追踪、错误回溯 | 后端开发 |
| [32-metadata-sync](agent/32-metadata-sync.md) | 数据库元数据提取、初始化脚本、自动同步 | 数据工程师 |
| [33-testing](agent/33-testing.md) | 单元/集成/E2E 测试策略 | 测试、开发 |
| [34-llm-risks](agent/34-llm-risks.md) | LLM 成本、延迟、幻觉、稳定性、版本漂移 | 技术负责人 |

---

*设计文档版本: 2.0*
*日期: 2026-05-16*

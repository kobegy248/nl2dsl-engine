# 反馈闭环设计

## 设计目标

收集用户对查询结果的纠错反馈，形成"查询 → 纠错 → 改进"的闭环，持续优化语义理解质量。

## 收集机制

### API 接口

```
POST /api/v1/feedback
Content-Type: application/json

{
  "query_id": "uuid-of-query",
  "user_id": "u001",
  "corrected_dsl": { ... },    // 用户修正后的 DSL（可选）
  "comment": "销售额应该包含退款"  // 文字反馈（可选）
}
```

### 存储格式

每条反馈以 JSON Lines 格式追加写入 `feedback.jsonl`：

```json
{"query_id": "550e8400-e29b-41d4-a716-446655440000", "user_id": "u001", "corrected_dsl": {"metrics": [...]}, "comment": "..."}
{"query_id": "550e8400-e29b-41d4-a716-446655440001", "user_id": "u002", "corrected_dsl": null, "comment": "指标不对"}
```

## 数据结构

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query_id` | string | ✅ | 对应审计日志中的查询ID |
| `user_id` | string | ✅ | 反馈用户 |
| `corrected_dsl` | dict | ❌ | 用户修正后的 DSL，用于分析理解偏差 |
| `comment` | string | ❌ | 文字描述，用于定性分析 |

## 闭环流程

```
用户查询 ──→ 生成 DSL ──→ 执行 SQL ──→ 返回结果
                              │
                              ▼
                    用户对结果不满意
                              │
                              ▼
                    提交 feedback（corrected_dsl / comment）
                              │
                              ▼
                    写入 feedback.jsonl
                              │
                              ▼
                    ┌─────────────────────┐
                    │   定期分析反馈数据    │
                    │  1. 提取高频纠错模式  │
                    │  2. 更新语义层注册表   │
                    │  3. 补充 RAG 示例     │
                    │  4. 优化 Prompt       │
                    └─────────────────────┘
                              │
                              ▼
                    系统理解质量提升
```

## 当前限制

1. **手动分析**：当前 feedback 仅写入文件，需人工定期分析。未实现自动化处理
2. **无去重**：相同问题可能被多次反馈
3. **无关联**：未与审计日志自动关联（需通过 query_id 手动关联）

## 第五周实现（数据库 FeedbackStore）

第五周起，正式 API 默认使用数据库 `FeedbackStore`（与 Audit 共用同一 SQLAlchemy
Engine），JSONL Collector 保留为兼容适配器。

### 统一 FeedbackRequest

```json
{
  "query_id": "uuid",
  "user_id": "u001",
  "tenant_id": "t001",
  "is_correct": false,
  "issue_type": "metric",
  "corrected_dsl": {},
  "comment": "销售额口径不正确"
}
```

`issue_type` 枚举：`intent / metric / dimension / filter / time / join / ranking /
proportion / permission / result / other`。

### 写入前校验

- Audit `query_id` 必须存在。
- `user_id` 与审计记录一致。
- `tenant_id` 与审计记录一致。
- `corrected_dsl` 存在时通过 DSL Schema 校验。
- 至少提供 `is_correct=false` / `corrected_dsl` / 非空 `comment` 中的一项。

### tenant_id 强校验（修复）

- `FeedbackRequest.tenant_id` 必填且不得为空白：缺失 / 全空格返回 `422`。
- `FeedbackStore` 在 Store 层亦做防御性非空校验，不依赖 API 层 Pydantic。
- 审计记录有 `tenant_id` 时，请求 `tenant_id` 缺失 / 为空 / 不一致一律拒绝（`400`）；
  审计记录本身缺少 `tenant_id` 时也拒绝（无法证明同租户）。不返回其他租户的审计内容。

### 去重

`dedup_hash` = SHA-256(`query_id + user_id + tenant_id + is_correct + issue_type +
corrected_dsl + comment`，稳定排序 JSON）。重复提交返回原 `feedback_id`，
`deduplicated=true`，不重复插入。去重基于 `dedup_hash` 的 UNIQUE 约束**原子**完成：
直接 INSERT，捕获约束竞争后回查原 `feedback_id`，避免“先 SELECT 后 INSERT”竞态在
并发下抛 500。

### 不复制敏感数据

反馈表只保存关联 ID、用户纠正内容与必要元数据。原始 SQL、Trace、问题等继续以审计
日志为数据源，不在反馈表重复保存。`GET /api/v1/admin/feedback/{id}` 返回关联的审计
摘要（question / status / dsl），SQL 与 Trace 仍通过审计接口获取。

### 管理 API 的租户边界（修复）

`GET /api/v1/admin/feedback` 列表接口必须通过 `tenant_id` 限定租户范围；未提供返回
`400`，禁止未限定租户的全量查询。项目尚无认证框架，当前以强制 `tenant_id` 过滤为底线。

**详情接口同样强制租户隔离（第二轮审阅 P0）**：`GET /api/v1/admin/feedback/{feedback_id}`
必须提供非空 `tenant_id` 查询参数，未提供或空白返回 `400`。租户校验下沉到
`FeedbackStore.get(feedback_id, tenant_id=...)`，SQL 层直接 `AND tenant_id = :tenant_id`
过滤；记录不存在或属于其他租户统一返回 `404`，不泄露记录是否存在，响应不含其他租户的
反馈内容。反馈详情返回的审计摘要（`audit_summary`）同样按同一 `tenant_id` 过滤。


### 候选评测用例导出

```bash
python -m nl2dsl.feedback.exporter \
  --db-url "sqlite:///data/nl2dsl.db" \
  --output reports/feedback/candidates.yaml --status pending \
  --tenant-id t001
```

- `--db-url` **必填**：指向真实持久化数据库，不再默认创建空内存库并报告“导出 0 条”。
- `--tenant-id` 可选，限定租户范围；未提供时导出全部（需调用方已获授权）。
- 仅 `corrected_dsl` 非空的负反馈生成候选 DSL。
- 只有 comment 的反馈进入“待分析”列表，不猜测 expected DSL。
- `candidate_id` 基于 `query + corrected_dsl` 稳定生成（仅用 query 会冲突）；不把
  `DSL.data_source` 误当作业务 domain（domain 留空待人工补全）。
- 相同 query + corrected DSL 合并来源反馈 ID；输出稳定排序。
- 不直接写正式 Evaluation Dataset，不自动修改 Prompt / RAG / 业务 YAML。

## 未来增强

| 增强项 | 说明 | 优先级 |
|--------|------|--------|
| 自动化纠错模式提取 | 从 corrected_dsl 中自动发现常见的理解偏差 | P1 |
| 反馈去重 | 基于 query_id + corrected_dsl 哈希去重 | 已实现（第五周） |
| 反馈与审计关联查询 | 一键查询某条反馈对应的完整审计记录 | 已实现（第五周） |
| 反馈统计面板 | Web 端展示反馈趋势、高频问题 Top N | P3 |
| 自动 Prompt 优化 | 基于反馈自动调整 RAG few-shot 示例 | P3（需人工审核后入库） |

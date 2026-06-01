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

## 未来增强

| 增强项 | 说明 | 优先级 |
|--------|------|--------|
| 自动化纠错模式提取 | 从 corrected_dsl 中自动发现常见的理解偏差 | P1 |
| 反馈去重 | 基于 query_id + corrected_dsl 哈希去重 | P2 |
| 反馈与审计关联查询 | 一键查询某条反馈对应的完整审计记录 | P2 |
| 反馈统计面板 | Web 端展示反馈趋势、高频问题 Top N | P3 |
| 自动 Prompt 优化 | 基于反馈自动调整 RAG few-shot 示例 | P3 |

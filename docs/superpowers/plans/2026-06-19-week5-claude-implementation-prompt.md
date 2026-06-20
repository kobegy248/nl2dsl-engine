# Claude 开发提示词：第五周评估、反馈与可观测闭环

将下面整段内容交给 Claude：

---

你现在负责 NL2DSL 项目的第五周开发：**评估、反馈与可观测闭环**。

项目目录：

```text
D:\demo\db-gpt\NL2DSL
```

## 开始前必须阅读

按顺序阅读：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/specs/2026-06-19-week5-quality-feedback-observability-design.md`
4. `docs/superpowers/plans/2026-06-19-week5-quality-feedback-observability-plan.md`
5. `docs/evaluation/framework-guide.md`
6. `docs/feedback/feedback-loop-design.md`
7. `docs/audit/audit-log-design.md`

探索代码、查找符号和追踪调用链时优先使用 Codegraph。

## 核心目标

完成以下闭环：

```text
真实查询评测
  → rule/llm × optimizer on/off 矩阵
  → baseline 回归对比
  → 查询响应返回 query_id
  → 反馈校验并关联 Audit
  → 反馈持久化去重
  → 候选 Evaluation 用例导出
  → 固定格式质量报告
```

## P0 必须修复

### 1. 评测真实性

当前 `V2BenchmarkRunner.run_batch_with_optimizer()` 从测试用例 expected 构造 actual DSL。这是错误的。

必须改为调用真实查询链路获取 DSL、SQL、Trace 和结果。

禁止：

- 从 expected 构造 actual DSL。
- 使用期望答案作为 Optimizer 输入。
- LLM 不可用时静默 fallback 后仍标记为 LLM 模式。

### 2. Query ID

以下响应必须返回 `query_id`：

- `/api/v1/query`
- `/api/v1/query/dsl`
- `/api/v1/query/execute`
- SSE 最终 result 事件

### 3. 反馈契约与审计关联

统一 FeedbackRequest：

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

写入反馈前必须验证：

- Audit query_id 存在。
- user_id 匹配。
- tenant_id 匹配。
- corrected_dsl 合法。

## 实现要求

严格按照实施计划的 Phase 0 到 Phase 7 顺序推进。

### 评测

- 新增 `EvaluationObservation`。
- 新增真实 `EvaluationExecutor`。
- 支持 generator：rule / llm / all。
- 支持 optimizer：on / off / all。
- 支持 domain / tags 过滤。
- 每个矩阵组合独立构建执行环境。
- 支持 Baseline 保存、读取和 regression gate。
- 报告包含 domain、tag、matrix、失败/回退用例、延迟和 Optimizer 统计。

### Feedback

- 正式 API 默认使用数据库 FeedbackStore。
- 与 Audit 使用同一个 SQLAlchemy Engine。
- 实现稳定 SHA-256 去重。
- 重复提交返回原 feedback_id。
- 不在反馈表复制 SQL 和 Trace。
- JSONL Collector 可保留为兼容适配器。

### 候选用例

- 导出到 `reports/feedback/candidates.yaml`。
- 只处理 corrected_dsl 非空的负反馈。
- comment-only 进入待分析列表。
- 不直接写正式数据集。
- 不自动更新 Prompt、RAG 或业务 YAML。

### 质量报告

汇总：

- Evaluation 分数和回退。
- Audit 状态分布、P50/P95、Trace 完整率。
- Feedback 负反馈率、关联率、issue_type Top N、候选数量。

## 架构底线

- 不绕过 DSL。
- 不从自然语言直接生成 SQL。
- 不硬编码指标、维度或权限。
- 不自动相信用户反馈。
- 不自动修改语义配置、Prompt 或 RAG。
- 不复制不必要的敏感审计内容。
- 不为了测试通过而降低断言或跳过测试。

## 测试要求

至少覆盖：

1. expected 改变不会影响 actual DSL。
2. Optimizer OFF 真正不执行 Optimizer。
3. LLM 不可用时返回 unavailable。
4. domain / tags 过滤。
5. baseline 回退门禁。
6. 查询端点 query_id。
7. feedback audit/user/tenant 校验。
8. feedback 去重。
9. corrected_dsl 校验。
10. candidate YAML 去重和稳定输出。
11. comment-only 不生成伪 expected。
12. Trace 按路径计算完整率。

## 完成后必须执行

```bash
pytest tests/unit/ tests/evaluation/v2/ -q
pytest tests/integration/ tests/e2e/test_audit_query_api.py -q
python -m nl2dsl.evaluation.v2_cli --help
python -m nl2dsl.quality.cli --help
git diff --check
```

还需要运行一次真实 rule 模式评测，生成 JSON 和 Markdown 示例报告。

## 文档要求

更新：

- `docs/evaluation/framework-guide.md`
- `docs/evaluation/optimizer-guide.md`
- `docs/feedback/feedback-loop-design.md`
- `docs/audit/audit-log-design.md`
- `docs/api/21-api-contract.md`
- `docs/specs/2026-06-05-next-stage-roadmap.md`

正文使用中文。代码标识、命令和 API 字段保持英文。

## 最终回复格式

完成后请提供：

1. 实现摘要。
2. 修改文件列表。
3. 关键架构决策。
4. 测试命令和准确结果。
5. 未完成项或风险。
6. 不要自行提交或 push，等待代码审阅。

---

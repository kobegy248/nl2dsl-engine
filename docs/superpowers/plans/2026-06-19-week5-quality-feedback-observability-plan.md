# 第五周实施计划：评估、反馈与可观测闭环

> 对应设计：`docs/specs/2026-06-19-week5-quality-feedback-observability-design.md`

---

## 1. 实施约束

1. 必须先阅读设计文档和 AGENTS/CLAUDE 规则。
2. 使用 Codegraph 优先理解调用链。
3. 不允许从 expected 构造 actual DSL。
4. 不允许自动修改 Prompt、RAG 或 YAML 业务配置。
5. 保持现有 API 向后兼容，新增字段优先使用可选字段。
6. 所有新功能必须有 Evaluation 或测试覆盖。

---

## 2. Phase 0：建立真实评测观测模型

### 目标

用真实查询链路输出统一 EvaluationObservation。

### 文件

- 新增 `nl2dsl/evaluation/execution.py`
- 修改 `nl2dsl/evaluation/models.py`
- 修改 `nl2dsl/evaluation/v2_runner.py`
- 修改 `tests/evaluation/v2/test_v2_runner.py`
- 新增 `tests/evaluation/v2/test_execution.py`

### 任务

1. 新增 `EvaluationObservation`。
2. 新增 `EvaluationExecutor` Protocol。
3. 新增 `ApiEvaluationExecutor`。
4. `V2BenchmarkRunner` 接收 Executor，不再调用 `_build_dsl_from_case()` 作为 actual。
5. 删除或仅保留 `_build_dsl_from_case()` 为明确命名的测试 helper，生产 CLI 不得调用。
6. Observation 保存 DSL、SQL、Trace、query_id、错误和延迟。

### 测试

- Executor 正确提取 API 返回。
- error / clarification / unavailable 状态可评分且不崩溃。
- expected 内容变化不会改变 actual DSL。

---

## 3. Phase 1：评测矩阵与多领域

### 文件

- 修改 `nl2dsl/api_factory.py`
- 如有必要同步修改 `nl2dsl/api.py`
- 修改 `nl2dsl/evaluation/dataset.py`
- 修改 `nl2dsl/evaluation/models.py`
- 修改 `nl2dsl/evaluation/v2_cli.py`
- 修改 `tests/evaluation/v2/test_dataset_loader.py`
- 修改 `tests/evaluation/v2/test_v2_runner.py`
- 新增相关 CLI 测试

### 任务

1. `create_app()` 增加显式 `enable_optimizer`。
2. 为评测增加显式 generator mode：`rule` / `llm`。
3. LLM 模式无 Client 时返回 unavailable，不静默 fallback。
4. `V2TestCase` 增加 domain。
5. Loader 支持 case / YAML / 目录三级 domain 解析。
6. CLI 增加：
   - `--domain`
   - `--tags`
   - `--generator rule|llm|all`
   - `--optimizer on|off|all`
7. 每个矩阵组合使用独立 App/Executor，避免共享 sticky fallback 状态。

### 测试

- Optimizer OFF 的 Trace 不含 optimize_dsl。
- Optimizer ON 的 Trace 含 optimize_dsl。
- rule 与 llm 模式不会串线。
- domain 和 tags 过滤正确。

---

## 4. Phase 2：Baseline 与固定报告

### 文件

- 新增 `nl2dsl/evaluation/baseline.py`
- 修改 `nl2dsl/evaluation/v2_reporter.py`
- 修改 `nl2dsl/evaluation/v2_cli.py`
- 修改 `pyproject.toml`（如需要新增命令）
- 新增 `tests/evaluation/v2/test_baseline.py`
- 扩展 `tests/evaluation/v2/test_v2_reporter.py`

### 任务

1. 定义带 `schema_version` 的 Baseline JSON。
2. 保存 git commit、dataset hash、运行矩阵。
3. CLI 增加：
   - `--save-baseline`
   - `--baseline`
   - `--fail-on-regression`
   - `--max-dimension-drop`
   - `--max-case-drop`
4. 报告增加：
   - 按 domain
   - 按 tag
   - 按运行矩阵
   - 失败/回退用例
   - 延迟
   - Optimizer 统计
5. JSON 和 Markdown 内容来自同一个结构化 Report Model。

### 测试

- 相同结果对比 delta 为 0。
- 新失败用例触发非零退出码。
- 维度下降超过阈值触发失败。
- 报告顺序稳定，适合 Git diff。

---

## 5. Phase 3：统一 query_id 与反馈契约

### 文件

- 修改 `nl2dsl/api_factory.py`
- 同步修改 `nl2dsl/api.py`
- 修改 `web/src/types/api.ts`
- 新增或修改 API/E2E 测试

### 任务

1. QueryResponse、DSLGenerateResponse、DSLExecuteResponse 增加 query_id。
2. SSE 最终 result 事件增加 query_id。
3. 统一 FeedbackRequest：
   - query_id
   - user_id
   - tenant_id
   - is_correct
   - issue_type
   - corrected_dsl
   - comment
4. 保持旧字段可继续工作，必要时提供默认值。

### 测试

- 所有查询端点返回 query_id。
- query_id 能查询到对应 Audit。
- 前端类型与后端契约一致。

---

## 6. Phase 4：数据库 FeedbackStore 与审计关联

### 文件

- 新增 `nl2dsl/feedback/models.py`
- 新增 `nl2dsl/feedback/store.py`
- 修改 `nl2dsl/feedback/collector.py`
- 修改 `nl2dsl/api_factory.py`
- 同步修改 `nl2dsl/api.py`
- 修改 `tests/unit/test_feedback_collector.py`
- 新增 `tests/unit/test_feedback_store.py`
- 新增反馈关联 E2E 测试

### 任务

1. 创建 `nl2dsl_feedback` 表。
2. 实现稳定 dedup_hash。
3. 写入前查询 AuditLogger：
   - query 存在
   - user 匹配
   - tenant 匹配
4. corrected_dsl 使用 DSL Model 校验。
5. 重复提交返回原 feedback_id。
6. 增加反馈详情/列表管理 API，返回关联的必要审计摘要。
7. 不在 feedback 表复制 SQL 和 Trace。

### 测试

- 不存在 query_id 拒绝。
- 跨用户/跨租户反馈拒绝。
- 重复提交去重。
- corrected_dsl 非法时拒绝。
- 可联合获取原问题和原 DSL。

---

## 7. Phase 5：候选评测用例导出

### 文件

- 新增 `nl2dsl/feedback/exporter.py`
- 新增 `tests/unit/test_feedback_exporter.py`
- 修改 `pyproject.toml` 增加命令（可选）

### 任务

1. 从负反馈读取 corrected_dsl。
2. 关联 Audit 获取 question、domain、original_dsl。
3. 对 query + corrected_dsl 做稳定去重。
4. 输出 `reports/feedback/candidates.yaml`。
5. 只有 comment 的反馈进入待分析区，不生成 expected。
6. 不直接写正式 Evaluation Dataset。

### 测试

- 多条相同纠错合并来源 ID。
- YAML 输出稳定。
- comment-only 不生成伪 expected。
- 敏感 SQL/Trace 不进入候选文件。

---

## 8. Phase 6：质量报告

### 文件

- 新增 `nl2dsl/quality/__init__.py`
- 新增 `nl2dsl/quality/analyzer.py`
- 新增 `nl2dsl/quality/report.py`
- 新增 `nl2dsl/quality/cli.py`
- 新增 `tests/unit/test_quality_analyzer.py`
- 新增 `tests/unit/test_quality_report.py`
- 修改 `pyproject.toml`

### 任务

1. 汇总 Evaluation baseline/report。
2. 从 Audit 统计状态和延迟。
3. 从 Feedback 统计 issue_type 和负反馈率。
4. 实现按路径的 Trace 完整率。
5. 输出 JSON + Markdown。
6. 报告内容可复现、字段顺序稳定。

### 命令建议

```bash
nl2dsl-quality-report \
  --evaluation reports/v2/current.json \
  --output reports/quality
```

---

## 9. Phase 7：文档与最终验证

### 文档

- 更新 `docs/evaluation/framework-guide.md`
- 更新 `docs/evaluation/optimizer-guide.md`
- 更新 `docs/feedback/feedback-loop-design.md`
- 更新 `docs/audit/audit-log-design.md`
- 更新 `docs/api/21-api-contract.md`
- 更新第五周路线图状态

### 最终验证

```bash
pytest tests/unit/ tests/evaluation/v2/ -q
pytest tests/integration/ tests/e2e/test_audit_query_api.py -q
python -m nl2dsl.evaluation.v2_cli --help
python -m nl2dsl.quality.cli --help
git diff --check
```

需要额外执行至少一次真实 rule 模式评测，并保存示例 JSON/Markdown 报告。

---

## 10. 完成定义

- 真实运行评测替代 expected 构造 DSL。
- 支持 rule/llm × optimizer ON/OFF。
- Baseline 回退可以阻断 CI。
- QueryResponse 返回 query_id。
- 反馈和审计具备用户/租户级关联约束。
- 反馈具备持久化去重。
- 可导出候选评测用例。
- 可生成固定格式质量报告。
- 文档和测试完整。

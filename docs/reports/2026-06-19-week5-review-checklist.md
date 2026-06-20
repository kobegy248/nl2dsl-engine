# 第五周代码审阅清单

> 用于 Claude 完成开发后的正式代码审阅。

## 1. P0 正确性

- [ ] V2 actual DSL 来自真实执行，不来自 expected。
- [ ] Baseline 和 Optimized 使用同一问题、同一生成模式。
- [ ] Optimizer OFF 时没有执行 Optimizer。
- [ ] LLM 模式不可用时明确 unavailable。
- [ ] QueryResponse 和 SSE 返回 query_id。
- [ ] query_id 能查询到对应审计记录。
- [ ] 反馈写入检查 user_id 和 tenant_id。
- [ ] corrected_dsl 经过 DSL Schema 校验。

## 2. 数据安全

- [ ] Feedback 表不复制 SQL 和 Trace。
- [ ] 管理 API 不泄漏跨租户数据。
- [ ] dedup_hash 不包含不稳定序列化。
- [ ] 用户反馈不会自动修改配置或 RAG。
- [ ] 候选用例不包含敏感 SQL、Trace 或结果明细。

## 3. 评测可信度

- [ ] rule/llm × optimizer on/off 模式真实独立。
- [ ] sticky LLM fallback 状态不会污染其他矩阵。
- [ ] domain 和 tags 过滤真实生效。
- [ ] unavailable 不计为通过。
- [ ] 报告按 case ID 稳定排序。
- [ ] baseline 包含 dataset hash 和 schema version。
- [ ] regression gate 对新增失败和维度回退生效。

## 4. 反馈闭环

- [ ] 重复反馈返回同一 feedback_id。
- [ ] 不存在的 query_id 被拒绝。
- [ ] 跨用户和跨租户反馈被拒绝。
- [ ] corrected_dsl 反馈可生成候选用例。
- [ ] comment-only 反馈不会被猜测成 expected DSL。
- [ ] 候选用例保留 source_feedback_ids。
- [ ] 候选文件不会直接写正式 dataset。

## 5. 可观测性

- [ ] 简单查询 Trace 完整率规则正确。
- [ ] Clarification 路径不套用简单成功路径。
- [ ] Agent 复杂路径有独立检查规则。
- [ ] P50/P95 算法对空数据和单条数据安全。
- [ ] Audit/Feedback 关联率可验证。

## 6. 工程质量

- [ ] API Factory 和正式 API 契约同步。
- [ ] 前端 TypeScript 类型同步。
- [ ] 没有业务逻辑堆在路由层。
- [ ] 没有硬编码 ecommerce 作为所有 domain。
- [ ] 新模块职责清晰，没有重复 Reporter/Model。
- [ ] JSON/Markdown 来自同一结构化报告。
- [ ] 无无关重构或大范围格式化。

## 7. 测试验收

- [ ] 新增单元测试。
- [ ] 新增集成测试。
- [ ] 新增 E2E 测试。
- [ ] Evaluation v2 全部通过。
- [ ] Audit 和 Feedback 相关测试通过。
- [ ] `git diff --check` 通过。
- [ ] 真实 rule 模式报告成功生成。
- [ ] 报告中的数字与用例结果一致。

## 8. 审阅输出格式

审阅时按严重程度输出：

1. P0：数据错误、安全漏洞、评测失真。
2. P1：可靠性、兼容性、回归风险。
3. P2：设计、维护性、测试缺口。

每条问题必须包含文件和行号、影响、修复建议。

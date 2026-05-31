# NL2DSL — 自然语言语义查询层

> 让业务人员用自然语言直接查数，系统自动理解语义、校验口径、保障安全。

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-732%20passed-brightgreen.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**NL2DSL 是一个面向数据治理的自然语言语义查询层。**

它不替代你的数据仓库或 BI 工具，而是在业务人员和数据库之间建立一个**语义层**：业务说"华东销售额"，系统自动理解成 `SUM(pay_amount) WHERE region_code='HD'`——同时保证口径一致、权限受控、全程可审计。

---

## 解决什么问题

传统数据架构中，业务人员看不懂数据库里的 `pay_amt`、`region_cd`，数据团队疲于应付各种"帮我拉个数"。NL2SQL 方案虽然让业务直接问数，但**幻觉严重、不可控、无权限保障**。

NL2DSL 在这之间插入一个**语义层**：

```
业务人员 ──→ "查华东销售额" ──→ 语义层 ──→ 数据库
                                   ↑
                              销售额 = SUM(pay_amt)
                              华东 = region_cd='HD'
                              权限：只能看华东
                              审计：谁在查、查了什么
```

语义层的核心资产是**治理定义**——指标口径、维度编码、权限策略。NL2DSL 消费这些定义，把自然语言翻译成安全、可控的查询。

---

## 效果演示

![NL2DSL Demo](docs/demo.gif)

输入"华东销售额最高的5个产品"，系统自动完成语义匹配 → DSL 生成 → SQL 执行 → 安全扫描 → 返回结果。全过程透明可追溯。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **语义理解** | "华东销售额"自动映射为 `SUM(pay_amount) WHERE region='HD'` |
| **多层安全** | DSL 校验 → 权限注入 → SQL 扫描 → 沙箱预检，逐层拦截 |
| **复杂查询拆解** | "对比华东华南趋势"自动拆子查询并行执行 |
| **Agent 自修正** | 歧义追问、DSL 校验失败自动修正、执行后自检 |
| **多域自治** | 一套系统服务多个业务团队，各域配置完全隔离 |
| **SSE 流式响应** | 复杂查询实时展示执行进度 |

**与传统 NL2SQL 的核心区别**：LLM 只生成结构化 DSL（可校验），系统负责 SQL 构建、权限注入和安全执行。不是黑盒 SQL，是**白盒可治理的查询管道**。

---

## 快速开始

```bash
# 安装
pip install -r requirements.txt

# 配置
cp .env.example .env
# 填入 LLM API Key（支持智谱 / Ollama / 任意 OpenAI 兼容接口）

# 准备治理配置（指标、维度、数据源）
mkdir -p configs
# 参考 configs/metrics.example.yaml

# 启动
uvicorn nl2dsl.api:app --reload --host 0.0.0.0 --port 8000

# 查询
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "查询华东地区的销售额", "user_id": "u001"}'
```

完整启动指南见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 架构与技术细节

- **查询管道**：10+ 节点的 LangGraph 状态机，含歧义检测、DSL 校验、权限注入、安全扫描、沙箱预检
- **Agent 编排**：7 种查询意图自动识别，复杂问题拆分子查询并行执行
- **双层架构**：Agent 层负责宏观编排（意图识别、多查询调度），Graph 层负责微观执行（单查询 DSL→SQL→数据）

详细架构文档、完整 API 参考、项目结构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 评测 (Evaluation)

运行评测套件，量化 NL→DSL 各维度准确率：

```bash
# 安装评测依赖
pip install -e ".[dev]"

# 运行完整评测
nl2dsl-eval --dataset tests/evaluation/dataset --output reports/ --format both

# 仅评测指定 domain
nl2dsl-eval --dataset tests/evaluation/dataset --domain ecommerce --format markdown

# 仅评测指定标签的用例
nl2dsl-eval --dataset tests/evaluation/dataset --tags filter join --output reports/
```

评测报告示例（Markdown）：

```
# NL2DSL Evaluation Report

**Generated:** 2026-05-31T10:30:00
**Total Cases:** 50
**Execution Time:** 45.2s

## Overall Score

### 87.3%

| Metric | Value |
|--------|-------|
| Passed | 43 |
| Failed | 7 |
| Pass Rate | 86.0% |

## By Category

| Category | Weight | Score |
|----------|--------|-------|
| Semantic | 56% | 88.5% |
| Planning | 14% | 75.0% |
| Execution | 20% | 90.0% |
| Governance | 10% | 65.0% |

## Per Domain

| Domain | Cases | Passed | Failed | Avg Score |
|--------|-------|--------|--------|-----------|
| ecommerce | 30 | 27 | 3 | 89.5% |
| bank | 10 | 8 | 2 | 84.2% |
| supply_chain | 10 | 8 | 2 | 82.1% |
```

### 评测维度说明（4 大类 12 维度）

| 类别 | 维度 | 权重 | 评分方式 |
|------|------|------|---------|
| **Semantic** | Intent | 8% | data_source 精确匹配 (0/1) |
| | Metric | 20% | func + field + alias 部分匹配 |
| | Dimension | 12% | Jaccard 相似度 |
| | Filter | 16% | field + operator + value 部分匹配 |
| **Planning** | Join | 7% | table + on_field + join_type 匹配 |
| | Limit | 4% | 精确匹配 |
| | OrderBy | 3% | 序列感知匹配 |
| **Execution** | SQL Success | 10% | SQL 执行成功 (0/1) |
| | Result Accuracy | 10% | 查询结果数据对比 |
| **Governance** | Permission | 4% | 敏感字段越权拦截 |
| | Masking | 3% | 敏感数据脱敏检查 |
| | Audit | 3% | 审计日志记录 |

评测框架支持自定义权重：
```bash
nl2dsl-eval --dataset tests/evaluation/dataset --weights metric=0.3 filter=0.25
```

---

## License

MIT

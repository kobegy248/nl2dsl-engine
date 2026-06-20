# 评估框架使用指南

## 概述

NL2DSL 评估框架提供 **4 大类 12 维度** 的量化评估能力，将"准不准"转化为可量化的数学题。

| 类别 | 权重 | 维度 |
|------|------|------|
| **Semantic** | 56% | Intent / Metric / Dimension / Filter |
| **Planning** | 14% | Join / Limit / OrderBy |
| **Execution** | 20% | SQL Success / Result Accuracy |
| **Governance** | 10% | Permission / Masking / Audit |

## 快速开始

### 安装

```bash
pip install -e ".[dev]"
```

### 运行评估

```bash
# 完整评估（所有 domain）
nl2dsl-eval --dataset tests/evaluation/dataset --output reports/ --format both

# 仅评估指定 domain
nl2dsl-eval --dataset tests/evaluation/dataset --domain ecommerce --format markdown

# 仅评估指定标签
nl2dsl-eval --dataset tests/evaluation/dataset --tags filter join --output reports/

# 自定义通过阈值
nl2dsl-eval --dataset tests/evaluation/dataset --threshold 0.75

# 自定义权重
nl2dsl-eval --dataset tests/evaluation/dataset --weights metric=0.3 filter=0.25
```

### 输出格式

**Markdown 报告**：
```
# NL2DSL Evaluation Report

## Overall Score: 87.3%

## By Category
| Category | Weight | Score |
| Semantic | 56% | 88.5% |
| Planning | 14% | 75.0% |
| Execution | 20% | 90.0% |
| Governance | 10% | 65.0% |
```

**JSON 报告**：结构化数据，供 CI/CD 消费。

## 添加测试用例

### 1. 创建 YAML 文件

在 `tests/evaluation/dataset/{domain}/` 下创建 `.yaml` 文件：

```yaml
test_cases:
  - id: ec_filter_001
    query: "查询华东地区的销售额"
    description: "Aggregation with region filter"
    tags: ["aggregation", "filter"]
    expected_dsl:
      data_source: orders
      metrics:
        - func: sum
          field: pay_amount
          alias: sales_amount
      dimensions: []
      filters:
        - field: region
          operator: "="
          value: 华东
      order_by: []
      limit: 10
```

### 2. 用例设计原则

| 原则 | 说明 |
|------|------|
| 一个用例测一个维度 | 避免同时改多个维度导致无法定位问题 |
| `id` 有语义 | `ec_filter_001` = ecommerce + filter + 序号 |
| `tags` 打标签 | 便于按标签过滤运行子集 |
| `expected_dsl` 完整 | 包含所有字段，即使为空也要显式写 `[]` |

### 3. 运行新用例

```bash
nl2dsl-eval --dataset tests/evaluation/dataset --tags filter
```

## 解读报告

### Category Score 分析

| Category 得分低 | 可能原因 | 排查方向 |
|----------------|---------|---------|
| Semantic ↓ | LLM 理解偏差 | 检查 RAG 召回、Prompt 质量 |
| Planning ↓ | 查询结构错误 | 检查 LangGraph DSL 生成节点 |
| Execution ↓ | SQL 构建或执行问题 | 检查 SQL Builder、数据库连接 |
| Governance ↓ | 安全合规漏洞 | 检查权限配置、脱敏规则 |

### 维度细查

报告会列出每个维度的得分。重点关注低于 0.8 的维度：

```
Intent        ████████████████████████████████░░░░░░░░ 80.0%
Metric        ██████████████████████████████░░░░░░░░░░ 75.0%  ← 重点关注
Dimension     ████████████████████████████████████░░░░ 90.0%
Filter        ██████████████████████████░░░░░░░░░░░░░░ 70.0%  ← 重点关注
```

## CI/CD 集成

### GitHub Actions 示例

```yaml
- name: Run Evaluation
  run: |
    nl2dsl-eval \
      --dataset tests/evaluation/dataset \
      --output reports/ \
      --format both \
      --threshold 0.75

- name: Upload Report
  uses: actions/upload-artifact@v4
  with:
    name: eval-report
    path: reports/
```

### 基线对比

保存上版本的评估结果作为基线，新版本的任何 Category 得分不应低于基线：

```bash
# 保存基线
nl2dsl-eval --dataset tests/evaluation/dataset --output baseline.json --format json

# 对比（自定义脚本）
python scripts/compare_baseline.py --current reports/eval.json --baseline baseline.json
```

## V2 真实评测（第五周）

V2 框架在第五周重构为**真实查询链路评测**：actual DSL 不再从测试用例 `expected`
构造，而是通过 `ApiEvaluationExecutor` 调用真实 `/api/v1/query` 获取 DSL、SQL、
Trace 与结果，评分器只读取真实 `EvaluationObservation`。

### 矩阵

同一用例集支持 generator × optimizer 矩阵：

| 生成模式 | Optimizer | 用途 |
|----------|-----------|------|
| rule | off | 无 LLM、无优化基线 |
| rule | on | 规则生成 + Optimizer 收益 |
| llm | off | LLM 原始语义能力 |
| llm | on | 完整生产链路能力 |

`llm` 模式无可用 LLM Client 时，用例状态标记为 `unavailable`，不静默退化到规则
生成，也不计为通过。

### 矩阵结果按组合身份保存（修复）

矩阵结果使用稳定组合身份 `domain + case_id + generator + optimizer` 作为键，
**同一用例的 rule/off、rule/on、llm/off、llm/on 四条结果互不覆盖**。Baseline 与
回归门禁按相同组合比较，禁止跨 generator 或 optimizer 模式比较。Markdown 与 JSON
报告同源，均能展示每个组合，且输出稳定排序。

### CLI

```bash
# 真实 rule 基线
python -m nl2dsl.evaluation.v2_cli \
  --dataset tests/evaluation/dataset/v2 \
  --generator rule --optimizer off \
  --output reports/v2

# 矩阵全量（rule/llm × on/off）
python -m nl2dsl.evaluation.v2_cli \
  --dataset tests/evaluation/dataset/v2 \
  --generator all --optimizer all

# 过滤（按真实业务 domain，v2 是版本目录不是 domain）
python -m nl2dsl.evaluation.v2_cli --dataset ... --domain ecommerce --tags ranking,time

# Baseline 保存与回归门禁
python -m nl2dsl.evaluation.v2_cli --dataset ... \
  --save-baseline reports/baselines/rule-optimizer-off.json
python -m nl2dsl.evaluation.v2_cli --dataset ... \
  --baseline reports/baselines/rule-optimizer-off.json \
  --fail-on-regression --max-dimension-drop 0.02 --max-case-drop 0.10
```

### 回归门禁默认规则

- Overall 不得下降。
- 任一评分维度下降超过 `--max-dimension-drop`（默认 2 个百分点）则失败。
- 单用例分数下降超过 `--max-case-drop`（默认 10 个百分点）则失败。
- 新增失败用例则失败。
- Baseline 中存在、当前评测缺失的 case / matrix 组合视为回退（不再静默跳过）。
- `unavailable` 不算通过。
- `--fail-on-regression` 时门禁失败返回非零退出码。

### Baseline 数据集与矩阵兼容性（修复）

- `dataset_hash` 覆盖影响评测语义的全部字段：`id / domain / query / expected / tags /
  category / difficulty`。修改 `expected`、`domain` 或 `tags` 都会改变 hash；字典键
  顺序与用例顺序不影响 hash。
- 比较前校验 `schema_version`、`dataset_hash` 与 `matrix_combos`；任一不兼容默认
  门禁失败并给出明确原因，不得静默继续。需重新建立 Baseline 时使用 `--save-baseline`
  覆盖旧文件。

### Baseline 身份校验 fail-closed（第二轮审阅 P1）

必需身份字段为 `schema_version` / `dataset_hash` / `matrix_combos`，比较前 fail-closed
校验，**不得**默认按零分继续比较后放行：

- Baseline 或当前报告任一必需身份字段缺失、为空或格式错误 → 门禁失败，原因标注
  “Baseline 不兼容或损坏”。
- `matrix_combos=[]`（空列表，合法的“无矩阵”身份）与字段缺失严格区分：空列表不触发
  失败，缺失即损坏。
- 不支持的 `schema_version`（不在 `SUPPORTED_SCHEMAS`）→ 明确失败，提示重新建立 Baseline。
- `dataset_hash` 不一致 → 提示评测用例集合已改变，需 `--save-baseline` 重建。
- 当前报告由 CLI 自动注入 `schema_version`（`BASELINE_SCHEMA_VERSION`）与 `dataset_hash`，
  保证身份字段齐全。

### Graph 重试终止条件（第三轮审阅 P0）

LangGraph 查询管道的每次校验 / 执行重试都依赖**可证明增长**的计数器，达到上限后
必须进入终止 `error` 节点，禁止任何错误路径无限回到自身（此前 bank / supply_chain
因规则生成器发明 ecommerce 指标导致 `validate_dsl ↔ correct_dsl` 死循环，撞
`GRAPH_RECURSION_LIMIT`）：

- `dsl_attempts` / 校验重试计数：每次 `route_after_validate` 重试自增；连续无进展
  （`correct_dsl` 不再改变 DSL）或达到最大尝试次数 → 路由到 `END` 并保留最后一次
  明确失败原因。
- 执行重试计数：`route_after_execute` 在 SQL 执行失败时重试，计数自增；达到上限 →
  `END`。`simplify_dsl` 计数同理。
- 不可修复的 DSL 快速失败，不得运行约 15 秒后撞 recursion limit。
- `--generator rule` 模式强制 `llm_client=None`，由 `RuleBasedDSLGenerator` 按各领域
  registry 生成合法 DSL（metric / dimension / data_source 均来自该领域 registry，
  不发明 ecommerce 字段），从根源避免校验失败循环。

### execution error 的 CLI 退出码（第三轮审阅 P1）

V2 CLI 区分三类结果，**不再把 100% 执行错误视为成功**：

- 语义评分未达阈值：按回归门禁处理（仅 `--fail-on-regression` 时非零）。
- 用例正常失败（有可评分结果）：默认退出码 0。
- 评测基础设施 / 执行链路异常：**默认非零退出码**，至少包括：
  - 所有选中用例均为 `error`（`execution_errors == total`）。
  - 出现 `GRAPH_RECURSION_LIMIT`（`recursion_errors > 0`）。
  - 报告无法生成或 JSON 无法解析。
  - 没有任何可评分结果。
- `--fail-on-execution-error`：显式开关，任一执行错误即返回非零（默认保守，不启用）。
- 报告 `summary` 新增 `execution_errors` 与 `recursion_errors` 计数；Markdown 明确区分
  评分失败与执行错误，不把普通低分自动等同基础设施错误。Baseline 回归逻辑保持不回退。

### 报告 JSON 完整性保证（第三轮审阅 P1）

所有生成的报告必须通过标准 JSON parser（PowerShell `ConvertFrom-Json` / Python
`json.load`）：

- 报告写入采用 UTF-8，错误信息中的换行 / 控制字符不得破坏 JSON 结构。
- 原子写入：先写临时文件再替换，避免中途中断留下半文件覆盖上一份有效报告。
- CLI 生成后立即用 `json.load()` 回读验证；解析失败返回非零退出码。
- `summary` 必含 `execution_errors` / `recursion_errors` 字段。

### 多领域（修复）

`V2TestCase.domain` 解析优先级：用例 `domain` → YAML 顶层 `domain` → 默认
`ecommerce`。**数据集结构目录名（如版本目录 `v2`）不是业务 domain**，不得作为
domain 回退。

每个业务领域使用对应的 `DomainContext`、语义配置、权限配置与执行环境：
`EvaluationExecutor` 按 `case.domain` 路由到对应领域的 App（`app_domain`），
未知 / 未配置领域返回 `error` 观测，**不静默回退 ecommerce**。多领域配置通过
`ExecutorConfig.domains: dict[str, DomainAppConfig]` 提供；单领域兼容模式仅服务
`default_domain`。

### 默认 V2 CLI 的三领域环境（第二轮审阅 P1）

`build_default_executor_config()` 默认构造**真实多领域** `ExecutorConfig.domains`，
包含三个业务领域，各自独立配置：

| 领域 | 样例数据库 | registry | 权限 | 评测用户 / 租户 |
|------|-----------|----------|------|----------------|
| `ecommerce` | `create_mock_database` | `samples/metrics.yaml` | `samples/permissions.yaml` | `u001` / `t001` |
| `bank` | `create_mock_bank_database` | `samples/bank_metrics.yaml` | `samples/bank_permissions.yaml` | `b001` / `t001` |
| `supply_chain` | `create_mock_supply_chain_database` | `samples/supply_chain_metrics.yaml` | `samples/supply_chain_permissions.yaml` | `sc001` / `t001` |

- 每个 `DomainAppConfig` 拥有独立 engine / registry_dict / permissions /
  sensitive_columns / masking_rules / eval_user_id / eval_tenant_id，避免跨领域串用定义。
- 用例按 `case.domain` 进入对应配置；`--domain` 过滤后只运行该领域用例（行为明确）。
- 未知领域由执行器返回 `error`，不静默回退 ecommerce。
- `--config` 显式覆盖时退化为单领域 ecommerce（兼容旧用法）。
- 样例数据与配置来自正式包 `nl2dsl/testing/sample_data` 与 `nl2dsl/evaluation/samples`，
  不依赖 `tests.*`。


### 评分说明

- 真实 DSL 不携带 `intent` 字段，按结构推导（`post_process.group_top_n` → rank，
  其余 → aggregate）。
- 评分前剥离治理注入的过滤条件（`tenant_id` 与行级权限），避免把权限注入误判为
  语义过滤偏差。
- 不可评分状态（error / clarification / unavailable）按 0 分处理且不通过，但不崩溃。

## 模块结构

```
nl2dsl/evaluation/
├── models.py       # 数据模型：EvalTestCase, ScoreBreakdown, TestResult, GovernanceInfo
├── scoring.py      # 评分引擎：12 维度评分逻辑 + 权重计算
├── runner.py       # 运行器：调用 API、收集 governance 信息、批量执行
├── report.py       # 报告生成：JSON + Markdown 格式化
├── dataset.py      # 数据集加载：YAML 解析、按 domain/tag 过滤
└── cli.py          # 命令行入口：nl2dsl-eval
```

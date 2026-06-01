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

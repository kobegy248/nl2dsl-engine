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

## License

MIT

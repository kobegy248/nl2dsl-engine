# NL2DSL 查询完整流程图

本文档描述用户自然语言查询从请求到结果返回的完整处理链路，基于 LangGraph StateGraph 架构。

---

## 一、顶层架构概览

```
用户请求 → API 层 → LangGraph StateGraph → 审计日志 → 返回响应
              ↓
         ┌──────────────────────────────────────────────┐
         │  clarification → validation 子图 →           │
         │  permission_check 子图 → resolve_semantic →  │
         │  build_sql → scan_sql → sandbox_check →      │
         │  [human_review] → execute_sql → END           │
         └──────────────────────────────────────────────┘
```

---

## 二、主查询链路详细流程图 (`POST /api/v1/query`)

```mermaid
flowchart TD
    START([用户发起 POST /api/v1/query]) --> INIT["1. API 层<br/>生成 query_id<br/>构建 QueryState<br/>初始化状态"]

    INIT --> GRAPH["2. LangGraph StateGraph<br/>graph.ainvoke(state, config)"]

    %% StateGraph 内部节点
    subgraph STATEGRAPH["StateGraph 执行链路"]
        direction TB

        ENTRY([START]) --> CLARIFY["clarification_node<br/>ClarificationDetector.detect()<br/>• 时间缺失<br/>• 指标歧义<br/>• 维度歧义"]

        CLARIFY --> ROUTE_CLARIFY{"route_after_clarification"}
        ROUTE_CLARIFY -->|"发现歧义"| END_CLARIFY([END<br/>status=clarification])
        ROUTE_CLARIFY -->|"无歧义"| VALIDATION["validation 子图"]

        %% 验证子图
        subgraph VALIDATION_SUB["验证子图 (validation)"]
            V_ENTRY --> V_ROUTE_LLM{"route_llm_availability<br/>llm_client 是否配置?"}
            V_ROUTE_LLM -->|"未配置"| MOCK_DSL["mock_dsl_node<br/>_mock_dsl_from_question()<br/>关键词匹配生成 DSL"]
            V_ROUTE_LLM -->|"已配置"| GEN_DSL["generate_dsl_node<br/>LLM + RAG 生成 DSL"]

            GEN_DSL -->|"失败"| MOCK_DSL
            GEN_DSL -->|"成功"| VALIDATE["validate_dsl_node<br/>DSLValidator.validate()"]
            MOCK_DSL --> VALIDATE

            VALIDATE --> V_ROUTE_VAL{"route_after_validate<br/>校验通过?"}
            V_ROUTE_VAL -->|"通过"| V_EXIT([子图 END])
            V_ROUTE_VAL -->|"失败(可重试)"| CORRECT["correct_dsl_node<br/>错误反馈 + 重新生成"]
            V_ROUTE_VAL -->|"失败(已达上限)"| V_ERR([子图 END<br/>status=error])
            CORRECT --> VALIDATE
        end
        V_ENTRY([子图 START])

        VALIDATION --> PERM["permission_check 子图"]

        %% 权限子图
        subgraph PERM_SUB["权限子图 (permission_check)"]
            P_ENTRY --> INJECT_ROW["inject_row_permission_node<br/>RowLevelSecurity.inject()<br/>• 注入 row_filters<br/>• 注入 tenant_id 隔离"]
            INJECT_ROW --> P_ROUTE{"错误?"}
            P_ROUTE -->|"错误"| P_ERR([子图 END<br/>status=error])
            P_ROUTE -->|"正常"| CHECK_COL["check_col_permission_node<br/>ColumnLevelSecurity.check()<br/>• 敏感字段黑名单"]
            CHECK_COL --> P_EXIT([子图 END])
        end
        P_ENTRY([子图 START])

        PERM --> RESOLVE["resolve_semantic_node<br/>SemanticResolver.resolve()<br/>• 指标展开: alias → SQL expr<br/>• value_map 值映射"]

        RESOLVE --> BUILD_SQL["build_sql_node<br/>SQLBuilder.build()<br/>• 恢复 metric 原始字段名<br/>• 解析 JOIN<br/>• 编译 SQL"]

        BUILD_SQL --> ROUTE_COMPLEXITY{"detect_complexity<br/>简单/复杂查询?"}
        ROUTE_COMPLEXITY -->|"简单"| SCAN_SQL["scan_sql_node<br/>SQLScanner.scan()<br/>基础安全扫描"]
        ROUTE_COMPLEXITY -->|"复杂"| SCAN_SQL
        ROUTE_COMPLEXITY -->|"错误"| END_ERR([END<br/>status=error])

        SCAN_SQL --> SANDBOX["sandbox_check_node<br/>QuerySandbox.check()<br/>• EXPLAIN 估算扫描行数<br/>• LIMIT 预览执行时间<br/>• 检测缺少 WHERE"]

        SANDBOX --> ROUTE_SANDBOX{"route_after_sandbox<br/>检查通过?"}
        ROUTE_SANDBOX -->|"有风险"| HUMAN_REVIEW["human_review_node<br/>标记 pending_review<br/>(有 checkpointer 时中断)"]
        ROUTE_SANDBOX -->|"通过"| EXEC_SQL["execute_sql_node<br/>engine.execute()<br/>转换为 dict list"]

        HUMAN_REVIEW --> ROUTE_HUMAN{"route_after_human_review<br/>用户批准?"}
        ROUTE_HUMAN -->|"批准"| EXEC_SQL
        ROUTE_HUMAN -->|"拒绝"| END_REJECT([END<br/>status=rejected])

        EXEC_SQL --> ROUTE_EXEC{"route_after_execute<br/>执行成功?"}
        ROUTE_EXEC -->|"失败(可重试)"| SIMPLIFY["simplify_dsl_node<br/>去除 JOIN / 减少维度"]
        ROUTE_EXEC -->|"成功"| END_OK([END<br/>status=success])
        ROUTE_EXEC -->|"失败(已达上限)"| END_ERR

        SIMPLIFY --> BUILD_SQL
    end

    GRAPH --> EXTRACT["3. API 层提取结果<br/>从 QueryState 构建 QueryResponse"]

    EXTRACT --> AUDIT["4. 审计日志记录<br/>AuditLogger.log()<br/>含完整 trace"]

    AUDIT --> RESPONSE["返回响应<br/>status=success/error/clarification/pending_review"]
    RESPONSE --> END([结束])
```

---

## 三、各阶段状态码与异常映射表

| 阶段 | 状态/异常类型 | Error Code | HTTP Status | 触发场景 |
|------|-------------|-----------|-------------|---------|
| 歧义澄清 | `status=clarification` | — | 200 | 检测到时间缺失/指标歧义/维度歧义 |
| Sandbox 警告 | `status=warning` | — | 200 | 扫描行数超限 / 执行时间超限 / 缺少 WHERE 条件 |
| DSL 生成 | ValidationError | VALIDATION_ERROR | 400 | 验证子图重试耗尽 |
| DSL 校验 | ValidationError | VALIDATION_ERROR | 400 | 数据源/指标/维度不存在 |
| 行级权限 | — | — | — | 无权限配置则直通 |
| 列级权限 | PermissionError | PERMISSION_DENIED | 403 | 访问敏感字段 |
| 语义解析 | SemanticError | SEMANTIC_ERROR | 400 | 指标未定义 |
| SQL 构建 | ValidationError | VALIDATION_ERROR | 400 | 表不存在 / 列不存在 / 非法表达式 |
| SQL 扫描 | ValidationError | VALIDATION_ERROR | 400 | 检测到危险 SQL 模式 |
| SQL 执行 | Exception | INTERNAL_ERROR | 500 | 数据库执行失败 |
| 人工审核 | `status=pending_review` | — | 200 | 沙箱检测风险，等待人工确认 |
| 审计查询 | NotFoundError | NOT_FOUND | 404 | 审计记录不存在 |

---

## 四、StateGraph 节点详解

### 4.1 节点清单

| 节点 | 所在文件 | 说明 |
|------|---------|------|
| `clarification` | `builder.py` | 歧义检测，有歧义直接 END |
| `validation` (子图) | `subgraphs.py` | DSL 生成 + 校验 + 修正循环 |
| `permission_check` (子图) | `subgraphs.py` | 行级权限注入 + 列级权限检查 |
| `resolve_semantic` | `builder.py` | 指标展开为 SQL 表达式 |
| `build_sql` | `builder.py` | SQLAlchemy Core 构建 SQL |
| `scan_sql` | `builder.py` | SQL 安全扫描 |
| `sandbox_check` | `builder.py` | 预执行安全检测 |
| `human_review` | `builder.py` | 人工审核标记（可中断） |
| `execute_sql` | `builder.py` | 数据库执行 |
| `simplify_dsl` | `builder.py` | 简化 DSL 后重试 |

### 4.2 条件路由

| 路由函数 | 判断条件 | 分支 |
|---------|---------|------|
| `route_after_clarification` | `ambiguities` 是否存在 | `clarification` → END / `continue` → validation |
| `route_llm_availability` | `llm_client` 是否配置 | `llm` → generate_dsl / `mock` → mock_dsl |
| `route_after_validate` | 校验结果 + 重试次数 | `ok` → END / `retry` → correct_dsl / `error` → END |
| `detect_complexity` | joins / metrics / dimensions 数量 | `simple` / `complex` → scan_sql |
| `route_after_sandbox` | `sandbox_result.passed` | `review` → human_review / `execute` → execute_sql |
| `route_after_execute` | 执行结果 + 重试次数 | `retry` → simplify_dsl / `end` → END |
| `route_on_error` | `error_code` 是否致命 | `end` → END / `continue` → 尝试恢复 |

---

## 五、验证子图内部流程

```mermaid
flowchart TD
    subgraph VALIDATION["验证子图 (validation)"]
        START_V([START]) --> ROUTE_LLM{"LLM 已配置?"}
        ROUTE_LLM -->|"否"| MOCK["mock_dsl_node<br/>关键词匹配生成"]
        ROUTE_LLM -->|"是"| GEN["generate_dsl_node<br/>LLM + RAG 生成"]

        GEN -->|"成功"| DSL1["DSL 对象"]
        GEN -->|"失败<br/>异常/超时/空返回"| MOCK

        MOCK --> DSL2["DSL 对象"]
        DSL1 --> VALIDATE["validate_dsl_node<br/>DSLValidator.validate()"]
        DSL2 --> VALIDATE

        VALIDATE --> ROUTE_VAL{"校验通过?"}
        ROUTE_VAL -->|"是"| DONE([END<br/>返回 DSL])
        ROUTE_VAL -->|"否 (可重试)"| CORRECT["correct_dsl_node<br/>错误反馈 + 重新生成"]
        ROUTE_VAL -->|"否 (已达上限)"| ERR([END<br/>status=error])

        CORRECT --> VALIDATE
    end
```

**关键设计**: LLM 失败不 fallback 到 mock，而是重试修正。mock 只在 LLM 未配置时使用。

---

## 六、权限子图内部流程

```mermaid
flowchart TD
    subgraph PERMISSION["权限子图 (permission_check)"]
        START_P([START]) --> INJECT["inject_row_permission_node<br/>RowLevelSecurity.inject()"]
        INJECT --> ROUTE_P{"错误?"}
        ROUTE_P -->|"错误"| ERR_P([END<br/>status=error])
        ROUTE_P -->|"正常"| CHECK["check_col_permission_node<br/>ColumnLevelSecurity.check()"]
        CHECK --> DONE_P([END])
    end
```

---

## 七、Mock DSL 生成逻辑

```mermaid
flowchart TD
    A["用户问题"] --> B["问题转小写"]
    B --> JOIN_CHECK{"包含 JOIN 关键词?<br/>客户/产品/品牌/品类"}
    JOIN_CHECK -->|"是"| ADD_JOIN["添加 Join 配置<br/>customer_dim / product_dim"]
    JOIN_CHECK -->|"否"| METRIC_CHECK
    ADD_JOIN --> METRIC_CHECK{"包含指标关键词?"}

    METRIC_CHECK -->|"销售额/业绩"| M1["sum(order_amount)<br/>alias=sales_amount"]
    METRIC_CHECK -->|"GMV/交易额"| M2["sum(order_amount)<br/>alias=gmv"]
    METRIC_CHECK -->|"订单量"| M3["count(id)<br/>alias=order_count"]
    METRIC_CHECK -->|"客单价"| M4["avg(pay_amount)<br/>alias=avg_order_value"]
    METRIC_CHECK -->|"客户数"| M5["count(customer_id)<br/>alias=customer_count"]
    METRIC_CHECK -->|"优惠/折扣"| M6["sum(discount_amount)<br/>alias=total_discount"]
    METRIC_CHECK -->|"无匹配"| M7["默认 sales_amount"]

    M1 & M2 & M3 & M4 & M5 & M6 & M7 --> DIM_CHECK["维度推断<br/>品牌/品类/产品/地区/时间/渠道/客户"]
    DIM_CHECK --> FILTER_CHECK["过滤条件推断<br/>• 地区: 华东/华南/华北/西南<br/>• 渠道: 线上/线下/分销<br/>• 客户类型: 新客/老客/VIP<br/>• 高价值: VIP + pay_amount>=5000"]
    FILTER_CHECK --> ORDER["默认 order_by<br/>desc by 第一个 metric"]
    ORDER --> LIMIT["默认 limit=10<br/>全部→100"]
    LIMIT --> DSL["组装 DSL 对象"]
```

---

## 八、SQL 构建阶段内部流程

```mermaid
flowchart TD
    A["DSL 对象<br/>(语义解析后)"] --> B["恢复 metric 原始字段名<br/>_restore_metric_fields()"]
    B --> C["获取主表<br/>_table_mapping[data_source]"]
    C --> D{"有 joins?"}
    D -->|"是"| E["加载 JOIN 表<br/>设置别名"]
    D -->|"否"| F["仅主表"]
    E --> G["解析 JOIN 条件列<br/>on_field 支持 qualified 名"]
    G --> H["构建 FROM + JOIN 子句"]
    F --> I["构建 SELECT"]
    H --> I
    I --> J["维度列 → 直接引用"]
    I --> K["指标列 → 聚合函数<br/>SUM/AVG/COUNT/MIN/MAX"]
    J & K --> WHERE["构建 WHERE<br/>operator 映射:<br/>=, !=, >, <, >=, <=, in, like"]
    WHERE --> GB{"有 dimensions<br/>+ metrics?"}
    GB -->|"是"| GROUP["GROUP BY 维度列"]
    GB -->|"否"| OB["ORDER BY"]
    GROUP --> OB
    OB --> LIM["LIMIT / OFFSET"]
    LIM --> COMPILE["compile()<br/>literal_binds=True"]
    COMPILE --> SQL["SQL 字符串"]
```

---

## 九、辅助接口流程

### 9.1 `POST /api/v1/query` — 自然语言查询

```mermaid
flowchart LR
    A["用户问题"] --> B["构建 QueryState"] --> C["graph.ainvoke()"]
    C --> D["提取结果<br/>构建 QueryResponse"] --> E["返回结果"]
```

### 9.2 `POST /api/v1/query/dsl` — 仅生成 DSL

```mermaid
flowchart LR
    A["用户问题"] --> B["构建 QueryState"] --> C["graph.ainvoke()"]
    C --> D["提取 dsl 字段"] --> E["返回 DSL"]
```

### 9.3 `POST /api/v1/query/execute` — 直接执行 DSL

```mermaid
flowchart LR
    A["用户传入 DSL"] --> B["构建 QueryState<br/>dsl=用户输入"] --> C["graph.ainvoke()"]
    C --> D["返回结果"]
```

### 9.4 `POST /api/v1/query/stream` — 流式查询

```mermaid
flowchart LR
    A["用户问题"] --> B["构建 QueryState"] --> C["graph.astream()"]
    C --> D["SSE 流式输出<br/>每个节点结果"] --> E["data: [DONE]"]
```

### 9.5 `POST /api/v1/query/resume` — 恢复中断流程

```mermaid
flowchart LR
    A["query_id + action"] --> B["graph.ainvoke(None, config)<br/>或 graph.ainvoke({'status': 'rejected'}, config)"]
    B --> C["返回结果"]
```

---

## 十、审计 Trace 结构

每条查询的 `trace` 数组由各节点通过 `Annotated[list[dict], add_to_list]` reducer 自动累积：

```json
[
  {
    "step": "clarification",
    "status": "success",
    "items_count": 0
  },
  {
    "step": "mock_dsl",
    "status": "success",
    "source": "mock"
  },
  {
    "step": "validate_dsl",
    "status": "success"
  },
  {
    "step": "inject_row_permission",
    "status": "success"
  },
  {
    "step": "check_col_permission",
    "status": "success"
  },
  {
    "step": "resolve_semantic",
    "status": "success"
  },
  {
    "step": "build_sql",
    "status": "success"
  },
  {
    "step": "scan_sql",
    "status": "success"
  },
  {
    "step": "sandbox_check",
    "status": "success",
    "risks": []
  },
  {
    "step": "execute_sql",
    "status": "success",
    "rows_returned": 10
  }
]
```

---

## 十一、数据流图

```mermaid
flowchart LR
    subgraph INPUT["输入层"]
        Q["自然语言问题"]
        UID["user_id"]
        TID["tenant_id"]
    end

    subgraph GRAPH["LangGraph 层"]
        STATE["QueryState<br/>TypedDict"]
    end

    subgraph SEMANTIC["语义层"]
        REG["SemanticRegistry<br/>metrics.yaml"]
        PERM["permissions.yaml"]
    end

    subgraph SQL_LAYER["SQL 层"]
        SQL["SQL 字符串"]
    end

    subgraph DATA["数据层"]
        DB[(SQLite/MySQL/...)]
        AUDIT[(审计日志表<br/>nl2dsl_audit_log)]
    end

    Q --> STATE
    UID --> PERM
    TID --> PERM
    REG --> STATE
    STATE --> SQL
    PERM --> SQL
    SQL --> DB
    SQL --> AUDIT
    DB --> RESULT["查询结果"]
    AUDIT --> LOG["审计记录"]
```

---

## 十二、关键设计决策

1. **LangGraph StateGraph**: 用 StateGraph 建模查询管道，获得条件分支、检查点、流式输出、子图封装、LangSmith 追踪等原生能力。

2. **LLM 只生成 DSL 不生成 SQL**：DSL 是结构化 JSON，可校验、可修正、可做权限控制；SQL 是自由文本，出错后难以定位。

3. **LLM 路径与 Mock 路径独立**：LLM 未配置时使用 Mock（开发环境），LLM 配置正常时只走 LLM。LLM 调用失败时不给出低质量 Mock 结果，而是明确报错。

4. **验证子图内循环修正**：DSL 验证失败时，correct_dsl_node 将错误信息反馈给 LLM 重新生成，最多重试 3 次。

5. **歧义检测前置（Clarification）**：在 DSL 生成前检测用户问题的歧义（时间缺失、指标/维度歧义），返回澄清问题而非猜测，降低错误生成概率。

6. **Sandbox 预执行检查**：在正式执行 SQL 前运行 EXPLAIN + LIMIT 预览，检测全表扫描、执行超时、缺少 WHERE 等风险，拦截危险查询。

7. **语义层隔离业务与物理模型**：指标/维度通过 YAML 注册，LLM 只使用语义名，SQL 构建阶段再展开为物理列。

8. **SQL 安全扫描白名单模式**：禁止一切非 SELECT 操作（DML/DDL/注释/UNION/多语句）。

9. **行级权限自动注入**：在 DSL 编译为 SQL 之前注入过滤条件，确保用户只能看到授权数据。

10. **统一错误处理**: `@with_error_handler` 装饰器捕获所有节点异常，转换为标准错误状态（status=error, error_code, trace）。

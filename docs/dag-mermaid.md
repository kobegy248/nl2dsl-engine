# NL2DSL Query Pipeline DAG

```mermaid
flowchart TD
    subgraph MainPipeline["主链路"]
        direction TB
        START([START]) --> clarification
        clarification -->|需要澄清| END1([END])
        clarification -->|继续| decompose
        decompose --> validation
        validation --> permission_check
        permission_check --> resolve_semantic
        resolve_semantic --> build_sql
        build_sql -->|错误| END2([END])
        build_sql -->|简单/复杂| scan_sql
        scan_sql --> sandbox_check
        sandbox_check -->|需审核| human_review
        sandbox_check -->|通过| execute_sql
        human_review -->|通过| execute_sql
        human_review -->|拒绝/错误| END3([END])
        execute_sql -->|重试| simplify_dsl
        execute_sql -->|成功| verify_dsl
        simplify_dsl --> build_sql
        verify_dsl --> END4([END])
    end

    subgraph ValidationSubgraph["验证子图"]
        direction TB
        ENTRY1([入口]) -->|LLM可用| gen_dsl[generate_dsl]
        ENTRY1 -->|无LLM| mock_dsl[mock_dsl]
        gen_dsl -->|错误| mock_dsl
        gen_dsl -->|成功| validate_dsl
        mock_dsl --> validate_dsl
        validate_dsl -->|通过| END5([END])
        validate_dsl -->|失败| correct_dsl
        validate_dsl -->|错误| END6([END])
        correct_dsl --> validate_dsl
    end

    subgraph PermissionSubgraph["权限子图"]
        direction TB
        ENTRY2([入口]) --> inject_row[inject_row_permission]
        inject_row -->|错误| END7([END])
        inject_row -->|成功| check_col[check_col_permission]
        check_col --> END8([END])
    end

    validation -.->|包含| ValidationSubgraph
    permission_check -.->|包含| PermissionSubgraph

    classDef agentic fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef endpoint fill:#ffebee,stroke:#b71c1c
    classDef loop fill:#fff3e0,stroke:#e65100

    class decompose,verify_dsl,correct_dsl agentic
    class END1,END2,END3,END4,END5,END6,END7,END8 endpoint
    class correct_dsl,simplify_dsl loop
```

## 节点说明

| 节点 | 职责 | Agentic |
|------|------|---------|
| `clarification` | 检测歧义，需澄清时结束 | 否 |
| `decompose` | 复杂查询改写（对比/同比/趋势） | **是** |
| `validation` | DSL 生成+校验+修正子图 | 部分 |
| `permission_check` | 行级过滤+列级权限 | 否 |
| `resolve_semantic` | 语义解析 | 否 |
| `build_sql` | DSL→SQL | 否 |
| `scan_sql` | SQL 安全扫描 | 否 |
| `sandbox_check` | 沙箱检查 | 否 |
| `human_review` | 人工审核 | 否 |
| `execute_sql` | 正式执行 | 否 |
| `simplify_dsl` | 失败简化重试 | 否 |
| `verify_dsl` | LLM 自检结果 | **是** |

### Validation Subgraph

| 节点 | 职责 | Agentic |
|------|------|---------|
| `generate_dsl` | LLM 生成 DSL（带 RAG） | RAG |
| `mock_dsl` | 兜底生成 | 否 |
| `validate_dsl` | 结构校验 | 否 |
| `correct_dsl` | LLM 决策检索词→定向 RAG→重生成 | **是** |

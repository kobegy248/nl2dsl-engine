#!/usr/bin/env python3
"""Generate DAG visualization for the NL2DSL query pipeline."""

from __future__ import annotations

import os
import subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, "docs")
os.makedirs(DOCS, exist_ok=True)

# ---------------------------------------------------------------------------
# Mermaid
# ---------------------------------------------------------------------------
MERMAID = """# NL2DSL Query Pipeline DAG

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
"""

# ---------------------------------------------------------------------------
# DOT
# ---------------------------------------------------------------------------
DOT = """digraph NL2DSL {
    rankdir=TB;
    node [shape=box, style="rounded,filled", fillcolor="#e8eaf6", fontname="Microsoft YaHei"];
    edge [fontname="Microsoft YaHei", fontsize=10];

    START [label="START", shape=circle, fillcolor="#c8e6c9"];
    END [label="END", shape=doublecircle, fillcolor="#ffcdd2"];

    clarification [label="clarification\n歧义检测"];
    decompose [label="decompose\n复杂查询改写", fillcolor="#e1f5fe", style="rounded,filled,bold"];
    validation [label="validation\nDSL生成校验子图", fillcolor="#f5f5f5", style="rounded,filled,dashed"];
    permission [label="permission_check\n权限子图", fillcolor="#f5f5f5", style="rounded,filled,dashed"];
    resolve [label="resolve_semantic\n语义解析"];
    build_sql [label="build_sql\nDSL→SQL"];
    scan_sql [label="scan_sql\nSQL扫描"];
    sandbox [label="sandbox_check\n沙箱检查"];
    human_review [label="human_review\n人工审核"];
    execute [label="execute_sql\n执行SQL"];
    simplify [label="simplify_dsl\n简化重试", fillcolor="#fff3e0"];
    verify [label="verify_dsl\n结果自检", fillcolor="#e1f5fe", style="rounded,filled,bold"];

    START -> clarification;
    clarification -> END [label="需澄清", color="#d32f2f", fontcolor="#d32f2f"];
    clarification -> decompose [label="继续"];
    decompose -> validation;
    validation -> permission;
    permission -> resolve;
    resolve -> build_sql;
    build_sql -> END [label="错误", color="#d32f2f", fontcolor="#d32f2f"];
    build_sql -> scan_sql [label="简单/复杂"];
    scan_sql -> sandbox;
    sandbox -> human_review [label="需审核", color="#f57c00", fontcolor="#f57c00"];
    sandbox -> execute [label="通过", color="#388e3c", fontcolor="#388e3c"];
    human_review -> execute [label="通过", color="#388e3c", fontcolor="#388e3c"];
    human_review -> END [label="拒绝/错误", color="#d32f2f", fontcolor="#d32f2f"];
    execute -> simplify [label="重试", color="#f57c00", fontcolor="#f57c00"];
    execute -> verify [label="成功", color="#388e3c", fontcolor="#388e3c"];
    simplify -> build_sql [color="#e65100", style=dashed];
    verify -> END;

    subgraph cluster_validation {
        label="Validation Subgraph";
        style="rounded,dashed";
        color="#666666";
        bgcolor="#fafafa";

        val_entry [label="入口", shape=point, width=0.15, height=0.15];
        gen_dsl [label="generate_dsl\nLLM生成"];
        mock_dsl [label="mock_dsl\n兜底生成"];
        validate [label="validate_dsl\n结构校验"];
        correct [label="correct_dsl\nAgentic修正", fillcolor="#e1f5fe", style="rounded,filled,bold"];
        val_end [label="END", shape=doublecircle, fillcolor="#ffcdd2"];

        val_entry -> gen_dsl [label="LLM可用"];
        val_entry -> mock_dsl [label="无LLM"];
        gen_dsl -> mock_dsl [label="错误", color="#d32f2f", fontcolor="#d32f2f"];
        gen_dsl -> validate [label="成功"];
        mock_dsl -> validate;
        validate -> val_end [label="通过", color="#388e3c", fontcolor="#388e3c"];
        validate -> correct [label="失败", color="#f57c00", fontcolor="#f57c00"];
        validate -> val_end [label="错误", color="#d32f2f", fontcolor="#d32f2f"];
        correct -> validate [color="#e65100", style=dashed];
    }

    subgraph cluster_permission {
        label="Permission Subgraph";
        style="rounded,dashed";
        color="#666666";
        bgcolor="#fafafa";

        perm_entry [label="入口", shape=point, width=0.15, height=0.15];
        inject [label="inject_row\n行级过滤"];
        check [label="check_col\n列级权限"];
        perm_end [label="END", shape=doublecircle, fillcolor="#ffcdd2"];

        perm_entry -> inject;
        inject -> perm_end [label="错误", color="#d32f2f", fontcolor="#d32f2f"];
        inject -> check [label="成功"];
        check -> perm_end;
    }
}
"""


def main():
    mermaid_path = os.path.join(DOCS, "dag-mermaid.md")
    dot_path = os.path.join(DOCS, "dag.dot")
    png_path = os.path.join(DOCS, "dag.png")

    with open(mermaid_path, "w", encoding="utf-8") as f:
        f.write(MERMAID)
    print(f"[OK] Mermaid -> {mermaid_path}")

    with open(dot_path, "w", encoding="utf-8") as f:
        f.write(DOT)
    print(f"[OK] DOT -> {dot_path}")

    try:
        subprocess.run(["dot", "-Tpng", dot_path, "-o", png_path], check=True, capture_output=True)
        print(f"[OK] PNG -> {png_path}")
    except FileNotFoundError:
        print("[SKIP] graphviz binary not found, skip PNG rendering")
    except subprocess.CalledProcessError as e:
        print(f"[ERR] dot failed: {e.stderr.decode()}")

    print("\nDone. Open dag-mermaid.md in GitHub/VS Code to view the diagram.")


if __name__ == "__main__":
    main()

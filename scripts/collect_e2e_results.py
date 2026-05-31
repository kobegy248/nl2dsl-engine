"""Collect E2E test results and query trace chain information.

This script:
1. Runs all E2E tests via pytest subprocess
2. Executes sample queries and collects trace information
3. Generates a comprehensive report with results and trace chains
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tests.e2e.mock_data import create_mock_database


def run_tests(output_file: str) -> str:
    """Run E2E tests and capture output."""
    print("=" * 70)
    print("Running E2E tests...")
    print("=" * 70)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/e2e/", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    output = result.stdout + "\n" + result.stderr

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"Test output saved to: {output_file}")
    return output


def collect_traces(output_file: str) -> dict:
    """Execute sample queries and collect trace chains."""
    print("\n" + "=" * 70)
    print("Collecting query trace chains...")
    print("=" * 70)

    os.environ["PYTHONIOENCODING"] = "utf-8"

    from fastapi.testclient import TestClient
    from nl2dsl.api_factory import create_app

    engine, *_ = create_mock_database("sqlite:///:memory:")

    fixtures_dir = os.path.join(os.path.dirname(__file__), "tests", "e2e", "fixtures")
    metrics_path = os.path.join(fixtures_dir, "metrics_test.yaml")
    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics_data = yaml.safe_load(f)

    registry_dict = {
        "metrics": metrics_data.get("metrics", {}),
        "dimensions": metrics_data.get("dimensions", {}),
        "data_sources": metrics_data.get("data_sources", {}),
    }

    perm_path = os.path.join(fixtures_dir, "permissions_test.yaml")
    with open(perm_path, "r", encoding="utf-8") as f:
        perm_data = yaml.safe_load(f)

    permissions = perm_data.get("users", {})
    sensitive_columns = perm_data.get("sensitive_columns", {})
    masking_rules = perm_data.get("masking_rules", {})

    app = create_app(
        engine=engine,
        registry_dict=registry_dict,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
    )
    client = TestClient(app)

    queries = [
        {
            "name": "简单查询 - 查询销售额",
            "type": "simple",
            "request": {
                "question": "查询销售额",
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query",
        },
        {
            "name": "复杂查询 - 对比华东和华南的销售额",
            "type": "complex_compare",
            "request": {
                "question": "对比华东和华南的销售额",
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query",
        },
        {
            "name": "趋势查询 - 销售额趋势",
            "type": "complex_trend",
            "request": {
                "question": "销售额趋势",
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query",
        },
        {
            "name": "关联查询 - 销售额和订单量的关系",
            "type": "complex_correlation",
            "request": {
                "question": "销售额和订单量的关系",
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query",
        },
        {
            "name": "DSL生成 - 查询华东地区的销售额",
            "type": "dsl_generate",
            "request": {
                "question": "查询华东地区的销售额",
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query/dsl",
        },
        {
            "name": "DSL执行 - 按品牌汇总销售额",
            "type": "dsl_execute",
            "request": {
                "dsl": {
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                    ],
                    "dimensions": ["brand"],
                    "data_source": "orders",
                },
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query/execute",
        },
        {
            "name": "权限测试 - u001(华东/华南)",
            "type": "permission_u001",
            "request": {
                "question": "查询各地区的销售额",
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query",
        },
        {
            "name": "权限测试 - u002(华北/西南)",
            "type": "permission_u002",
            "request": {
                "question": "查询各地区的销售额",
                "user_id": "u002",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query",
        },
        {
            "name": "跨表JOIN - 按客户类型统计销售额",
            "type": "join_customer",
            "request": {
                "dsl": {
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                    ],
                    "dimensions": ["customer_type"],
                    "joins": [
                        {
                            "table": "customer_dim",
                            "on_field": "customer_id",
                            "join_type": "left",
                            "alias": "c",
                        },
                    ],
                    "data_source": "orders",
                },
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query/execute",
        },
        {
            "name": "多维度分组 - 地区和品类",
            "type": "multi_dimension",
            "request": {
                "dsl": {
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                    ],
                    "dimensions": ["region", "category"],
                    "data_source": "orders",
                },
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query/execute",
        },
        {
            "name": "多指标 - 销售额和订单量",
            "type": "multi_metric",
            "request": {
                "dsl": {
                    "metrics": [
                        {"func": "sum", "field": "pay_amount", "alias": "sales_amount"},
                        {"func": "count", "field": "id", "alias": "order_count"},
                    ],
                    "dimensions": ["category"],
                    "data_source": "orders",
                },
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query/execute",
        },
        {
            "name": "库存查询 - 按仓库类型统计",
            "type": "inventory",
            "request": {
                "dsl": {
                    "metrics": [
                        {
                            "func": "sum",
                            "field": "stock_quantity",
                            "alias": "total_stock",
                        },
                    ],
                    "dimensions": ["warehouse_type"],
                    "data_source": "inventory",
                },
                "user_id": "u001",
                "tenant_id": "t001",
            },
            "endpoint": "/api/v1/query/execute",
        },
    ]

    results = {
        "collected_at": datetime.now().isoformat(),
        "total_queries": len(queries),
        "queries": [],
    }

    for q in queries:
        print(f"\n  ▶ {q['name']}")
        try:
            response = client.post(q["endpoint"], json=q["request"])
            data = response.json()

            result = {
                "name": q["name"],
                "type": q["type"],
                "endpoint": q["endpoint"],
                "status_code": response.status_code,
                "response_status": data.get("status"),
                "dsl": data.get("dsl"),
                "sql": data.get("sql"),
                "data_preview": data.get("data", [])[:3] if data.get("data") else None,
                "data_row_count": len(data.get("data", [])),
                "execution_time_ms": data.get("execution_time_ms"),
                "explanation": data.get("explanation"),
                "confidence": data.get("confidence"),
                "error": data.get("error"),
                "error_code": data.get("error_code"),
            }
            results["queries"].append(result)

            status_icon = "✅" if response.status_code == 200 and data.get("status") == "success" else "⚠️"
            print(f"    {status_icon} HTTP {response.status_code}, status={data.get('status')}")
            if data.get("sql"):
                sql_preview = data["sql"][:120] + "..." if len(data["sql"]) > 120 else data["sql"]
                print(f"    SQL: {sql_preview}")
            if data.get("data") is not None:
                print(f"    Rows: {len(data['data'])}")
            if data.get("explanation"):
                exp = data["explanation"][:80] + "..." if len(data["explanation"]) > 80 else data["explanation"]
                print(f"    Explanation: {exp}")

        except Exception as e:
            results["queries"].append({
                "name": q["name"],
                "type": q["type"],
                "endpoint": q["endpoint"],
                "error": str(e),
            })
            print(f"    ❌ Error: {e}")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nTrace results saved to: {output_file}")
    return results


def collect_sse_events(output_file: str) -> dict:
    """Collect SSE streaming events from complex queries."""
    print("\n" + "=" * 70)
    print("Collecting SSE streaming events...")
    print("=" * 70)

    os.environ["PYTHONIOENCODING"] = "utf-8"

    from fastapi.testclient import TestClient
    from nl2dsl.api_factory import create_app

    engine, *_ = create_mock_database("sqlite:///:memory:")

    fixtures_dir = os.path.join(os.path.dirname(__file__), "tests", "e2e", "fixtures")
    metrics_path = os.path.join(fixtures_dir, "metrics_test.yaml")
    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics_data = yaml.safe_load(f)

    registry_dict = {
        "metrics": metrics_data.get("metrics", {}),
        "dimensions": metrics_data.get("dimensions", {}),
        "data_sources": metrics_data.get("data_sources", {}),
    }

    perm_path = os.path.join(fixtures_dir, "permissions_test.yaml")
    with open(perm_path, "r", encoding="utf-8") as f:
        perm_data = yaml.safe_load(f)

    permissions = perm_data.get("users", {})
    sensitive_columns = perm_data.get("sensitive_columns", {})
    masking_rules = perm_data.get("masking_rules", {})

    app = create_app(
        engine=engine,
        registry_dict=registry_dict,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
    )
    client = TestClient(app)

    sse_queries = [
        {
            "name": "简单查询流",
            "question": "查询销售额",
            "type": "simple",
        },
        {
            "name": "对比查询流",
            "question": "对比华东和华南的销售额",
            "type": "compare",
        },
        {
            "name": "趋势查询流",
            "question": "销售额趋势",
            "type": "trend",
        },
        {
            "name": "关联查询流",
            "question": "销售额和订单量的关系",
            "type": "correlation",
        },
    ]

    results = {"collected_at": datetime.now().isoformat(), "streams": []}

    for q in sse_queries:
        print(f"\n  ▶ {q['name']}")
        try:
            response = client.post("/api/v1/query/stream", json={
                "question": q["question"],
                "user_id": "u001",
                "tenant_id": "t001",
            })

            events = []
            blocks = response.text.strip().split("\n\n")
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                event_type = None
                data_str = None
                for line in block.split("\n"):
                    line = line.strip()
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data_str = line[len("data:"):].strip()
                if not data_str or data_str == "{}":
                    continue
                try:
                    payload = json.loads(data_str)
                    events.append({
                        "event_type": event_type,
                        "payload": payload,
                    })
                except json.JSONDecodeError:
                    pass

            event_types = [e["event_type"] for e in events if e["event_type"]]
            print(f"    Events: {event_types}")

            results["streams"].append({
                "name": q["name"],
                "question": q["question"],
                "type": q["type"],
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "event_count": len(events),
                "event_types": event_types,
                "events": events,
            })

        except Exception as e:
            results["streams"].append({
                "name": q["name"],
                "question": q["question"],
                "type": q["type"],
                "error": str(e),
            })
            print(f"    ❌ Error: {e}")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nSSE results saved to: {output_file}")
    return results


def generate_report(
    test_output: str,
    trace_results: dict,
    sse_results: dict,
    output_file: str,
):
    """Generate a comprehensive Markdown report."""

    # Parse test summary
    passed = test_output.count(" PASSED ")
    failed = test_output.count(" FAILED ")
    error = test_output.count(" ERROR ")
    skipped = test_output.count(" SKIPPED ")
    xfailed = test_output.count(" XFAIL ")

    lines = test_output.split("\n")
    summary_line = ""
    for line in lines:
        if "passed" in line.lower() and ("failed" in line.lower() or "error" in line.lower()):
            summary_line = line.strip()
            break

    report = f"""# NL2DSL E2E 端到端测试报告

> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 1. 测试汇总

| 指标 | 数值 |
|------|------|
| 总测试数 | {passed + failed + error + skipped + xfailed} |
| 通过 | {passed} |
| 失败 | {failed} |
| 错误 | {error} |
| 跳过 | {skipped} |
| XFAIL | {xfailed} |

{summary_line}

---

## 2. 失败测试详情

"""

    # Extract failures
    in_failure = False
    failure_name = ""
    failure_details = []
    failures = []

    for line in lines:
        if line.startswith("___") and "___" in line:
            if failure_name and failure_details:
                failures.append((failure_name, failure_details))
            failure_name = line.strip("_\n")
            failure_details = []
            in_failure = True
        elif line.startswith("=" * 20) and "FAILURES" in line:
            in_failure = True
        elif line.startswith("=" * 20) and "ERRORS" in line:
            in_failure = True
        elif line.startswith("================= test session"):
            if failure_name and failure_details:
                failures.append((failure_name, failure_details))
            in_failure = False
        elif in_failure and failure_name and not line.startswith("___"):
            failure_details.append(line)

    if failures:
        for name, details in failures:
            report += f"### {name}\n\n"
            report += "```\n"
            report += "\n".join(details[:30])
            report += "\n```\n\n"
    else:
        report += "🎉 所有测试通过，无失败项！\n\n"

    report += """---

## 3. 查询链路（Trace）分析

"""

    for q in trace_results.get("queries", []):
        report += f"### {q['name']}\n\n"
        report += f"- **类型**: {q['type']}\n"
        report += f"- **端点**: {q['endpoint']}\n"
        report += f"- **HTTP状态**: {q['status_code']}\n"
        report += f"- **响应状态**: {q['response_status']}\n"
        report += f"- **执行时间**: {q.get('execution_time_ms', 'N/A')} ms\n"

        if q.get("dsl"):
            dsl_json = json.dumps(q["dsl"], ensure_ascii=False, indent=2)
            report += f"\n**DSL**:\n```json\n{dsl_json}\n```\n"

        if q.get("sql"):
            report += f"\n**SQL**:\n```sql\n{q['sql']}\n```\n"

        if q.get("data_preview") is not None:
            preview = json.dumps(q["data_preview"], ensure_ascii=False, indent=2)
            report += f"\n**数据预览** (共 {q['data_row_count']} 行):\n```json\n{preview}\n```\n"

        if q.get("explanation"):
            report += f"\n**解释**: {q['explanation']}\n"

        if q.get("confidence") is not None:
            report += f"\n**置信度**: {q['confidence']}\n"

        if q.get("error"):
            report += f"\n**错误**: {q['error']} ({q.get('error_code', 'N/A')})\n"

        report += "\n---\n\n"

    report += """## 4. SSE 流式事件分析

"""

    for stream in sse_results.get("streams", []):
        report += f"### {stream['name']}\n\n"
        report += f"- **问题**: {stream['question']}\n"
        report += f"- **类型**: {stream['type']}\n"
        report += f"- **HTTP状态**: {stream['status_code']}\n"
        report += f"- **Content-Type**: {stream.get('content_type', 'N/A')}\n"
        report += f"- **事件数量**: {stream['event_count']}\n"
        report += f"- **事件类型**: {stream.get('event_types', [])}\n"

        if stream.get("events"):
            report += "\n**事件详情**:\n\n"
            for i, event in enumerate(stream["events"]):
                event_type = event.get("event_type", "unknown")
                payload = json.dumps(event["payload"], ensure_ascii=False, indent=2)
                # Truncate long payloads
                if len(payload) > 500:
                    payload = payload[:500] + "...\n}"
                report += f"#### Event {i+1}: `{event_type}`\n\n```json\n{payload}\n```\n\n"

        report += "---\n\n"

    report += """## 5. 链路节点说明

LangGraph StateGraph 查询链路中的关键节点:

| 节点 | 说明 | trace 状态 |
|------|------|-----------|
| clarification | 歧义检测 | success / skipped |
| decompose | 复杂查询改写 | success / skipped |
| generate_dsl | LLM 生成 DSL | success (llm) / success (mock) |
| mock_dsl | Mock DSL 生成 | success |
| validate_dsl | DSL 校验 | success |
| inject_row_permission | 行级权限注入 | success |
| check_col_permission | 列级权限检查 | success |
| resolve_semantic | 语义解析 | success |
| build_sql | SQL 构建 | success |
| scan_sql | SQL 安全扫描 | success |
| execute_sql | SQL 执行 | success |
| simplify_dsl | DSL 简化(重试) | success |
| verify_dsl | DSL 执行后自检 | skipped / pass / warn / fail |

---

*报告由 collect_e2e_results.py 自动生成*
"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nReport saved to: {output_file}")


def main():
    print("=" * 70)
    print("NL2DSL E2E 测试与链路收集工具")
    print("=" * 70)

    # Step 1: Run tests
    test_output = run_tests("e2e_test_results.txt")

    # Step 2: Collect traces
    trace_results = collect_traces("e2e_trace_results.json")

    # Step 3: Collect SSE events
    sse_results = collect_sse_events("e2e_sse_results.json")

    # Step 4: Generate report
    generate_report(test_output, trace_results, sse_results, "e2e_report.md")

    print("\n" + "=" * 70)
    print("所有任务完成！")
    print("=" * 70)
    print("输出文件:")
    print("  - e2e_test_results.txt  (pytest 原始输出)")
    print("  - e2e_trace_results.json (查询链路 JSON)")
    print("  - e2e_sse_results.json   (SSE 事件 JSON)")
    print("  - e2e_report.md          (综合报告 Markdown)")


if __name__ == "__main__":
    main()

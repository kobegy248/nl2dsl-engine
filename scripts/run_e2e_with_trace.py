"""Run key E2E tests with real LLM and capture detailed trace output.

Usage:
    python run_e2e_with_trace.py > e2e_trace_results.json
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

# Load .env
from pathlib import Path
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value

# Ensure test fixtures are available
import yaml
from tests.e2e.mock_data import create_mock_database

fixtures_dir = Path(__file__).parent / "tests" / "e2e" / "fixtures"
metrics_path = fixtures_dir / "metrics_test.yaml"
with open(metrics_path, "r", encoding="utf-8") as f:
    metrics_data = yaml.safe_load(f)
registry_dict = {
    "metrics": metrics_data.get("metrics", {}),
    "dimensions": metrics_data.get("dimensions", {}),
    "data_sources": metrics_data.get("data_sources", {}),
}

# Load permissions
perm_path = fixtures_dir / "permissions_test.yaml"
with open(perm_path, "r", encoding="utf-8") as f:
    perm_data = yaml.safe_load(f)
permissions = perm_data.get("users", {})
sensitive_columns = perm_data.get("sensitive_columns", {})
masking_rules = perm_data.get("masking_rules", {})

# Create engine
engine, *_ = create_mock_database("sqlite:///:memory:")

# Build app with real LLM
from nl2dsl.api_factory import create_app
from nl2dsl.llm.client import LLMClient
from nl2dsl.config import settings

llm_client = LLMClient(
    api_key=os.environ.get("NL2DSL_LLM_API_KEY", ""),
    base_url=settings.llm_base_url,
    model=settings.llm_model,
)

app = create_app(
    engine=engine,
    registry_dict=registry_dict,
    permissions=permissions,
    sensitive_columns=sensitive_columns,
    masking_rules=masking_rules,
    llm_client=llm_client,
)

from fastapi.testclient import TestClient
client = TestClient(app)

# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

results = []


def run_test(name: str, method: str, url: str, payload: dict | None = None):
    """Run a single API test and capture all details."""
    start = time.time()
    result = {
        "name": name,
        "method": method,
        "url": url,
        "request": payload,
        "status_code": None,
        "response": None,
        "error": None,
        "elapsed_ms": 0,
    }
    try:
        if method == "GET":
            response = client.get(url)
        elif method == "POST":
            response = client.post(url, json=payload)
        else:
            raise ValueError(f"Unsupported method: {method}")

        result["status_code"] = response.status_code
        result["elapsed_ms"] = int((time.time() - start) * 1000)

        try:
            data = response.json()
            result["response"] = data
        except Exception:
            result["response"] = {"raw_text": response.text[:500]}

    except Exception as exc:
        result["error"] = traceback.format_exc()
        result["elapsed_ms"] = int((time.time() - start) * 1000)

    results.append(result)
    # Print progress
    status = "OK" if result["status_code"] == 200 else f"FAIL({result['status_code']})"
    if result["error"]:
        status = "ERROR"
    print(f"  [{status}] {name} ({result['elapsed_ms']}ms)", file=sys.stderr)
    return result


def summarize_dsl(dsl: dict) -> str:
    """Summarize DSL for readable output."""
    if not dsl:
        return "N/A"
    metrics = [m.get("alias", m.get("field", "?")) for m in dsl.get("metrics", [])]
    dims = dsl.get("dimensions", [])
    filters = dsl.get("filters", [])
    limit = dsl.get("limit")
    return f"metrics={metrics}, dims={dims}, filters={len(filters)}, limit={limit}"


# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------

print("=" * 70, file=sys.stderr)
print("E2E Tests with Real LLM + Trace Capture", file=sys.stderr)
print(f"Model: {settings.llm_model}", file=sys.stderr)
print(f"Base URL: {settings.llm_base_url}", file=sys.stderr)
print("=" * 70, file=sys.stderr)

# A. Health check
run_test("health_check", "GET", "/health")

# B. Schema endpoints
run_test("schema_endpoint", "GET", "/api/v1/schema")
run_test("metrics_endpoint", "GET", "/api/v1/metrics")

# C. DSL generation tests (direct LLM test)
print("\n--- DSL Generation (/api/v1/query/dsl) ---", file=sys.stderr)

dsl_questions = [
    ("dsl_simple", "查询销售额"),
    ("dsl_with_region_filter", "查询华东地区的销售额"),
    ("dsl_with_channel_filter", "查询线上渠道的销售额"),
    ("dsl_top_n", "查询销售额排名前5的品牌"),
    ("dsl_chinese_top_n", "查询销售额前五的品牌"),
    ("dsl_multi_dimension", "查询各地区各渠道的销售额"),
    ("dsl_complex_filter", "查询华东地区线上渠道的销售额"),
    ("dsl_customer_type", "查询VIP客户的销售额"),
    ("dsl_gmv", "查询各地区的GMV"),
    ("dsl_order_count", "查询各品类的订单量"),
    ("dsl_avg_order_value", "查询客单价"),
    ("dsl_trend", "销售额趋势"),
    ("dsl_compare", "对比华东和华南的销售额"),
    ("dsl_correlation", "销售额和订单量的关系"),
]

for name, question in dsl_questions:
    run_test(name, "POST", "/api/v1/query/dsl", {
        "question": question,
        "user_id": "u001",
        "tenant_id": "t001",
    })

# D. Full query tests (LLM + validation + permissions + SQL build + execute)
print("\n--- Full Query (/api/v1/query) ---", file=sys.stderr)

query_questions = [
    ("query_simple", "查询销售额"),
    ("query_region_filter", "查询华东地区的销售额"),
    ("query_channel_filter", "查询线上渠道的销售额"),
    ("query_multi_filter", "查询华东地区线上渠道的销售额"),
    ("query_top_n", "查询销售额最高的产品"),
    ("query_brand", "查询各品牌的销售额"),
    ("query_customer_type", "查询各客户类型的销售额"),
    ("query_compare", "对比华东和华南的销售额"),
    ("query_trend", "销售额趋势"),
    ("query_correlation", "销售额和订单量的关系"),
    ("query_proportion", "各品类销售额占比"),
    ("query_ranking", "销售额排名前5的品牌"),
]

for name, question in query_questions:
    run_test(name, "POST", "/api/v1/query", {
        "question": question,
        "user_id": "u001",
        "tenant_id": "t001",
    })

# E. Permission tests
print("\n--- Permission Tests ---", file=sys.stderr)

run_test("permission_u001_east_south", "POST", "/api/v1/query", {
    "question": "查询各地区的销售额",
    "user_id": "u001",
    "tenant_id": "t001",
})

run_test("permission_u002_north_west", "POST", "/api/v1/query", {
    "question": "查询各地区的销售额",
    "user_id": "u002",
    "tenant_id": "t001",
})

# F. Execute endpoint (bypass LLM, direct DSL)
print("\n--- Execute Endpoint (/api/v1/query/execute) ---", file=sys.stderr)

run_test("execute_sales_by_brand", "POST", "/api/v1/query/execute", {
    "dsl": {
        "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
        "dimensions": ["brand"],
        "data_source": "orders",
    },
    "user_id": "u001",
    "tenant_id": "t001",
})

run_test("execute_with_region_filter", "POST", "/api/v1/query/execute", {
    "dsl": {
        "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
        "dimensions": ["brand"],
        "filters": [{"field": "region", "operator": "=", "value": "华东"}],
        "data_source": "orders",
    },
    "user_id": "u001",
    "tenant_id": "t001",
})

run_test("execute_multi_table_join", "POST", "/api/v1/query/execute", {
    "dsl": {
        "metrics": [{"func": "sum", "field": "pay_amount", "alias": "sales_amount"}],
        "dimensions": ["customer_name"],
        "joins": [{"table": "customer_dim", "on_field": "customer_id", "join_type": "left", "alias": "c"}],
        "data_source": "orders",
    },
    "user_id": "u001",
    "tenant_id": "t001",
})

# G. Error cases
print("\n--- Error Cases ---", file=sys.stderr)

run_test("error_invalid_dsl", "POST", "/api/v1/query/execute", {
    "dsl": {"data_source": "nonexistent"},
    "user_id": "u001",
    "tenant_id": "t001",
})

run_test("error_empty_question", "POST", "/api/v1/query", {
    "question": "",
    "user_id": "u001",
    "tenant_id": "t001",
})

# H. SSE streaming
print("\n--- SSE Streaming ---", file=sys.stderr)
run_test("stream_simple", "POST", "/api/v1/query/stream", {
    "question": "查询销售额",
    "user_id": "u001",
    "tenant_id": "t001",
})

run_test("stream_complex", "POST", "/api/v1/query/stream", {
    "question": "对比华东和华南的销售额",
    "user_id": "u001",
    "tenant_id": "t001",
})

# I. Audit log
print("\n--- Audit Log ---", file=sys.stderr)
run_test("audit_list", "GET", "/api/v1/admin/audit/queries?limit=10")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 70, file=sys.stderr)
print("SUMMARY", file=sys.stderr)
print("=" * 70, file=sys.stderr)

total = len(results)
passed = sum(1 for r in results if r["status_code"] == 200)
failed = sum(1 for r in results if r["status_code"] is not None and r["status_code"] != 200)
errors = sum(1 for r in results if r["error"] is not None)

print(f"Total: {total}, Passed: {passed}, Failed: {failed}, Errors: {errors}", file=sys.stderr)

# Print DSL summary for successful DSL generation tests
print("\n--- DSL Generation Summary ---", file=sys.stderr)
for r in results:
    if r["url"] == "/api/v1/query/dsl" and r["status_code"] == 200:
        dsl = r.get("response", {}).get("dsl")
        print(f"  {r['name']}: {summarize_dsl(dsl)}", file=sys.stderr)

# Print SQL summary for successful query tests
print("\n--- Query SQL Summary ---", file=sys.stderr)
for r in results:
    if r["url"] == "/api/v1/query" and r["status_code"] == 200:
        sql = r.get("response", {}).get("sql")
        sql_short = (sql[:100] + "...") if sql and len(sql) > 100 else (sql or "N/A")
        print(f"  {r['name']}: {sql_short}", file=sys.stderr)

# Print failures
if failed > 0 or errors > 0:
    print("\n--- Failures ---", file=sys.stderr)
    for r in results:
        if r["status_code"] is not None and r["status_code"] != 200:
            resp = r.get("response", {})
            err = resp.get("error", resp.get("message", str(resp)[:200]))
            print(f"  FAIL {r['name']} ({r['status_code']}): {err}", file=sys.stderr)
        elif r["error"]:
            print(f"  ERROR {r['name']}: {r['error'][:200]}", file=sys.stderr)

# Output full JSON to stdout
output = {
    "meta": {
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
    },
    "results": results,
}

print(json.dumps(output, ensure_ascii=False, indent=2, default=str))

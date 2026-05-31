"""Parse e2e_summary_v3.log into JSON format matching complex_nl_queries_results.json"""

from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime

log_path = Path("e2e_summary_v3.log")
log_content = log_path.read_text(encoding="utf-16")

# --- Question mappings (from run_e2e_with_trace.py) ---
name_to_question = {
    # DSL Generation
    "dsl_simple": "查询销售额",
    "dsl_with_region_filter": "查询华东地区的销售额",
    "dsl_with_channel_filter": "查询线上渠道的销售额",
    "dsl_top_n": "查询销售额排名前5的品牌",
    "dsl_chinese_top_n": "查询销售额前五的品牌",
    "dsl_multi_dimension": "查询各地区各渠道的销售额",
    "dsl_complex_filter": "查询华东地区线上渠道的销售额",
    "dsl_customer_type": "查询VIP客户的销售额",
    "dsl_gmv": "查询各地区的GMV",
    "dsl_order_count": "查询各品类的订单量",
    "dsl_avg_order_value": "查询客单价",
    "dsl_trend": "销售额趋势",
    "dsl_compare": "对比华东和华南的销售额",
    "dsl_correlation": "销售额和订单量的关系",
    # Full Query
    "query_simple": "查询销售额",
    "query_region_filter": "查询华东地区的销售额",
    "query_channel_filter": "查询线上渠道的销售额",
    "query_multi_filter": "查询华东地区线上渠道的销售额",
    "query_top_n": "查询销售额最高的产品",
    "query_brand": "查询各品牌的销售额",
    "query_customer_type": "查询各客户类型的销售额",
    "query_compare": "对比华东和华南的销售额",
    "query_trend": "销售额趋势",
    "query_correlation": "销售额和订单量的关系",
    "query_proportion": "各品类销售额占比",
    "query_ranking": "销售额排名前5的品牌",
    # Permission tests
    "permission_u001_east_south": "查询各地区的销售额",
    "permission_u002_north_west": "查询各地区的销售额",
    # Execute endpoint
    "execute_sales_by_brand": "按品牌统计销售额",
    "execute_with_region_filter": "按品牌统计销售额（含华东过滤）",
    "execute_multi_table_join": "按客户名称统计销售额（多表JOIN）",
    # Error cases
    "error_invalid_dsl": "[错误用例] 无效DSL",
    "error_empty_question": "[错误用例] 空问题",
    # SSE streaming
    "stream_simple": "查询销售额",
    "stream_complex": "对比华东和华南的销售额",
    # Audit log
    "audit_list": "审计日志查询",
}

# Parse test results from log
# Pattern: [OK] name (time_ms) or [FAIL(code)] name (time_ms)
test_pattern = re.compile(
    r'^\s+\[(OK|FAIL\((\d+)\)|ERROR)\]\s+(\w+)\s+\((\d+)ms\)',
    re.MULTILINE
)

# Parse DSL summaries
# Pattern: dsl_name: metrics=[...], dims=[...], filters=N, limit=N
dsl_pattern = re.compile(
    r'^\s+([\w_]+):\s+metrics=\[(.*?)\],\s+dims=\[(.*?)\],\s+filters=(\d+),\s+limit=(\S+)',
    re.MULTILINE
)

# Parse SQL summaries
# Pattern: query_name: SELECT ...
sql_pattern = re.compile(
    r'^\s+([\w_]+):\s+(SELECT\s+.+?)$',
    re.MULTILINE
)

# Parse failure reasons from "--- Failures ---" section
failure_pattern = re.compile(
    r'^\s+FAIL\s+([\w_]+)\s+\((\d+)\):\s+(.+)$',
    re.MULTILINE
)

# Collect inline NL2DSLException errors that appear before FAIL lines
# These appear in the log as: [node_name] NL2DSLException: ...
inline_error_map = {}  # name -> error message
lines = log_content.split('\n')
for i, line in enumerate(lines):
    line = line.strip()
    fail_match = re.match(r'^\[FAIL\((\d+)\)\]\s+([\w_]+)\s+\((\d+)ms\)', line)
    if fail_match:
        name = fail_match.group(2)
        # Look backward for the most recent error/tracback
        for j in range(i - 1, max(-1, i - 20), -1):
            prev_line = lines[j].rstrip()
            # Match NL2DSLException lines
            err_match = re.search(r'NL2DSLException:\s+(.+)', prev_line)
            if err_match:
                inline_error_map[name] = "NL2DSLException: " + err_match.group(1)
                break
            # Match "Validation failed" lines
            val_match = re.search(r'Validation failed:\s+(.+)', prev_line)
            if val_match:
                inline_error_map[name] = "Validation failed: " + val_match.group(1)
                break
            # Match "Unexpected exception" lines
            ue_match = re.search(r'Unexpected exception:\s*(.+)', prev_line)
            if ue_match:
                # Collect the full exception message (may span multiple lines)
                err_msg = ue_match.group(1)
                for k in range(j + 1, min(len(lines), j + 15)):
                    next_l = lines[k].strip()
                    if not next_l:
                        break
                    err_msg += " " + next_l
                inline_error_map[name] = "Unexpected exception: " + err_msg
                break

# Extract model info
model_match = re.search(r'Model:\s*(.+)', log_content)
base_url_match = re.search(r'Base URL:\s*(.+)', log_content)
model = model_match.group(1).strip() if model_match else "unknown"
base_url = base_url_match.group(1).strip() if base_url_match else "unknown"

# Extract summary counts
summary_match = re.search(r'Total:\s*(\d+),\s*Passed:\s*(\d+),\s*Failed:\s*(\d+),\s*Errors:\s*(\d+)', log_content)
total = int(summary_match.group(1)) if summary_match else 0
passed = int(summary_match.group(2)) if summary_match else 0
failed = int(summary_match.group(3)) if summary_match else 0
errors = int(summary_match.group(4)) if summary_match else 0

# Collect test statuses and execution times
status_map = {}  # name -> {status, status_code, elapsed_ms}
for match in test_pattern.finditer(log_content):
    status_label = match.group(1)
    fail_code = match.group(2)
    name = match.group(3)
    elapsed_ms = int(match.group(4))

    if status_label == "OK":
        status = "success"
        status_code = 200
    elif status_label.startswith("FAIL"):
        status = "failed"
        status_code = int(fail_code) if fail_code else 400
    elif status_label == "ERROR":
        status = "error"
        status_code = 500
    else:
        status = "unknown"
        status_code = 0

    status_map[name] = {
        "response_status": status,
        "status_code": status_code,
        "execution_time_ms": elapsed_ms,
    }

# Collect DSL summaries
dsl_map = {}  # name -> dsl summary dict
for match in dsl_pattern.finditer(log_content):
    name = match.group(1)
    metrics_str = match.group(2)
    dims_str = match.group(3)
    filters_count = int(match.group(4))
    limit_str = match.group(5)

    # Parse metrics list
    metrics = [m.strip().strip("'\"") for m in metrics_str.split(",") if m.strip()]
    # Parse dims list
    dims = [d.strip().strip("'\"") for d in dims_str.split(",") if d.strip()]
    # Parse limit
    try:
        limit = int(limit_str)
    except ValueError:
        limit = None if limit_str == "None" else 10

    dsl_map[name] = {
        "metrics": [{"func": "sum", "field": "SUM(pay_amount)", "alias": m} for m in metrics],
        "dimensions": dims,
        "filters": [{"field": "(various)", "operator": "=", "value": "..."}] * filters_count,
        "limit": limit,
    }

# Collect SQL summaries
sql_map = {}  # name -> sql string
for match in sql_pattern.finditer(log_content):
    name = match.group(1)
    sql = match.group(2).strip()
    if sql.endswith("..."):
        sql = sql[:-3]
    sql_map[name] = sql

# Collect failure reasons
failure_map = {}  # name -> error message
for match in failure_pattern.finditer(log_content):
    name = match.group(1)
    err_msg = match.group(3).strip()
    failure_map[name] = err_msg

# Build results array
results = []
all_test_names = list(name_to_question.keys())

# Also add health check and schema endpoints
endpoint_names = ["health_check", "schema_endpoint", "metrics_endpoint"]
for name in endpoint_names:
    if name in status_map:
        all_test_names.insert(0, name)

# Build question mapping for endpoint tests
name_to_question.update({
    "health_check": "健康检查",
    "schema_endpoint": "获取Schema",
    "metrics_endpoint": "获取指标",
})

for name in all_test_names:
    if name not in status_map:
        continue

    info = status_map[name]
    question = name_to_question.get(name, name)

    entry = {
        "name": name,
        "question": question,
        "status_code": info["status_code"],
        "response_status": info["response_status"],
        "dsl": None,
        "sql": None,
        "data": None,
        "row_count": 0,
        "explanation": None,
        "confidence": None,
        "error": None,
        "error_code": None,
        "execution_time_ms": info["execution_time_ms"],
    }

    # Add DSL if available
    if name in dsl_map:
        entry["dsl"] = dsl_map[name]

    # Add SQL if available
    if name in sql_map:
        entry["sql"] = sql_map[name]

    # Add error if failed
    if info["response_status"] != "success":
        err = failure_map.get(name) or inline_error_map.get(name) or "Unknown error"
        entry["error"] = err
        entry["error_code"] = f"HTTP_{info['status_code']}"

    results.append(entry)

# Build final output
output = {
    "test_time": datetime.now().isoformat(),
    "model": model,
    "base_url": base_url,
    "total": total,
    "passed": passed,
    "failed": failed,
    "errors": errors,
    "results": results,
}

output_path = Path("e2e_summary_v3.json")
output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Generated: {output_path}")
print(f"Total tests: {total}, Passed: {passed}, Failed: {failed}, Errors: {errors}")
print(f"Results written: {len(results)} entries")

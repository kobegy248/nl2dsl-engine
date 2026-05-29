"""Collect e2e test results with SQL, data, and trace for manual review.

Usage:
    cd tests/e2e && python collect_results.py

Output:
    e2e_results.json  - Full results for all /query/execute tests
    e2e_results.txt   - Human-readable summary
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from fastapi.testclient import TestClient
from tests.e2e.mock_data import create_mock_bank_database, create_mock_database
from nl2dsl.api_factory import create_app


def load_ecommerce_config():
    fixtures_dir = Path(__file__).parent / "fixtures"
    with open(fixtures_dir / "metrics_test.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    with open(fixtures_dir / "permissions_test.yaml", "r", encoding="utf-8") as f:
        perm = yaml.safe_load(f)
    registry = {
        "metrics": data.get("metrics", {}),
        "dimensions": data.get("dimensions", {}),
        "data_sources": data.get("data_sources", {}),
    }
    return registry, perm.get("users", {}), perm.get("sensitive_columns", {}), perm.get("masking_rules", {})


def load_bank_config():
    fixtures_dir = Path(__file__).parent / "fixtures"
    with open(fixtures_dir / "bank_metrics_test.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    with open(fixtures_dir / "bank_permissions_test.yaml", "r", encoding="utf-8") as f:
        perm = yaml.safe_load(f)
    registry = {
        "metrics": data.get("metrics", {}),
        "dimensions": data.get("dimensions", {}),
        "data_sources": data.get("data_sources", {}),
    }
    return registry, perm.get("users", {}), perm.get("sensitive_columns", {}), perm.get("masking_rules", {})


def extract_execute_tests(filepath: Path, domain: str) -> list[dict]:
    """Extract all /query/execute test cases from a test file."""
    content = filepath.read_text(encoding="utf-8")
    tests = []

    # Pattern to match a test method with dsl = {...}
    # We look for: def test_xxx(...): """docstring""" dsl = { ... }
    pattern = re.compile(
        r'def\s+(test_\w+)\s*\([^)]*\):\s*'
        r'"""(.*?)"""\s*'
        r'dsl\s*=\s*(\{.*?\})\s*'
        r'response\s*=\s*\w+\.post\s*\(\s*"/api/v1/query/execute"',
        re.DOTALL,
    )

    for match in pattern.finditer(content):
        test_name = match.group(1)
        doc = match.group(2).strip()
        dsl_str = match.group(3)

        # Extract user_id and tenant_id from the post call
        start = match.end()
        next_chunk = content[start : start + 500]
        user_match = re.search(r'"user_id"\s*:\s*"([^"]+)"', next_chunk)
        tenant_match = re.search(r'"tenant_id"\s*:\s*"([^"]+)"', next_chunk)
        user_id = user_match.group(1) if user_match else ""
        tenant_id = tenant_match.group(1) if tenant_match else ""

        # Safely evaluate the DSL dict
        try:
            dsl = eval(dsl_str, {"__builtins__": {}}, {})
        except Exception:
            continue

        tests.append(
            {
                "name": test_name,
                "description": doc,
                "domain": domain,
                "dsl": dsl,
                "user_id": user_id,
                "tenant_id": tenant_id,
            }
        )

    return tests


def extract_nl_tests(filepath: Path, domain: str) -> list[dict]:
    """Extract /query (natural language) test cases."""
    content = filepath.read_text(encoding="utf-8")
    tests = []

    # Pattern for NL queries: question = "..."
    pattern = re.compile(
        r'def\s+(test_\w+)\s*\([^)]*\):\s*'
        r'"""(.*?)"""\s*'
        r'response\s*=\s*\w+\.post\s*\(\s*"/api/v1/query"',
        re.DOTALL,
    )

    for match in pattern.finditer(content):
        test_name = match.group(1)
        doc = match.group(2).strip()

        start = match.end()
        next_chunk = content[start : start + 500]
        q_match = re.search(r'"question"\s*:\s*"([^"]+)"', next_chunk)
        user_match = re.search(r'"user_id"\s*:\s*"([^"]+)"', next_chunk)
        tenant_match = re.search(r'"tenant_id"\s*:\s*"([^"]+)"', next_chunk)

        if not q_match:
            continue

        tests.append(
            {
                "name": test_name,
                "description": doc,
                "domain": domain,
                "question": q_match.group(1),
                "user_id": user_match.group(1) if user_match else "",
                "tenant_id": tenant_match.group(1) if tenant_match else "",
            }
        )

    return tests


def run_all():
    e2e_dir = Path(__file__).parent

    # Collect test definitions
    all_tests = []
    all_tests.extend(extract_execute_tests(e2e_dir / "test_end_to_end.py", "ecommerce"))
    all_tests.extend(extract_execute_tests(e2e_dir / "test_end_to_end_bank.py", "bank"))

    nl_tests = []
    nl_tests.extend(extract_nl_tests(e2e_dir / "test_end_to_end.py", "ecommerce"))
    nl_tests.extend(extract_nl_tests(e2e_dir / "test_end_to_end_bank.py", "bank"))

    # Create apps with correct registry & permissions
    ecommerce_db = create_mock_database()[0]
    eco_reg, eco_perm, eco_sc, eco_mr = load_ecommerce_config()
    ecommerce_app = create_app(
        engine=ecommerce_db,
        registry_dict=eco_reg,
        permissions=eco_perm,
        sensitive_columns=eco_sc,
        masking_rules=eco_mr,
    )

    bank_db = create_mock_bank_database()[0]
    bank_reg, bank_perm, bank_sc, bank_mr = load_bank_config()
    bank_app = create_app(
        engine=bank_db,
        registry_dict=bank_reg,
        permissions=bank_perm,
        sensitive_columns=bank_sc,
        masking_rules=bank_mr,
    )

    results = []

    # Run /query/execute tests
    print(f"Running {len(all_tests)} /query/execute tests...")
    for i, test in enumerate(all_tests, 1):
        app = bank_app if test["domain"] == "bank" else ecommerce_app
        client = TestClient(app)
        resp = client.post(
            "/api/v1/query/execute",
            json={
                "dsl": test["dsl"],
                "user_id": test["user_id"],
                "tenant_id": test["tenant_id"],
            },
        )
        data = resp.json()

        result = {
            "index": i,
            "name": test["name"],
            "description": test["description"],
            "domain": test["domain"],
            "endpoint": "/query/execute",
            "dsl": test["dsl"],
            "user_id": test["user_id"],
            "tenant_id": test["tenant_id"],
            "status": data.get("status") if data else "error",
            "status_code": resp.status_code,
            "sql": data.get("sql") if data else None,
            "data": data.get("data") if data else None,
            "trace": data.get("trace") if data else None,
            "error": data.get("error") if data else None,
            "error_code": data.get("error_code") if data else None,
        }
        results.append(result)
        print(f"  [{i}/{len(all_tests)}] {test['name']}: {result['status']}")

    # Run /query (NL) tests
    print(f"\nRunning {len(nl_tests)} /query (NL) tests...")
    for i, test in enumerate(nl_tests, 1):
        app = bank_app if test["domain"] == "bank" else ecommerce_app
        client = TestClient(app)
        resp = client.post(
            "/api/v1/query",
            json={
                "question": test["question"],
                "user_id": test["user_id"],
                "tenant_id": test["tenant_id"],
            },
        )
        data = resp.json()

        result = {
            "index": len(all_tests) + i,
            "name": test["name"],
            "description": test["description"],
            "domain": test["domain"],
            "endpoint": "/query",
            "question": test["question"],
            "user_id": test["user_id"],
            "tenant_id": test["tenant_id"],
            "status": data.get("status") if data else "error",
            "status_code": resp.status_code,
            "dsl_generated": data.get("dsl") if data else None,
            "sql": data.get("sql") if data else None,
            "data": data.get("data") if data else None,
            "trace": data.get("trace") if data else None,
            "error": data.get("error") if data else None,
            "error_code": data.get("error_code") if data else None,
        }
        results.append(result)
        print(f"  [{i}/{len(nl_tests)}] {test['name']}: {result['status']}")

    # Save JSON
    output_json = e2e_dir / "e2e_results.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nJSON saved: {output_json}")

    # Save human-readable text
    output_txt = e2e_dir / "e2e_results.txt"
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("E2E Test Results Summary\n")
        f.write("=" * 80 + "\n\n")

        success = sum(1 for r in results if r["status"] == "success")
        error = sum(1 for r in results if r["status"] == "error")
        f.write(f"Total: {len(results)} | Success: {success} | Error: {error}\n\n")

        for r in results:
            f.write("-" * 80 + "\n")
            f.write(f"[{r['index']}] {r['name']}\n")
            f.write(f"    Description: {r['description']}\n")
            f.write(f"    Domain: {r['domain']} | Endpoint: {r['endpoint']}\n")
            f.write(f"    User: {r['user_id']} | Tenant: {r['tenant_id']}\n")
            f.write(f"    Status: {r['status']} (HTTP {r['status_code']})\n")

            if r.get("error"):
                f.write(f"    ERROR: {r['error']}\n")

            if r.get("sql"):
                f.write(f"    SQL:\n        {r['sql']}\n")

            if r.get("dsl"):
                f.write(f"    DSL: {json.dumps(r['dsl'], ensure_ascii=False)}\n")

            if r.get("question"):
                f.write(f"    Question: {r['question']}\n")

            if r.get("dsl_generated"):
                f.write(f"    Generated DSL: {json.dumps(r['dsl_generated'], ensure_ascii=False)}\n")

            if r.get("data"):
                rows = r["data"]
                f.write(f"    Data ({len(rows)} rows):\n")
                for j, row in enumerate(rows[:10]):  # limit to 10 rows
                    f.write(f"        Row {j + 1}: {json.dumps(row, ensure_ascii=False)}\n")
                if len(rows) > 10:
                    f.write(f"        ... ({len(rows) - 10} more rows)\n")

            if r.get("trace"):
                f.write(f"    Trace: {json.dumps(r['trace'], ensure_ascii=False)}\n")

            f.write("\n")

    print(f"Text saved: {output_txt}")


if __name__ == "__main__":
    run_all()

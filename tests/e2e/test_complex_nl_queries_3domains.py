"""复杂自然语言查询测试 - 三个独立业务域 (3-Domain E2E Test).

三个完全独立的业务域，各自拥有独立的:
  - 数据库 schema 和 mock 数据
  - 语义层配置 (metrics/dimensions/data_sources)
  - 查询用例

Domain 1: 销售/电商 (E-commerce)
Domain 2: 银行/金融 (Banking)
Domain 3: 供应链/物流 (Supply Chain)
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import yaml

from fastapi.testclient import TestClient
from nl2dsl.api_factory import create_app
from nl2dsl.llm.client import LLMClient
from nl2dsl.config import settings

# Import all three mock database creators
from tests.e2e.mock_data import (
    create_mock_database,
    create_mock_bank_database,
    create_mock_supply_chain_database,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_yaml(filename: str) -> dict:
    """Load a YAML fixture file."""
    with open(os.path.join(FIXTURES_DIR, filename), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_registry_dict(metrics_data: dict) -> dict:
    """Build registry dict from metrics YAML data."""
    return {
        "metrics": metrics_data.get("metrics", {}),
        "dimensions": metrics_data.get("dimensions", {}),
        "data_sources": metrics_data.get("data_sources", {}),
    }


def create_domain_client(
    engine,
    registry_dict: dict,
    permissions: dict,
    sensitive_columns: dict,
    masking_rules: dict,
    llm_client,
) -> TestClient:
    """Create a TestClient for a single domain."""
    app = create_app(
        engine=engine,
        registry_dict=registry_dict,
        permissions=permissions,
        sensitive_columns=sensitive_columns,
        masking_rules=masking_rules,
        llm_client=llm_client,
    )
    return TestClient(app)


def run_query(
    client: TestClient,
    name: str,
    question: str,
    user_id: str = "u001",
    tenant_id: str = "t001",
) -> dict:
    """Run a natural language query and return full response."""
    print(f"\n{'='*70}")
    print(f"  [{name}]")
    print(f"  Q: {question}")
    print(f"{'='*70}")

    response = client.post("/api/v1/query", json={
        "question": question,
        "user_id": user_id,
        "tenant_id": tenant_id,
    })

    data = response.json()
    result = {
        "name": name,
        "question": question,
        "status_code": response.status_code,
        "response_status": data.get("status"),
        "dsl": data.get("dsl"),
        "sql": data.get("sql"),
        "data": data.get("data", []),
        "row_count": len(data.get("data", [])),
        "explanation": data.get("explanation"),
        "confidence": data.get("confidence"),
        "error": data.get("error") or data.get("message"),
        "error_code": data.get("error_code"),
        "execution_time_ms": data.get("execution_time_ms"),
    }

    ok = response.status_code == 200 and data.get("status") == "success"
    icon = "OK" if ok else "FAIL"
    print(f"\n  [{icon}] HTTP {response.status_code} | status={data.get('status')} | time={data.get('execution_time_ms')}ms")

    if data.get("dsl"):
        dsl = data["dsl"]
        print(f"\n  DSL: source={dsl.get('data_source')} metrics={[m.get('alias') for m in dsl.get('metrics', [])]} dims={dsl.get('dimensions')}")
        if dsl.get("filters"):
            print(f"       filters={dsl.get('filters')}")
        if dsl.get("order_by"):
            print(f"       order_by={dsl.get('order_by')}")
        if dsl.get("limit"):
            print(f"       limit={dsl.get('limit')}")

    if data.get("sql"):
        sql_short = data["sql"][:200] + "..." if len(data["sql"]) > 200 else data["sql"]
        print(f"\n  SQL: {sql_short}")

    if data.get("data") is not None:
        print(f"\n  Data: {len(data['data'])} rows")
        for i, row in enumerate(data["data"][:3]):
            print(f"    Row {i+1}: {json.dumps(row, ensure_ascii=False)}")
        if len(data["data"]) > 3:
            print(f"    ... {len(data['data'])} rows total")

    if data.get("error"):
        print(f"\n  Error: {data['error']} ({data.get('error_code')})")

    return result


def run_domain_queries(
    domain_name: str,
    client: TestClient,
    queries: list[dict],
) -> tuple[list[dict], int, int]:
    """Run all queries for a single domain and return (results, passed, failed)."""
    print("\n" + "=" * 70)
    print(f"  【{domain_name}】")
    print("=" * 70)

    results = []
    passed = 0
    failed = 0

    for q in queries:
        result = run_query(client, q["name"], q["question"])
        results.append(result)
        if result["response_status"] == "success" and result["status_code"] == 200:
            passed += 1
        else:
            failed += 1

    return results, passed, failed


def main():
    print("\n" + "=" * 70)
    print("  复杂自然语言查询测试 - 3 个独立业务域")
    print("=" * 70)
    print("\n  Domain 1: 销售/电商 (E-commerce)")
    print("  Domain 2: 银行/金融 (Banking)")
    print("  Domain 3: 供应链/物流 (Supply Chain)")

    # ========================================================================
    # Shared LLM client
    # ========================================================================
    llm_client = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    # ========================================================================
    # Domain 1: E-commerce / Sales
    # ========================================================================
    engine1, *_ = create_mock_database("sqlite:///:memory:")
    metrics1 = load_yaml("metrics_test.yaml")
    registry1 = build_registry_dict(metrics1)
    perm1 = load_yaml("permissions_test.yaml")

    client1 = create_domain_client(
        engine=engine1,
        registry_dict=registry1,
        permissions=perm1.get("users", {}),
        sensitive_columns=perm1.get("sensitive_columns", {}),
        masking_rules=perm1.get("masking_rules", {}),
        llm_client=llm_client,
    )

    queries_domain1 = [
        {
            "name": "E1-多层条件:华东线上金额大于5000的订单",
            "question": "查询华东地区线上渠道金额大于5000的订单销售额",
        },
        {
            "name": "E2-排除条件:非手机品类且金额大于3000",
            "question": "查询非手机品类且金额大于3000的销售额",
        },
        {
            "name": "E3-TOP排名:华东销售额前5的产品",
            "question": "查询华东地区销售额排名前5的产品",
        },
    ]

    results1, passed1, failed1 = run_domain_queries("销售/电商 (E-commerce)", client1, queries_domain1)

    # ========================================================================
    # Domain 2: Banking / Finance
    # ========================================================================
    engine2, *_ = create_mock_bank_database("sqlite:///:memory:")
    metrics2 = load_yaml("bank_metrics_test.yaml")
    registry2 = build_registry_dict(metrics2)
    perm2 = load_yaml("bank_permissions_test.yaml")

    client2 = create_domain_client(
        engine=engine2,
        registry_dict=registry2,
        permissions=perm2.get("users", {}),
        sensitive_columns=perm2.get("sensitive_columns", {}),
        masking_rules=perm2.get("masking_rules", {}),
        llm_client=llm_client,
    )

    queries_domain2 = [
        {
            "name": "B1-多层条件:北京分行账户余额大于10万的客户",
            "question": "查询北京分行账户余额大于10万的客户数量",
        },
        {
            "name": "B2-渠道对比:手机银行 vs 柜面交易金额",
            "question": "对比手机银行和柜面的交易金额",
        },
        {
            "name": "B3-排名:持有金额最多的前5个产品",
            "question": "查询客户持有金额最多的前5个产品",
        },
    ]

    results2, passed2, failed2 = run_domain_queries("银行/金融 (Banking)", client2, queries_domain2)

    # ========================================================================
    # Domain 3: Supply Chain / Logistics
    # ========================================================================
    engine3, *_ = create_mock_supply_chain_database("sqlite:///:memory:")
    metrics3 = load_yaml("supply_chain_metrics_test.yaml")
    registry3 = build_registry_dict(metrics3)
    perm3 = load_yaml("supply_chain_permissions_test.yaml")

    client3 = create_domain_client(
        engine=engine3,
        registry_dict=registry3,
        permissions=perm3.get("users", {}),
        sensitive_columns=perm3.get("sensitive_columns", {}),
        masking_rules=perm3.get("masking_rules", {}),
        llm_client=llm_client,
    )

    queries_domain3 = [
        {
            "name": "S1-多层条件:华东区域电子类物料采购",
            "question": "查询华东区域电子类物料的采购金额",
        },
        {
            "name": "S2-仓库对比:各仓库库存金额对比",
            "question": "对比各仓库的库存金额",
        },
        {
            "name": "S3-排名:准时交付率最高的前5供应商",
            "question": "查询准时交付率最高的前5个供应商",
        },
    ]

    results3, passed3, failed3 = run_domain_queries("供应链/物流 (Supply Chain)", client3, queries_domain3)

    # ========================================================================
    # Flatten results (original format)
    # ========================================================================
    all_results = results1 + results2 + results3
    total_passed = passed1 + passed2 + passed3
    total_failed = failed1 + failed2 + failed3
    total_queries = len(all_results)

    print("\n" + "=" * 70)
    print("  测试总结")
    print("=" * 70)
    print(f"  总查询数: {total_queries}")
    print(f"  成功: {total_passed}")
    print(f"  失败: {total_failed}")
    print(f"  成功率: {total_passed/total_queries*100:.1f}%")
    print("")
    print(f"  销售/电商:   {passed1}/{len(results1)} 通过")
    print(f"  银行/金融:   {passed2}/{len(results2)} 通过")
    print(f"  供应链/物流: {passed3}/{len(results3)} 通过")

    # Flat format matching original JSON structure
    output = {
        "test_time": datetime.now().isoformat(),
        "total": total_queries,
        "passed": total_passed,
        "failed": total_failed,
        "results": all_results,
    }

    output_file = "complex_nl_queries_3domains_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  结果已保存: {output_file}")

    # Print failures
    if total_failed > 0:
        print("\n" + "=" * 70)
        print("  失败查询详情")
        print("=" * 70)
        for r in all_results:
            if r["response_status"] != "success" or r["status_code"] != 200:
                print(f"\n  FAIL {r['name']}")
                print(f"     Q: {r['question']}")
                print(f"     HTTP: {r['status_code']}, status: {r['response_status']}")
                if r.get("error"):
                    print(f"     Error: {r['error']}")


if __name__ == "__main__":
    main()

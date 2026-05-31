"""Debug script: run only bank domain queries with full error tracing."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from nl2dsl.api_factory import create_app
from nl2dsl.llm.client import LLMClient
from nl2dsl.config import settings
from tests.e2e.mock_data import create_mock_bank_database

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "tests", "e2e", "fixtures")


def main():
    print("\n" + "=" * 70)
    print("  Bank Domain Debug - 只跑银行域 3 个查询")
    print("=" * 70)

    engine, *_ = create_mock_bank_database("sqlite:///:memory:")

    with open(os.path.join(FIXTURES_DIR, "bank_metrics_test.yaml"), "r", encoding="utf-8") as f:
        metrics_data = yaml.safe_load(f)
    registry_dict = {
        "metrics": metrics_data.get("metrics", {}),
        "dimensions": metrics_data.get("dimensions", {}),
        "data_sources": metrics_data.get("data_sources", {}),
    }

    with open(os.path.join(FIXTURES_DIR, "bank_permissions_test.yaml"), "r", encoding="utf-8") as f:
        perm_data = yaml.safe_load(f)

    llm_client = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )

    app = create_app(
        engine=engine,
        registry_dict=registry_dict,
        permissions=perm_data.get("users", {}),
        sensitive_columns=perm_data.get("sensitive_columns", {}),
        masking_rules=perm_data.get("masking_rules", {}),
        llm_client=llm_client,
    )
    client = TestClient(app)

    queries = [
        {
            "name": "B1-北京分行账户余额大于10万的客户",
            "question": "查询北京分行账户余额大于10万的客户数量",
        },
        {
            "name": "B2-手机银行vs柜面交易金额",
            "question": "对比手机银行和柜面的交易金额",
        },
        {
            "name": "B3-持有金额最多的前5个产品",
            "question": "查询客户持有金额最多的前5个产品",
        },
    ]

    for q in queries:
        print(f"\n{'='*70}")
        print(f"  [{q['name']}]")
        print(f"  Q: {q['question']}")
        print(f"{'='*70}")

        response = client.post("/api/v1/query", json={
            "question": q["question"],
            "user_id": "b003",  # b003 has no row_filters, full access
            "tenant_id": "t001",
        })

        data = response.json()
        print(f"\n  HTTP {response.status_code} | status={data.get('status')}")
        if data.get("dsl"):
            print(f"\n  DSL: {json.dumps(data['dsl'], ensure_ascii=False, indent=2)[:500]}")
        if data.get("sql"):
            print(f"\n  SQL: {data['sql'][:200]}...")
        if data.get("data"):
            print(f"\n  Data: {len(data['data'])} rows")
        if data.get("error"):
            print(f"\n  Error: {data['error']}")
        if data.get("message"):
            print(f"\n  Message: {data['message']}")
        if data.get("error_code"):
            print(f"  Error Code: {data['error_code']}")

        # Print raw response for debugging
        print(f"\n  --- Raw response keys: {list(data.keys())}")


if __name__ == "__main__":
    main()

"""复杂自然语言查询测试 - 验证系统对复杂语义的理解能力.

这些问题不直接传DSL，而是通过自然语言描述复杂业务需求，
验证系统能否正确解析意图、分解任务、生成正确的DSL和SQL。
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import yaml

from fastapi.testclient import TestClient
from nl2dsl.api_factory import create_app
from tests.e2e.mock_data import create_mock_database


def setup_client():
    """Create test client with mock data and LLM client."""
    engine, *_ = create_mock_database("sqlite:///:memory:")
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")

    with open(os.path.join(fixtures_dir, "metrics_test.yaml"), "r", encoding="utf-8") as f:
        metrics_data = yaml.safe_load(f)
    registry_dict = {
        "metrics": metrics_data.get("metrics", {}),
        "dimensions": metrics_data.get("dimensions", {}),
        "data_sources": metrics_data.get("data_sources", {}),
    }

    with open(os.path.join(fixtures_dir, "permissions_test.yaml"), "r", encoding="utf-8") as f:
        perm_data = yaml.safe_load(f)
    permissions = perm_data.get("users", {})
    sensitive_columns = perm_data.get("sensitive_columns", {})
    masking_rules = perm_data.get("masking_rules", {})

    # Initialize LLM client from environment / .env
    from nl2dsl.llm.client import LLMClient
    from nl2dsl.config import settings
    llm_client = LLMClient(
        api_key=settings.llm_api_key,
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
        enable_clarification=True,
    )
    return TestClient(app)


def run_query(client: TestClient, name: str, question: str, user_id: str = "u001", tenant_id: str = "t001") -> dict:
    """Run a natural language query and return full response."""
    print(f"\n{'='*70}")
    print(f"  【{name}】")
    print(f"  问题: {question}")
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
        "error": data.get("error"),
        "error_code": data.get("error_code"),
        "execution_time_ms": data.get("execution_time_ms"),
    }

    # Print summary
    ok = response.status_code == 200 and data.get("status") == "success"
    icon = "✅" if ok else "❌"
    print(f"\n  {icon} HTTP {response.status_code} | status={data.get('status')} | time={data.get('execution_time_ms')}ms")

    if data.get("dsl"):
        dsl = data["dsl"]
        print(f"\n  📋 DSL:")
        print(f"     data_source: {dsl.get('data_source')}")
        print(f"     metrics: {[m.get('alias') for m in dsl.get('metrics', [])]}")
        print(f"     dimensions: {dsl.get('dimensions')}")
        if dsl.get("filters"):
            print(f"     filters: {dsl.get('filters')}")
        if dsl.get("order_by"):
            print(f"     order_by: {dsl.get('order_by')}")
        if dsl.get("limit"):
            print(f"     limit: {dsl.get('limit')}")

    if data.get("sql"):
        sql_lines = data["sql"].split("\n")
        print(f"\n  🗄️  SQL:")
        for line in sql_lines:
            print(f"     {line}")

    if data.get("data") is not None:
        print(f"\n  📊 数据: {len(data['data'])} 行")
        if data["data"]:
            for i, row in enumerate(data["data"][:3]):
                print(f"     Row {i+1}: {json.dumps(row, ensure_ascii=False)}")
            if len(data["data"]) > 3:
                print(f"     ... 共 {len(data['data'])} 行")

    if data.get("explanation"):
        print(f"\n  💬 Explanation: {data['explanation'][:200]}")

    if data.get("error"):
        print(f"\n  ⚠️  Error: {data['error']} ({data.get('error_code')})")

    return result


def main():
    print("\n" + "🚀" * 35)
    print("  复杂自然语言查询测试 - NL2DSL 语义理解能力验证")
    print("🚀" * 35)

    client = setup_client()
    results = []

    # ========================================================================
    # A. 多层条件组合查询 (Multi-layer filtering)
    # ========================================================================

    queries = [
        # A1. 时间+地区+渠道+金额范围
        {
            "name": "A1-多层条件:华东线上金额大于5000的订单",
            "question": "查询华东地区线上渠道金额大于5000的订单销售额",
        },
        # A2. 排除条件
        {
            "name": "A2-排除条件:非手机品类且金额大于3000",
            "question": "查询非手机品类且金额大于3000的销售额",
        },
        # A3. 模糊匹配+范围
        {
            "name": "A3-模糊+范围:苹果产品且金额在5000到20000之间",
            "question": "查询苹果品牌产品在5000到20000元之间的销售额",
        },

        # ========================================================================
        # B. 复杂对比分析 (Complex comparison)
        # ========================================================================

        # B1. 多维度对比
        {
            "name": "B1-多维度对比:华东线上 vs 华南线下",
            "question": "对比华东地区线上渠道和华南地区线下渠道的销售额",
        },
        # B2. 时间对比
        {
            "name": "B2-时间对比:1月和2月的销售额",
            "question": "对比1月份和2月份的销售额",
        },
        # B3. 多指标对比
        {
            "name": "B3-多指标对比:各品类销售额和订单量",
            "question": "对比各品类的销售额和订单量",
        },

        # ========================================================================
        # C. 排名+过滤组合 (Ranking + Filter)
        # ========================================================================

        # C1. TOP N + 条件
        {
            "name": "C1-TOP条件:华东销售额前5的产品",
            "question": "查询华东地区销售额排名前5的产品",
        },
        # C2. 倒数排名
        {
            "name": "C2-倒数:销售额最低的3个品牌",
            "question": "查询销售额最低的3个品牌",
        },
        # C3. 分组内排名概念
        {
            "name": "C3-分组排名:各品类销售额第一的产品",
            "question": "查询各品类中销售额最高的产品",
        },

        # ========================================================================
        # D. 跨维度/跨表分析 (Cross-dimension analysis)
        # ========================================================================

        # D1. 隐含JOIN - 供应商
        {
            "name": "D1-隐含JOIN:按供应商统计销售额",
            "question": "查询各供应商的销售额",
        },
        # D2. 隐含JOIN - 客户
        {
            "name": "D2-隐含JOIN:按客户名称统计",
            "question": "查询各客户的消费金额",
        },
        # D3. 隐含JOIN - 城市等级
        {
            "name": "D3-隐含JOIN:按城市等级统计",
            "question": "查询各城市等级的销售额",
        },
        # D4. 日期维度
        {
            "name": "D4-日期维度:周末和节假日的销售对比",
            "question": "对比周末和非周末的销售额",
        },

        # ========================================================================
        # E. 复杂聚合请求 (Complex aggregation)
        # ========================================================================

        # E1. 多指标+多维度
        {
            "name": "E1-多指标多维度:各地区各渠道的销售额订单量客单价",
            "question": "查询各地区各渠道的销售额、订单量和客单价",
        },
        # E2. 占比分析
        {
            "name": "E2-占比:各品类销售额占总销售额的比例",
            "question": "查询各品类销售额占总销售额的比例",
        },
        # E3. 平均值对比
        {
            "name": "E3-均值对比:VIP和新客的客单价对比",
            "question": "对比VIP客户和新客户的平均客单价",
        },

        # ========================================================================
        # F. 复杂业务场景 (Business scenarios)
        # ========================================================================

        # F1. 库存分析
        {
            "name": "F1-库存:库存不足30天的产品",
            "question": "查询可售天数不足30天的产品",
        },
        # F2. 库存+销售交叉
        {
            "name": "F2-库存销售交叉:库存高但销量低的产品",
            "question": "查询库存量高但销售额低的产品",
        },
        # F3. 渠道分析
        {
            "name": "F3-渠道:线上渠道各品牌的销售占比",
            "question": "查询线上渠道各品牌的销售占比",
        },

        # ========================================================================
        # G. 边界/棘手问题 (Edge cases)
        # ========================================================================

        # G1. 歧义问题
        {
            "name": "G1-歧义:销售情况",
            "question": "查一下销售情况",
        },
        # G2. 超长问题
        {
            "name": "G2-复杂描述:华东线上VIP客户大额订单",
            "question": "帮我查一下华东地区通过线上渠道购买的VIP客户中，单笔金额超过8000元的订单，按产品品牌分组统计销售额和订单数量，取前10名",
        },
        # G3. 口语化
        {
            "name": "G3-口语化:最近卖得好的东西",
            "question": "最近哪些产品卖得比较好",
        },
    ]

    passed = 0
    failed = 0

    for q in queries:
        result = run_query(client, q["name"], q["question"])
        results.append(result)
        if result["response_status"] == "success" and result["status_code"] == 200:
            passed += 1
        else:
            failed += 1

    # ========================================================================
    # Summary
    # ========================================================================

    print("\n" + "=" * 70)
    print("  测试总结")
    print("=" * 70)
    print(f"  总查询数: {len(queries)}")
    print(f"  ✅ 成功: {passed}")
    print(f"  ❌ 失败: {failed}")
    print(f"  成功率: {passed/len(queries)*100:.1f}%")

    # Save results
    output = {
        "test_time": datetime.now().isoformat(),
        "total": len(queries),
        "passed": passed,
        "failed": failed,
        "results": results,
    }

    with open("complex_nl_queries_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  结果已保存: complex_nl_queries_results.json")

    # Print failed details
    if failed > 0:
        print("\n" + "=" * 70)
        print("  失败查询详情")
        print("=" * 70)
        for r in results:
            if r["response_status"] != "success" or r["status_code"] != 200:
                print(f"\n  ❌ {r['name']}")
                print(f"     问题: {r['question']}")
                print(f"     HTTP: {r['status_code']}, status: {r['response_status']}")
                if r.get("error"):
                    print(f"     错误: {r['error']}")


if __name__ == "__main__":
    main()

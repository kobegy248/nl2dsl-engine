"""测试 RAG 4 集合覆盖度。

每个用例标注期望命中的集合和 DSL 关键字段。
"""

import io
import json
import sys

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests
from dataclasses import dataclass
from typing import Optional

API = "http://localhost:8000/api/v1/query"


@dataclass
class TestCase:
    id: int
    question: str
    expected_metric_alias: str  # 期望的 metric alias
    expected_dimension: str  # 期望的 dimension（主维度）
    expected_filter_field: Optional[str] = None  # 期望的 filter field（若有）
    expected_filter_value: Optional[str] = None
    expected_limit: Optional[int] = None
    purpose: str = ""  # 测试目的


CASES = [
    TestCase(1, "查询华东地区销售额", "sales_amount", "region",
             "region", "华东", purpose="全集合命中基线"),
    TestCase(2, "各品牌的流水", "gmv", "brand",
             purpose="terms 别名映射：流水 -> gmv"),
    TestCase(3, "卖得不错的几款货", "sales_amount", "product_name",
             purpose="纯语义检索，依赖 history"),
    TestCase(4, "各品类的客单价", "avg_order_value", "category",
             purpose="terms 别名：客单价 -> avg_order_value"),
    TestCase(5, "按渠道和品类统计成交总额", "gmv", "channel",
             purpose="多维度 + terms：成交总额 -> gmv"),
    TestCase(6, "VIP客户有多少人", "customer_count", "customer_type",
             "customer_type", "VIP", purpose="复杂过滤+terms 模糊"),
    TestCase(7, "AOV最高的5个地区", "avg_order_value", "region",
             expected_limit=5, purpose="英文缩写 AOV + top-N"),
    TestCase(8, "让利最多的牌子", "total_discount", "brand",
             purpose="非标准词：让利→total_discount, 牌子→brand"),
]


def run_case(c: TestCase) -> dict:
    """执行单个用例并校验。"""
    try:
        r = requests.post(API, json={
            "question": c.question, "user_id": "test", "tenant_id": "default"
        }, timeout=120).json()
    except Exception as e:
        return {"case": c, "error": f"请求失败: {e}"}

    dsl = r.get("dsl") or {}
    metrics = dsl.get("metrics") or []
    dimensions = dsl.get("dimensions") or []
    filters = dsl.get("filters") or []
    limit = dsl.get("limit")
    data = r.get("data") or []

    checks = []
    # 检查 metric alias
    aliases = [m.get("alias") for m in metrics]
    metric_ok = c.expected_metric_alias in aliases
    checks.append(("metric", metric_ok, f"期望={c.expected_metric_alias}, 实际={aliases}"))

    # 检查 dimension
    dim_ok = c.expected_dimension in dimensions
    checks.append(("dimension", dim_ok, f"期望={c.expected_dimension}, 实际={dimensions}"))

    # 检查 filter（如果有）
    if c.expected_filter_field:
        filter_ok = any(
            f.get("field") == c.expected_filter_field
            and str(f.get("value")) == str(c.expected_filter_value)
            for f in filters
        )
        checks.append(("filter", filter_ok,
                       f"期望={c.expected_filter_field}={c.expected_filter_value}, 实际={filters}"))

    # 检查 limit
    if c.expected_limit is not None:
        limit_ok = limit == c.expected_limit
        checks.append(("limit", limit_ok, f"期望={c.expected_limit}, 实际={limit}"))

    return {"case": c, "checks": checks, "rows": len(data), "dsl": dsl, "data": data[:2]}


def main():
    print("=" * 80)
    print("RAG 4 集合覆盖测试")
    print("=" * 80)

    results = []
    for c in CASES:
        print(f"\n[#{c.id}] {c.question}")
        print(f"  目的: {c.purpose}")
        result = run_case(c)
        results.append(result)

        if "error" in result:
            print(f"  ❌ {result['error']}")
            continue

        for name, ok, detail in result["checks"]:
            mark = "✅" if ok else "❌"
            print(f"  {mark} {name}: {detail}")
        print(f"  返回 {result['rows']} 条数据")

    print("\n" + "=" * 80)
    total = sum(len(r.get("checks", [])) for r in results)
    passed = sum(1 for r in results for _, ok, _ in r.get("checks", []) if ok)
    print(f"总计: {passed}/{total} 通过")
    print("=" * 80)


if __name__ == "__main__":
    main()

"""Unit tests for registry-aware entity extraction (AgentOrchestrator._extract_entities)."""

from __future__ import annotations

from nl2dsl.agent.orchestrator import AgentOrchestrator


def _registry() -> dict:
    """A synthetic registry mirroring the ecommerce metrics.yaml."""
    return {
        "metrics": {
            "sales_amount": {"expr": "SUM(order_amount)", "description": "销售额"},
            "order_count": {"expr": "COUNT(id)", "description": "订单数量"},
        },
        "dimensions": {
            "supplier_name": {"column": "supplier_name", "type": "string", "description": "供应商名称"},
            "city_level": {"column": "city_level", "type": "string", "description": "城市等级"},
            "customer_name": {"column": "customer_name", "type": "string", "description": "客户名称"},
            "region": {"column": "region_code", "type": "string", "description": "地区"},
        },
        "data_sources": {},
    }


def test_extract_without_registry_uses_hardcoded_keywords():
    """Without a registry, only hardcoded keywords match (legacy behavior)."""
    e = AgentOrchestrator._extract_entities("按供应商统计销售额")
    assert "销售额" in e.metrics  # hardcoded metric keyword
    # 供应商 is NOT a hardcoded keyword, so no dimension is recognized.
    assert not any("supplier" in d for d in e.dimensions)


def test_extract_with_registry_recognizes_supplier_dimension():
    """With a registry, 供应商→supplier_name is recognized as a dimension."""
    e = AgentOrchestrator._extract_entities("按供应商统计销售额", _registry())
    assert "supplier_name" in e.dimensions
    assert "销售额" in e.metrics


def test_extract_with_registry_recognizes_city_level():
    """城市等级→city_level recognized via the description '城市等级'."""
    e = AgentOrchestrator._extract_entities("按城市等级统计销售额", _registry())
    assert "city_level" in e.dimensions


def test_extract_with_registry_does_not_overmatch_unrelated_dimension():
    """A dimension whose description/id is not in the question is not matched."""
    e = AgentOrchestrator._extract_entities("按供应商统计销售额", _registry())
    # city_level and customer_name should NOT be pulled in.
    assert "city_level" not in e.dimensions
    assert "customer_name" not in e.dimensions


def test_extract_registry_augments_not_replaces_hardcoded():
    """Hardcoded keyword matches still work alongside registry matches."""
    e = AgentOrchestrator._extract_entities("按供应商统计华东销售额", _registry())
    assert "supplier_name" in e.dimensions  # registry match
    assert "华东" in e.dimensions  # hardcoded keyword match
    assert "销售额" in e.metrics


def test_route_routes_registry_dimension_to_simple_plan():
    """End-to-end: a registry-recognized dimension routes to SimpleExecutionPlan
    instead of falling through to ExplorationPlan."""
    import asyncio

    from nl2dsl.agent.controller import AgentController
    from nl2dsl.agent.models import SimpleExecutionPlan
    from nl2dsl.agent.planner import Planner

    controller = AgentController()  # real planner reads intents.yaml
    entities = AgentOrchestrator._extract_entities(
        "按供应商统计销售额", _registry()
    )
    result = asyncio.run(controller.route("按供应商统计销售额", entities))
    assert isinstance(result, SimpleExecutionPlan)
    assert "supplier_name" in result.entities.dimensions

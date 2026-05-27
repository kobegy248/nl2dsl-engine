"""Tests for domain discovery."""
from pathlib import Path

from nl2dsl.engine import Engine


def test_discover_domains_finds_default():
    """Default ecommerce domain is found when metrics.yaml exists."""
    engine = Engine()
    assert "ecommerce" in engine.domains


def test_discover_domains_finds_bank():
    """Bank domain is found when bank_metrics.yaml exists."""
    engine = Engine()
    assert "bank" in engine.domains


def test_get_domain_returns_context():
    """get_domain returns a DomainContext with correct registry."""
    engine = Engine()
    ctx = engine.get_domain("bank")
    assert ctx.domain == "bank"
    assert "total_balance" in ctx.registry_dict["metrics"]


def test_get_domain_fallback_to_default():
    """Unknown domain falls back to ecommerce."""
    engine = Engine()
    ctx = engine.get_domain("nonexistent")
    assert ctx.domain == "ecommerce"

import pytest
from nl2dsl.evaluation.canonical.time_resolver import TimeResolver, CanonicalTimeRange


@pytest.fixture
def resolver():
    return TimeResolver()


def test_resolve_year(resolver):
    result = resolver.resolve("2024年")
    assert result.start == "2024-01-01"
    assert result.end == "2024-12-31"
    assert result.granularity == "year"


def test_resolve_month(resolver):
    result = resolver.resolve("2024年1月")
    assert result.start == "2024-01-01"
    assert result.end == "2024-01-31"
    assert result.granularity == "month"


def test_resolve_range(resolver):
    result = resolver.resolve(["2024-01-01", "2024-12-31"])
    assert result.start == "2024-01-01"
    assert result.end == "2024-12-31"
    assert result.granularity == "day"

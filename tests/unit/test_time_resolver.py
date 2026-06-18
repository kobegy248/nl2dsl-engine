"""Unit tests for the deterministic runtime TimeResolver."""

from datetime import date

from nl2dsl.query.time_resolver import resolve_time


REF = date(2026, 6, 18)  # Thursday


def _rng(q: str, field: str = "order_date"):
    r = resolve_time(q, field, reference_date=REF)
    assert r is not None, f"expected resolution for {q!r}"
    return r


def test_none_returns_none():
    assert resolve_time("", "order_date", reference_date=REF) is None
    assert resolve_time("查询销售额", "order_date", reference_date=REF) is None


def test_vague_returns_none():
    # 近期 / 未来 / 当季 without a number are not resolvable
    assert resolve_time("近期销售额", "order_date", reference_date=REF) is None
    assert resolve_time("未来销售额趋势", "order_date", reference_date=REF) is None


def test_this_month():
    r = _rng("本月销售额")
    assert r.time_range == ("2026-06-01", "2026-06-30")
    assert r.granularity == "month"
    assert r.time_field == "order_date"


def test_dang_month_alias():
    assert _rng("当月销售额").time_range == ("2026-06-01", "2026-06-30")


def test_last_month():
    assert _rng("上月订单量").time_range == ("2026-05-01", "2026-05-31")


def test_last_month_across_year_boundary():
    r = resolve_time("上月销售额", "order_date", reference_date=date(2026, 1, 10))
    assert r.time_range == ("2025-12-01", "2025-12-31")


def test_this_week_monday_anchored():
    r = _rng("本周销售额")
    assert r.time_range == ("2026-06-15", "2026-06-21")
    assert r.granularity == "week"


def test_last_week():
    assert _rng("上周销售额").time_range == ("2026-06-08", "2026-06-14")


def test_recent_n_days_inclusive():
    assert _rng("最近7天销售额").time_range == ("2026-06-12", "2026-06-18")
    assert _rng("最近30天销售额").time_range == ("2026-05-20", "2026-06-18")


def test_recent_n_days_variants():
    assert _rng("近7天销售额").time_range == ("2026-06-12", "2026-06-18")
    assert _rng("过去3天销售额").time_range == ("2026-06-16", "2026-06-18")


def test_today_yesterday():
    assert _rng("今天销售额").time_range == ("2026-06-18", "2026-06-18")
    assert _rng("昨天销售额").time_range == ("2026-06-17", "2026-06-17")


def test_this_year_last_year():
    assert _rng("今年销售额").time_range == ("2026-01-01", "2026-12-31")
    assert _rng("去年销售额").time_range == ("2025-01-01", "2025-12-31")


def test_standalone_month_current_year():
    r = _rng("1月份销售额")
    assert r.time_range == ("2026-01-01", "2026-01-31")
    assert r.granularity == "month"


def test_standalone_month_february_leap():
    r = resolve_time("2月份销售额", "order_date", reference_date=date(2024, 6, 18))
    assert r.time_range == ("2024-02-01", "2024-02-29")  # 2024 is a leap year


def test_standalone_month_february_non_leap():
    r = resolve_time("2月份销售额", "order_date", reference_date=date(2026, 6, 18))
    assert r.time_range == ("2026-02-01", "2026-02-28")


def test_absolute_year():
    r = _rng("2024年销售额")
    assert r.time_range == ("2024-01-01", "2024-12-31")
    assert r.granularity == "year"


def test_absolute_year_month():
    r = _rng("2024年1月销售额")
    assert r.time_range == ("2024-01-01", "2024-01-31")
    assert r.granularity == "month"


def test_absolute_quarter():
    r = _rng("2024年Q1销售额")
    assert r.time_range == ("2024-01-01", "2024-03-31")
    assert r.granularity == "quarter"


def test_absolute_year_month_not_mismatched_as_year():
    # "2024年1月" must resolve to the month, not the whole year
    r = _rng("2024年1月销售额")
    assert r.time_range[1] == "2024-01-31"


def test_source_expr_recorded():
    r = _rng("本月销售额")
    assert r.source_expr == "本月"


def test_reference_date_defaults_to_today():
    # Without pinning, should still resolve (uses date.today()) — just assert non-None
    r = resolve_time("本月销售额", "order_date")
    assert r is not None
    assert r.granularity == "month"

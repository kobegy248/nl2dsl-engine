"""Deterministic natural-language time resolver (runtime query path).

Converts relative and absolute Chinese time expressions in a user question
into a concrete ``(time_field, time_range)`` pair that can be written into
the DSL (``DSL.time_field`` + ``DSL.time_range``).

This is the runtime counterpart of the evaluation-only
``nl2dsl.evaluation.canonical.time_resolver.TimeResolver``: it additionally
handles *relative* expressions (本月 / 上月 / 最近7天 / 今年 / 去年) which the
evaluation resolver does not, and uses ``calendar.monthrange`` for correct
month-end math.

Design notes:
- ``reference_date`` defaults to ``date.today()`` **inside the function body**
  (never at module import), so tests can pin it and module import has no
  side effects.
- Only ``time_field`` + ``time_range`` are produced (the two existing DSL
  fields). ``granularity`` is carried on ``ResolvedTime`` for trace logging
  and forward-compatibility with Week 4 period-over-period work; it is NOT
  stored in the DSL this week.
- Vague terms (近期 / 未来 / 当季 without a number) return ``None`` so the
  optimizer rule F003 can Warn rather than silently guessing.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class ResolvedTime:
    """A resolved time expression ready to write into the DSL."""

    time_field: str
    time_range: tuple[str, str]
    granularity: str  # day | week | month | quarter | year
    source_expr: str  # the matched substring, for trace/audit


# Absolute forms -----------------------------------------------------------
_YEAR_RE = re.compile(r"(\d{4})年")
_YEAR_MONTH_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月")
_YEAR_QUARTER_RE = re.compile(r"(\d{4})年\s*([Qq])([1-4])")

# Relative forms -----------------------------------------------------------
_RECENT_DAYS_RE = re.compile(r"(?:最近|近|过去)\s*(\d+)\s*天")
_STANDALONE_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})月份?")

_RELATIVE_MAP: dict[str, str] = {
    "本月": "this_month",
    "当月": "this_month",
    "上月": "last_month",
    "上个月": "last_month",
    "本周": "this_week",
    "这周": "this_week",
    "上周": "last_week",
    "今天": "today",
    "今日": "today",
    "昨天": "yesterday",
    "今年": "this_year",
    "去年": "last_year",
}


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _month_range(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _week_range(ref: date, offset: int = 0) -> tuple[date, date]:
    """Week (Mon–Sun) containing ``ref`` shifted by ``offset`` weeks."""
    monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def resolve_time(
    question: str,
    time_field: str,
    reference_date: date | None = None,
) -> ResolvedTime | None:
    """Resolve a time expression in ``question`` to a concrete range.

    Args:
        question: The original natural-language question.
        time_field: The semantic time dimension to populate (e.g. "order_date").
        reference_date: "Today" for relative expressions. Defaults to
            ``date.today()`` evaluated inside the body (pinnable for tests).

    Returns:
        ``ResolvedTime`` if a resolvable expression is found, else ``None``.
    """
    if not question or not time_field:
        return None
    if reference_date is None:
        reference_date = date.today()

    # 1. Absolute: 2024年1月  /  2024年Q1  /  2024年
    m = _YEAR_MONTH_RE.search(question)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            start, end = _month_range(year, month)
            return ResolvedTime(
                time_field,
                (_fmt(start), _fmt(end)),
                "month",
                m.group(0),
            )

    m = _YEAR_QUARTER_RE.search(question)
    if m:
        year, q = int(m.group(1)), int(m.group(3))
        m_start = (q - 1) * 3 + 1
        m_end = q * 3
        start = date(year, m_start, 1)
        _, end = _month_range(year, m_end)
        return ResolvedTime(
            time_field,
            (_fmt(start), _fmt(end)),
            "quarter",
            m.group(0),
        )

    m = _YEAR_RE.search(question)
    if m and not _YEAR_MONTH_RE.search(question) and not _YEAR_QUARTER_RE.search(question):
        year = int(m.group(1))
        return ResolvedTime(
            time_field,
            (f"{year}-01-01", f"{year}-12-31"),
            "year",
            m.group(0),
        )

    # 2. Relative keyword forms (本月 / 上月 / 本周 / 上周 / 今天 / 今年 / 去年 …)
    for kw, kind in _RELATIVE_MAP.items():
        idx = question.find(kw)
        if idx < 0:
            continue
        resolved = _resolve_relative(kind, reference_date)
        if resolved is not None:
            rng, granularity = resolved
            return ResolvedTime(time_field, rng, granularity, kw)

    # 3. 最近N天 / 近N天 / 过去N天
    m = _RECENT_DAYS_RE.search(question)
    if m:
        n = int(m.group(1))
        if n > 0:
            end = reference_date
            start = reference_date - timedelta(days=n - 1)
            return ResolvedTime(
                time_field,
                (_fmt(start), _fmt(end)),
                "day",
                m.group(0),
            )

    # 4. Standalone month: 1月份 / 3月  (current year)
    m = _STANDALONE_MONTH_RE.search(question)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            start, end = _month_range(reference_date.year, month)
            return ResolvedTime(
                time_field,
                (_fmt(start), _fmt(end)),
                "month",
                m.group(0),
            )

    return None


def _resolve_relative(kind: str, ref: date) -> tuple[tuple[str, str], str] | None:
    if kind == "this_month":
        start, end = _month_range(ref.year, ref.month)
        return (_fmt(start), _fmt(end)), "month"
    if kind == "last_month":
        y, mo = (ref.year - 1, 12) if ref.month == 1 else (ref.year, ref.month - 1)
        start, end = _month_range(y, mo)
        return (_fmt(start), _fmt(end)), "month"
    if kind == "this_week":
        start, end = _week_range(ref, 0)
        return (_fmt(start), _fmt(end)), "week"
    if kind == "last_week":
        start, end = _week_range(ref, -1)
        return (_fmt(start), _fmt(end)), "week"
    if kind == "today":
        return (_fmt(ref), _fmt(ref)), "day"
    if kind == "yesterday":
        d = ref - timedelta(days=1)
        return (_fmt(d), _fmt(d)), "day"
    if kind == "this_year":
        return (f"{ref.year}-01-01", f"{ref.year}-12-31"), "year"
    if kind == "last_year":
        return (f"{ref.year - 1}-01-01", f"{ref.year - 1}-12-31"), "year"
    return None

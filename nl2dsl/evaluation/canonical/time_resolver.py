"""规范化时间解析器，包含粒度信息。"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CanonicalTimeRange:
    """规范化的时间表示。"""

    start: str
    end: str
    granularity: str  # day | week | month | quarter | year


class TimeResolver:
    """将自然语言时间表达式解析为规范化的时间范围。"""

    _YEAR_RE = re.compile(r"^(\d{4})年$")
    _MONTH_RE = re.compile(r"^(\d{4})年(\d{1,2})月$")
    _QUARTER_RE = re.compile(r"^(\d{4})年([Qq]\d)$")

    def resolve(self, time_expr) -> CanonicalTimeRange | None:
        """将时间表达式解析为规范化的范围。

        参数：
            time_expr: 如 "2024年" 的字符串，或如 ["2024-01-01", "2024-12-31"] 的列表
        """
        if time_expr is None:
            return None

        # 已是范围格式
        if isinstance(time_expr, (list, tuple)) and len(time_expr) == 2:
            return CanonicalTimeRange(
                start=str(time_expr[0]),
                end=str(time_expr[1]),
                granularity="day",
            )

        if not isinstance(time_expr, str):
            return None

        s = time_expr.strip()

        # 年份："2024年"
        m = self._YEAR_RE.match(s)
        if m:
            year = m.group(1)
            return CanonicalTimeRange(f"{year}-01-01", f"{year}-12-31", "year")

        # 月份："2024年1月"
        m = self._MONTH_RE.match(s)
        if m:
            year, month = m.group(1), int(m.group(2))
            # 简易月末计算
            end_day = "31" if month in (1, 3, 5, 7, 8, 10, 12) else "30"
            if month == 2:
                end_day = "29" if int(year) % 4 == 0 else "28"
            return CanonicalTimeRange(
                f"{year}-{month:02d}-01",
                f"{year}-{month:02d}-{end_day}",
                "month",
            )

        # 季度："2024年Q1"
        m = self._QUARTER_RE.match(s)
        if m:
            year, q = m.group(1), int(m.group(2)[1])
            month_start = (q - 1) * 3 + 1
            month_end = q * 3
            end_day = "31" if month_end in (1, 3, 5, 7, 8, 10, 12) else "30"
            return CanonicalTimeRange(
                f"{year}-{month_start:02d}-01",
                f"{year}-{month_end:02d}-{end_day}",
                "quarter",
            )

        # 尝试直接日期解析
        try:
            from datetime import datetime
            dt = datetime.strptime(s, "%Y-%m-%d")
            return CanonicalTimeRange(s, s, "day")
        except ValueError:
            pass

        return None

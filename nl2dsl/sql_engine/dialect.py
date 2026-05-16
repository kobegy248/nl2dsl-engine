from __future__ import annotations

import sqlglot
from nl2dsl.exceptions import ValidationError


class DialectConverter:
    SUPPORTED = {"mysql", "postgres", "postgresql", "clickhouse", "doris", "presto", "spark"}

    def transpile(self, sql: str, target: str) -> str:
        target_lower = target.lower()
        if target_lower == "postgresql":
            target_lower = "postgres"
        if target_lower not in self.SUPPORTED:
            raise ValidationError(f"不支持的方言: {target}")
        try:
            result = sqlglot.transpile(sql, read="sqlite", write=target_lower)
            return result[0] if result else sql
        except Exception as e:
            raise ValidationError(f"方言转换失败: {e}")

    def list_supported(self) -> list[str]:
        return sorted(self.SUPPORTED)

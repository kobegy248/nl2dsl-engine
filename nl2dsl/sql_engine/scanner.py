from __future__ import annotations

import re
from nl2dsl.exceptions import ValidationError


class SQLScanner:
    FORBIDDEN_PATTERNS = [
        (re.compile(r"(?i)\b(DELETE|UPDATE|DROP|INSERT|ALTER|CREATE|TRUNCATE)\b"), "危险操作"),
        (re.compile(r"(?i)/\*.*?\*/"), "块注释"),
        (re.compile(r"(?i)--[^\n]*"), "行注释"),
        (re.compile(r"(?i)\bUNION\b"), "UNION"),
        (re.compile(r"(?i);\s*\w+"), "多语句"),
    ]

    def scan(self, sql: str) -> None:
        for pattern, desc in self.FORBIDDEN_PATTERNS:
            if pattern.search(sql):
                raise ValidationError(f"SQL 安全检查失败: 检测到 {desc}")

import pytest
from nl2dsl.sql_engine.scanner import SQLScanner
from nl2dsl.exceptions import ValidationError


def test_safe_sql():
    scanner = SQLScanner()
    scanner.scan("SELECT product_name, SUM(order_amount) FROM orders GROUP BY product_name")


def test_forbidden_delete():
    scanner = SQLScanner()
    with pytest.raises(ValidationError) as exc:
        scanner.scan("DELETE FROM orders")
    assert "危险操作" in str(exc.value)


def test_forbidden_update():
    scanner = SQLScanner()
    with pytest.raises(ValidationError):
        scanner.scan("UPDATE orders SET x=1")


def test_forbidden_drop():
    scanner = SQLScanner()
    with pytest.raises(ValidationError):
        scanner.scan("DROP TABLE orders")


def test_forbidden_union():
    scanner = SQLScanner()
    with pytest.raises(ValidationError):
        scanner.scan("SELECT * FROM a UNION SELECT * FROM b")


def test_forbidden_comment():
    scanner = SQLScanner()
    with pytest.raises(ValidationError):
        scanner.scan("SELECT 1 -- malicious")


def test_forbidden_block_comment():
    scanner = SQLScanner()
    with pytest.raises(ValidationError):
        scanner.scan("SELECT 1 /* malicious */")


def test_forbidden_multi_statement():
    scanner = SQLScanner()
    with pytest.raises(ValidationError):
        scanner.scan("SELECT 1; DROP TABLE x")

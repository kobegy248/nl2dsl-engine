import pytest
from nl2dsl.sql_engine.dialect import DialectConverter
from nl2dsl.exceptions import ValidationError


@pytest.fixture
def converter():
    return DialectConverter()


def test_transpile_mysql(converter):
    sql = 'SELECT product_name, SUM(order_amount) AS sales_amount FROM order_fact GROUP BY product_name LIMIT 10'
    result = converter.transpile(sql, target="mysql")
    assert "LIMIT" in result


def test_transpile_postgresql(converter):
    sql = 'SELECT product_name, SUM(order_amount) AS sales_amount FROM order_fact GROUP BY product_name LIMIT 10'
    result = converter.transpile(sql, target="postgres")
    assert "LIMIT" in result


def test_transpile_clickhouse(converter):
    sql = 'SELECT product_name, SUM(order_amount) AS sales_amount FROM order_fact GROUP BY product_name LIMIT 10'
    result = converter.transpile(sql, target="clickhouse")
    assert "LIMIT" in result


def test_unsupported_dialect(converter):
    with pytest.raises(ValidationError):
        converter.transpile("SELECT 1", target="unknown_dialect")


def test_list_supported(converter):
    dialects = converter.list_supported()
    assert "mysql" in dialects
    assert "postgres" in dialects
    assert "clickhouse" in dialects
    assert "doris" in dialects

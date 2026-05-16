from nl2dsl.exceptions import (
    NL2DSLException,
    ValidationError,
    PermissionError,
    SemanticError,
)


def test_nl2dsl_exception_base():
    exc = NL2DSLException("base error")
    assert exc.error_code == "INTERNAL_ERROR"
    assert exc.status_code == 500
    assert str(exc) == "base error"


def test_validation_error():
    exc = ValidationError("invalid field")
    assert exc.error_code == "VALIDATION_ERROR"
    assert exc.status_code == 400


def test_permission_error():
    exc = PermissionError("no access")
    assert exc.error_code == "PERMISSION_DENIED"
    assert exc.status_code == 403


def test_semantic_error():
    exc = SemanticError("metric not found")
    assert exc.error_code == "SEMANTIC_ERROR"
    assert exc.status_code == 400

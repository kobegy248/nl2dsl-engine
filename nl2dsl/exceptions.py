class NL2DSLException(Exception):
    error_code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ValidationError(NL2DSLException):
    error_code = "VALIDATION_ERROR"
    status_code = 400


class PermissionError(NL2DSLException):
    error_code = "PERMISSION_DENIED"
    status_code = 403


class SemanticError(NL2DSLException):
    error_code = "SEMANTIC_ERROR"
    status_code = 400


class QueryError(NL2DSLException):
    error_code = "QUERY_ERROR"
    status_code = 400


class LLMError(NL2DSLException):
    error_code = "LLM_ERROR"
    status_code = 502


class NotFoundError(NL2DSLException):
    error_code = "NOT_FOUND"
    status_code = 404

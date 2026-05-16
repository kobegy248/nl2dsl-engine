from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from nl2dsl.config import settings
from nl2dsl.exceptions import NL2DSLException

app = FastAPI(title="NL2DSL", version="0.1.0")


class QueryRequest(BaseModel):
    question: str
    user_id: str
    tenant_id: str
    data_source: str | None = None


class QueryResponse(BaseModel):
    status: str
    data: list[dict] | None = None
    dsl: dict | None = None
    sql: str | None = None
    execution_time_ms: int = 0


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/query/dsl")
async def query_dsl(req: QueryRequest) -> QueryResponse:
    return QueryResponse(status="success", dsl={"data_source": "orders"})


@app.post("/api/v1/query")
async def query(req: QueryRequest) -> QueryResponse:
    return QueryResponse(status="success", data=[])


@app.exception_handler(NL2DSLException)
async def nl2dsl_exception_handler(request, exc: NL2DSLException):
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error_code": exc.error_code, "message": exc.message},
    )

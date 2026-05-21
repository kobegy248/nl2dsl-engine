# NL2DSL LangGraph 重写设计文档

## 背景

当前 NL2DSL 的查询链路是纯 Python 手写顺序调用（`api.py` 中约 200 行核心逻辑），各阶段通过直接函数调用串联，用 `trace` 数组手动记录执行过程。

本设计将整条链路重写为 LangGraph `StateGraph`，同时保留现有 FastAPI API 接口不变。

## 目标

1. 整条查询链路用 LangGraph StateGraph 建模
2. 特定阶段引入 LangChain（RAG Retrieval Chain、PromptTemplate、OutputParser）
3. 保持现有 API 接口不变（外部调用方无感知）
4. 获得 LangGraph 原生能力：条件分支、检查点持久化、人机交互、流式输出、子图、LangSmith 追踪

## 非目标

- 不替换底层服务实现（`SQLBuilder`、`SemanticResolver` 等保持独立类）
- 不改变数据模型（`DSL` Pydantic 模型不变）
- 不迁移 demo/ 目录下的学习代码

## 架构设计

### StateGraph 节点映射

将现有 10 个阶段映射为 LangGraph 节点：

| 现有阶段 | LangGraph 节点 | 说明 |
|---------|---------------|------|
| 歧义检测 | `clarification` | 检测查询歧义，有歧义直接 END |
| DSL 生成 | `generate_dsl` | 包含 LLM / Mock 双路径 |
| DSL 校验 | `validate_dsl` | 校验失败触发修正循环 |
| DSL 修正 | `correct_dsl` | 根据错误反馈重新生成 |
| 行级权限 | `inject_row_permission` | 封装在 permission_check 子图中 |
| 列级权限 | `check_col_permission` | 封装在 permission_check 子图中 |
| 语义解析 | `resolve_semantic` | 指标名展开为 SQL 表达式 |
| SQL 构建 | `build_sql` | SQLAlchemy Core 构建 |
| SQL 扫描 | `scan_sql` | 安全扫描，含简单/复杂双路径 |
| 沙箱检查 | `sandbox_check` | 不通过触发人工审核 |
| 人工审核 | `human_review` | Human-in-the-loop 中断点 |
| SQL 执行 | `execute_sql` | 数据库执行 |
| 执行重试 | `execute_sql_retry` | 失败后简化 DSL 重试 |
| 错误处理 | 统一装饰器 | 所有节点异常捕获 |

### 完整流程图

```
START
  ↓
clarification ──┬──[有歧义]→ END (status=clarification)
                └──[无歧义]→ check_llm
                                  ├──[未配置]→ mock_dsl
                                  └──[可用]→ llm_dsl
                                                  ├──[失败]→ END (error)
                                                  └──[成功]→
                                   ┌─────────────┐
                                   │ 验证子图    │
                                   │ generate    │
                                   │   ↓         │
                                   │ validate ──┬──[失败]→
                                   │   └──[通过]│ correct →
                                   │            └──────────
                                   └─────────────┘
                                         ↓
                                   permission_check 子图
                                   ┌─────────────┐
                                   │ inject_row  │
                                   │   ↓         │
                                   │ check_col   │
                                   └─────────────┘
                                         ↓
resolve_semantic → build_sql → detect_complexity
                      ├──[简单]→ light_scan
                      └──[复杂]→ deep_scan
                                ↓
sandbox_check ──┬──[不通过]→ human_review ──┬──[通过]→ build_sql
                │                           │ (循环)
                └──[通过]───────────────────┘
                             ↓
execute_sql ──┬──[成功]→ END (success)
              └──[失败]→ simplify_dsl → build_sql → scan_sql
                         → execute_sql_retry → END

所有节点: @with_error_handler → [异常]→ END (error)
```

## 状态模型

```python
class QueryState(TypedDict):
    # 输入字段
    question: str
    user_id: str
    tenant_id: str
    data_source: str | None

    # 中间产物
    ambiguities: list[ClarificationItem] | None
    dsl: DSL | None
    dsl_attempts: list[dict]          # 每次生成尝试记录
    sql: str | None
    sandbox_result: SandboxResult | None
    complexity: str                   # "simple" | "complex"

    # 输出字段
    data: list[dict] | None
    status: str                       # "success" | "clarification" | "warning" | "error" | "pending_review"
    error: str | None
    error_code: str | None
    trace: list[dict]

    # 元数据
    query_id: str
    started_at: float
    llm_used: bool
```

## 条件路由设计

### 1. 歧义检测 → 提前结束

```python
def route_after_clarification(state: QueryState) -> str:
    if state.get("ambiguities"):
        return "clarification"
    return "continue"

builder.add_conditional_edges("clarification", route_after_clarification, {
    "clarification": END,
    "continue": "check_llm",
})
```

### 2. LLM / Mock 双路径（独立路径，非 fallback）

```python
def route_llm_availability(state: QueryState) -> str:
    if llm_client is None:
        return "mock"
    return "llm"

builder.add_conditional_edges("check_llm", route_llm_availability, {
    "mock": "mock_dsl",
    "llm": "llm_dsl",
})
```

**关键决策**：LLM 失败（网络错误、格式错误）不 fallback 到 mock，而是重试修正或直接报错。mock 仅在 LLM 未配置时使用（开发/测试环境）。

### 3. DSL 校验失败 → 修正循环

```python
def route_after_validate(state: QueryState) -> str:
    if state.get("status") == "error":
        return "error"
    attempts = state.get("dsl_attempts", [])
    if attempts and not attempts[-1].get("valid"):
        return "retry"
    return "ok"

builder.add_conditional_edges("validate_dsl", route_after_validate, {
    "error": END,
    "retry": "correct_dsl",
    "ok": "permission_check",
})
```

### 4. 查询复杂度 → 不同扫描策略

```python
def detect_complexity(state: QueryState) -> str:
    dsl = state.get("dsl")
    if dsl and (dsl.get("joins") or len(dsl.get("dimensions", [])) > 3):
        return "complex"
    return "simple"

builder.add_conditional_edges("build_sql", detect_complexity, {
    "simple": "light_scan",
    "complex": "deep_scan",
})
```

### 5. 沙箱不通过 → 人工审核

```python
def route_after_sandbox(state: QueryState) -> str:
    result = state.get("sandbox_result")
    if result and not result.passed:
        return "review"
    return "execute"

builder.add_conditional_edges("sandbox_check", route_after_sandbox, {
    "review": "human_review",
    "execute": "execute_sql",
})
```

### 6. 执行失败 → 降级重试

```python
def route_after_execute(state: QueryState) -> str:
    if state.get("status") == "error" and state.get("error_code") == "EXECUTE_TIMEOUT":
        return "retry"
    return "end"

builder.add_conditional_edges("execute_sql", route_after_execute, {
    "retry": "simplify_dsl",
    "end": END,
})
```

## 子图封装

### 权限检查子图

```python
def build_permission_subgraph() -> CompiledStateGraph:
    sub = StateGraph(QueryState)
    sub.add_node("inject_row", inject_row_permission)
    sub.add_node("check_col", check_col_permission)
    sub.add_conditional_edges("inject_row",
        lambda s: "error" if s.get("status") == "error" else "ok",
        {"error": END, "ok": "check_col"}
    )
    sub.set_entry_point("inject_row")
    sub.set_finish_point("check_col")
    return sub.compile()

# 主图使用
builder.add_node("permission_check", build_permission_subgraph())
```

### 验证子图（DSL 生成 + 校验 + 修正）

```python
def build_validation_subgraph() -> CompiledStateGraph:
    sub = StateGraph(QueryState)
    sub.add_node("generate", generate_dsl)
    sub.add_node("validate", validate_dsl)
    sub.add_node("correct", correct_dsl)
    sub.add_conditional_edges("generate",
        lambda s: "mock" if not s.get("llm_used") else "llm_ok" if s.get("dsl") else "llm_fail",
        {"mock": "validate", "llm_ok": "validate", "llm_fail": END}
    )
    sub.add_conditional_edges("validate",
        lambda s: "retry" if s.get("dsl_attempts", [])[-1].get("valid") is False else "ok",
        {"retry": "correct", "ok": END}
    )
    sub.add_edge("correct", "validate")
    sub.set_entry_point("generate")
    return sub.compile()
```

## 检查点持久化

使用 LangGraph 内置 `SqliteSaver`：

```python
from langgraph.checkpoint.sqlite import SqliteSaver

checkpointer = SqliteSaver.from_conn_string("sqlite:///./nl2dsl.db")
graph = builder.compile(checkpointer=checkpointer)
```

### 获得的能力

- **Time Travel**：`graph.get_state_history(config)` 获取完整历史，可回退到任意步骤
- **中断恢复**：在 `human_review` 节点中断后，调用 `graph.invoke(None, config)` 恢复
- **审计增强**：审计日志可直接从检查点读取，无需手动维护 `trace` 数组

## 人机交互（Human-in-the-loop）

### 编译时声明中断点

```python
graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_review"]
)
```

### 恢复 API

```python
@app.post("/api/v1/query/resume")
async def resume_query(query_id: str, action: str) -> QueryResponse:
    config = {"configurable": {"thread_id": query_id}}
    if action == "approve":
        result = await graph.ainvoke(None, config)
    else:
        result = await graph.ainvoke({"status": "rejected"}, config)
    return QueryResponse(...)
```

## 流式输出

### 新增流式查询接口

```python
@app.post("/api/v1/query/stream")
async def query_stream(req: QueryRequest):
    state = QueryState(...)
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    async def event_generator():
        async for chunk in graph.astream(state, config, stream_mode="updates"):
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 流式格式

```json
data: {"clarification": {"ambiguities": null}}
data: {"generate_dsl": {"dsl": {...}, "llm_used": true}}
data: {"validate_dsl": {}}
data: {"inject_row_permission": {"dsl": {...}}}
data: {"build_sql": {"sql": "SELECT ..."}}
data: {"execute_sql": {"data": [...], "rows_returned": 10}}
data: [DONE]
```

## API 适配层（保持接口不变）

### 现有接口内部适配

```python
@app.post("/api/v1/query")
async def query(req: QueryRequest) -> QueryResponse:
    query_id = str(uuid.uuid4())
    state = QueryState(query_id=query_id, ...)
    config = {"configurable": {"thread_id": query_id}}

    result = await graph.ainvoke(state, config)

    # 检查是否在中断点暂停
    if result.get("status") == "pending_review":
        return QueryResponse(
            status="pending_review",
            clarification={"message": "查询存在安全风险，等待人工审核", "query_id": query_id},
        )

    return QueryResponse(
        status=result["status"],
        data=result.get("data"),
        dsl=result.get("dsl"),
        sql=result.get("sql"),
        execution_time_ms=int((time.time() - result["started_at"]) * 1000),
    )
```

### 接口汇总

| 接口 | 状态 | 说明 |
|------|------|------|
| `POST /api/v1/query` | **保留** | 内部实现换 LangGraph |
| `POST /api/v1/query/dsl` | **保留** | 内部实现换 LangGraph |
| `POST /api/v1/query/execute` | **保留** | 内部实现换 LangGraph |
| `POST /api/v1/query/stream` | **新增** | 流式查询 |
| `POST /api/v1/query/resume` | **新增** | 恢复中断流程 |

## 错误处理

### 统一异常装饰器

```python
def with_error_handler(node_func):
    def wrapper(state: QueryState) -> dict:
        try:
            return node_func(state)
        except NL2DSLException as e:
            return {"status": "error", "error": e.message, "error_code": e.error_code}
        except Exception as e:
            return {"status": "error", "error": str(e), "error_code": "INTERNAL_ERROR"}
    return wrapper

@with_error_handler
def validate_dsl(state: QueryState) -> dict:
    validator.validate(state["dsl"])
    return {}
```

### 全局错误路由

每个节点后接条件边：如果 `status == "error"`，直接路由到 END。

## LangChain 引入点

| 阶段 | LangChain 组件 | 用途 |
|------|---------------|------|
| RAG 检索 | `RunnableParallel` + `Retriever` | 统一检索 schema/metrics/history/terms |
| Prompt 管理 | `ChatPromptTemplate` | DSL 生成 prompt 模板化 |
| Output 解析 | `JsonOutputParser` | LLM 输出自动解析为 DSL dict |
| Embedding | `HuggingFaceEmbeddings` | 替换现有 BGEEmbedder（可选） |

## 文件变更规划

### 新增文件

- `nl2dsl/graph/` — LangGraph 图定义
  - `state.py` — QueryState TypedDict
  - `nodes.py` — 所有节点函数
  - `edges.py` — 条件路由函数
  - `subgraphs.py` — 子图定义
  - `builder.py` — StateGraph 构建 + 编译
  - `chain.py` — LangChain Runnable 封装（RAG、Prompt）

### 修改文件

- `nl2dsl/api.py` — 替换核心链路为 LangGraph 调用
- `nl2dsl/dsl/generator.py` — 适配 RetryChain 到 LangGraph 修正循环
- `pyproject.toml` — 确认 langgraph、langchain 依赖版本

### 删除/废弃

- `nl2dsl/llm/agent.py` — QueryAgent 工作流（被 StateGraph 替代）

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| LangGraph 学习成本 | demo/ 目录已有大量学习代码，团队有基础 |
| 性能开销 | StateGraph 调度开销极小（<1ms），主要耗时仍在 LLM/DB |
| 调试困难 | LangSmith 提供完整 trace，比现有手动 trace 更清晰 |
| 回滚 | 保留 git 历史，可随时回退到纯 Python 版本 |

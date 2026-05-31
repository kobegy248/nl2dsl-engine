# Code Review Report — feat/agent-capabilities

**Branch:** feat/agent-capabilities  
**Scope:** Agent 核心层（意图识别、任务分解、调度、聚合、解释）+ API 工厂适配  
**Review Date:** 2026-05-30  
**Lines Changed:** ~5,600 (net -1,535)

---

## Findings (ranked by severity)

### 🔴 P0 — Correctness Bugs (5)

#### 1. `api_factory.py:476` — Agent `warning` status silently converted to `success`

**What:** The query handler only checks `if agent_result.status == "error"`; everything else returns `status="success"`. When AgentOrchestrator returns `status="warning"` (some sub-queries failed, partial results), the API response claims full success.

**Impact:** Users see success + partial data without knowing some sub-queries failed. The explanation may mention quality notes, but the HTTP response status is indistinguishable from fully-successful queries.

**Fix:** Map agent statuses properly:
```python
if agent_result.status == "error":
    raise ValidationError(...)
# Surface warning as-is
status = agent_result.status  # "success" | "warning" | "clarification"
```

---

#### 2. `nl2dsl/agent/controller.py:60` — Simple queries now depend on `configs/intents.yaml`

**What:** `route()` now calls `self._planner.plan(question)` for **all** queries. Previously, simple queries were routed by entity counts alone, never touching the planner. If `configs/intents.yaml` is missing or unreadable, `Planner.__init__` raises `FileNotFoundError`, and **all queries fail**.

**Impact:** A deployment where the working directory is not the project root (Docker, Celery, tests run from `tests/`) will fail on every request, including simple ones that previously worked.

**Fix:** Make Planner initialization lazy or wrap `route()` in try/except with a fallback to the old entity-based routing when Planner fails.

---

#### 3. `nl2dsl/agent/planner.py:291` — `IntentRegistry.load()` uses relative path

**What:** `Planner.__init__` defaults to `IntentRegistry.load("configs/intents.yaml")` — a relative path.

**Impact:** When imported from a different CWD, the file is not found. This breaks tests, Docker containers, and any async worker that doesn't start from the project root.

**Fix:** Resolve the path relative to the module file:
```python
import pathlib
config_path = pathlib.Path(__file__).parent.parent / "configs" / "intents.yaml"
self._intents = intents or IntentRegistry.load(str(config_path))
```

---

#### 4. `nl2dsl/agent/explainer.py:41` — `__sub_query_id` leaks into user-facing explanations

**What:** `_collect_rows()` injects `"__sub_query_id": "sq-1"` into every row copy. `_format_data_summary()` iterates `row.items()` and includes this internal marker in the text shown to users.

**Impact:** User sees explanations like `product_name=iPhone, __sub_query_id=sq-1, sales_amount=1000`.

**Fix:** Skip internal keys in `_format_data_summary`:
```python
pairs = [f"{k}={v}" for k, v in row.items() if not k.startswith("__")]
```

---

#### 5. `nl2dsl/agent/aggregator.py:114` — `_aggregate_compare` silently drops 3+ sub-queries

**What:** The function computes `diff` and `growth_rate` using only `values[0]` and `values[1]`. If there are 3+ sub-queries, only the first two are compared; the rest are silently ignored.

**Impact:** A query like "对比华东、华南、华北的销售额" creates 3 sub-queries, but the response only shows diff between 华东 and 华南. 华北 is present in `totals` but never compared.

**Fix:** Either (a) enforce max 2 sub-queries in planner decomposition, or (b) extend compare aggregation to handle N-way comparison (e.g. all-pairs diffs or max-min range).

---

### 🟡 P1 — Reliability / Performance Issues (3)

#### 6. `api_factory.py:441` — `AgentController` instantiated on every request

**What:** Both `/api/v1/query` and `/api/v1/query/stream` create a fresh `AgentController()` on every request. Each creation instantiates `Planner()` which re-reads and re-parses `configs/intents.yaml`.

**Impact:** Under load, redundant file I/O + YAML parsing for every request. If the file becomes temporarily unreadable, some requests fail non-deterministically.

**Fix:** Instantiate `AgentController` once at app startup, or cache the `IntentRegistry` in a module-level singleton.

---

#### 7. `nl2dsl/agent/orchestrator.py:67` — `_get_domain_context` fallback can crash

**What:** Falls back to `self._domains["ecommerce"]` without checking if the key exists.

**Impact:** If `_build_domains_dict()` returns only `{"bank": ...}` without `"ecommerce"`, any request with `domain="ecommerce"` (or the default) crashes with `KeyError`.

**Fix:** Use `.get()` with a proper fallback or raise a meaningful `NotFoundError`.

---

#### 8. `api_factory.py:447` — `ExplorationPlan` silently treated as simple query

**What:** The handler checks `isinstance(execution_plan, ComplexExecutionPlan)` and falls through to simple query for everything else. `ExplorationPlan` has `exploration_steps` that are completely ignored.

**Impact:** Open-ended questions ("有什么数据？") that should trigger exploration behavior get a generic single-query response instead.

**Fix:** Add an explicit `elif isinstance(execution_plan, ExplorationPlan)` branch that calls `orchestrator._run_exploration_path()`.

---

### 🟢 P2 — Design / Maintainability Issues (2)

#### 9. `nl2dsl/agent/controller.py:34` — Deterministic routing guards removed

**What:** Old code had hard guards: `metric_count > 1` or `dimension_count > 1` forced `ComplexExecutionPlan`. New code relies entirely on `Planner` intent classification.

**Impact:** If Planner misclassifies a multi-metric query as `single_query`, it enters the simple path and produces incorrect/oversimplified results. The old deterministic guards were a safety net.

**Fix:** Re-add structural guards as a safety check after Planner classification:
```python
if intent == "single_query" and (len(entities.metrics) > 1 or len(entities.dimensions) > 1):
    intent = "compare"  # or force ComplexExecutionPlan
```

---

#### 10. `docs/` — Critical pipeline documentation deleted

**Deleted:** `docs/query-flow.md`, `docs/dag-mermaid.md`, `docs/dag.dot`, `docs/dag.html`, `docs/README.md`, `NL2DSL.md`

**Impact:** These files documented:
- Validation subgraph retry limit (max 3)
- Sandbox → human_review routing
- Permission check subgraph flow
- verify_dsl as post-execution quality gate

New developers (and future maintainers) have no authoritative spec for these behavioral contracts.

**Fix:** Migrate the invariant documentation into code comments or a new `docs/agent/` doc, rather than deleting outright.

---

## Test Coverage Gaps

- **6 tests deleted** from `test_agent_controller.py` that verified deterministic routing (multi-metrics, multi-dimensions, MoM, exploration queries). No replacement tests verify that structural complexity still routes correctly when Planner misclassifies.
- `test_agent_coverage.py` tests confidence range as `0.0 <= c <= 100.0` in two places — should be `<= 1.0` after the recent 0-1 normalization.

---

## Summary by Category

| Category | Count | Key Files |
|----------|-------|-----------|
| Correctness | 5 | api_factory.py, controller.py, planner.py, explainer.py, aggregator.py |
| Reliability | 3 | api_factory.py, orchestrator.py |
| Design | 2 | controller.py, docs/ |

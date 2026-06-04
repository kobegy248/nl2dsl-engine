# Semantic Query Optimizer V1 — Detailed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a rule-engine-based Semantic Query Optimizer that detects and fixes 26 types of semantic errors in DSL queries, with priority-ordered execution and detailed optimization reporting.

**Architecture:** Three-layer pipeline (Normalizer → Rule Engine → Canonical Resolver). The Rule Engine executes rules in priority order (P1→P6) via a PriorityQueue, collecting results into an OptimizationReport. Each rule is independently registered via a decorator-based RuleRegistry and carries metadata for A/B testing and evaluation integration.

**Tech Stack:** Python 3.10+, Pydantic (DSL models), dataclasses (rule types), pytest (testing). No LLM calls — pure deterministic rule engine.

**Design Docs:**
- `docs/specs/semantic-optimizer-error-taxonomy-v2.md` — 26 error types across 9 categories
- `docs/specs/semantic-optimizer-architecture-v2.md` — Architecture and interfaces
- `docs/specs/semantic-optimizer-implementation-plan-v2.md` — Phase-level plan

---

## File Structure (Final State)

```
nl2dsl/optimizer/                     # NEW module
├── __init__.py                        # optimize() entry point
├── normalizer.py                      # Structural normalization
├── metadata.py                        # RuleMetadata dataclass
├── base.py                            # BaseRule + RuleResult
├── context.py                         # RuleContext + SemanticConfig
├── registry.py                        # RuleRegistry (decorator-based)
├── engine.py                          # RuleEngine + Dispatcher + Pipeline
├── report.py                          # OptimizationReport
└── rules/
    ├── __init__.py                    # Re-exports all rules
    ├── structural.py                  # S001-S002
    ├── metric.py                      # M001-M004
    ├── dimension.py                   # D001-D003
    ├── filter.py                      # F001-F005
    ├── intent.py                      # I001-I002
    ├── planning.py                    # P001-P004
    ├── time.py                        # T001-T002
    ├── ambiguity.py                   # A001-A002
    └── governance.py                  # G001-G002

tests/unit/optimizer/                  # NEW tests
├── __init__.py
├── test_normalizer.py
├── test_registry.py
├── test_engine.py
├── test_report.py
└── rules/
    ├── __init__.py
    ├── test_structural.py
    ├── test_metric.py
    ├── test_dimension.py
    ├── test_filter.py
    ├── test_intent.py
    ├── test_planning.py
    ├── test_time.py
    ├── test_ambiguity.py
    └── test_governance.py
```

---

## Phase 0: Infrastructure (P0)

**Goal:** Build the Rule Engine skeleton. Load 1 demo rule → dispatch → execute → output OptimizationReport.

### Task 0.1: Create module structure and SemanticConfig

**Files:**
- Create: `nl2dsl/optimizer/__init__.py`
- Create: `nl2dsl/optimizer/context.py`

- [ ] **Step 1: Create `nl2dsl/optimizer/__init__.py` (empty for now)**

```python
"""Semantic Query Optimizer — rule-engine-based DSL optimization."""
```

- [ ] **Step 2: Create `nl2dsl/optimizer/context.py` with SemanticConfig**

```python
"""Rule execution context and semantic configuration wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SemanticConfig:
    """Typed wrapper around the semantic layer configuration.

    Loaded from metrics.yaml / dimensions.yaml. Provides lookup
    methods for rules to query without touching raw dicts.
    """

    metrics: dict = field(default_factory=dict)
    """{metric_id: {expr, description, canonical_id, data_source, ...}}"""

    dimensions: dict = field(default_factory=dict)
    """{dimension_id: {column, description, value_map, data_source, type, ...}}"""

    data_sources: dict = field(default_factory=dict)
    """{source_name: {table, metrics: [...], dimensions: [...], joins: [...]}}"""

    @classmethod
    def from_registry_dict(cls, registry: dict) -> SemanticConfig:
        """Build from the raw dict returned by SemanticRegistry.load()."""
        return cls(
            metrics=registry.get("metrics", {}),
            dimensions=registry.get("dimensions", {}),
            data_sources=registry.get("data_sources", {}),
        )

    def has_metric(self, name: str) -> bool:
        return name in self.metrics

    def has_dimension(self, name: str) -> bool:
        return name in self.dimensions

    def has_data_source(self, name: str) -> bool:
        return name in self.data_sources

    def get_metric_field(self, name: str) -> str | None:
        """Get the physical field name for a metric from its expr."""
        m = self.metrics.get(name, {})
        expr = m.get("expr", "")
        if "(" in expr and ")" in expr:
            return expr.split("(")[1].split(")")[0].strip()
        return None

    def get_metric_func(self, name: str) -> str | None:
        """Get the aggregation function for a metric from its expr."""
        m = self.metrics.get(name, {})
        expr = m.get("expr", "")
        if "(" in expr:
            return expr.split("(")[0].strip().lower()
        return None

    def get_dimension_column(self, name: str) -> str | None:
        """Get the physical column for a dimension."""
        d = self.dimensions.get(name, {})
        return d.get("column")

    def get_dimension_type(self, name: str) -> str:
        """Get the data type of a dimension (string, integer, boolean, date)."""
        d = self.dimensions.get(name, {})
        return d.get("type", "string")

    def get_value_map(self, dimension: str) -> dict | None:
        """Get the value_map for a dimension if it exists."""
        d = self.dimensions.get(dimension, {})
        return d.get("value_map")

    def get_values(self, dimension: str) -> list | None:
        """Get the allowed values list for a dimension."""
        d = self.dimensions.get(dimension, {})
        return d.get("values")

    def get_table_for_source(self, data_source: str) -> str:
        """Get the physical table name for a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("table", data_source)

    def get_metrics_for_source(self, data_source: str) -> list[str]:
        """Get metric IDs that belong to a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("metrics", [])

    def get_dimensions_for_source(self, data_source: str) -> list[str]:
        """Get dimension IDs that belong to a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("dimensions", [])

    def get_joins_for_source(self, data_source: str) -> list[dict]:
        """Get available JOIN paths from a data source."""
        ds = self.data_sources.get(data_source, {})
        return ds.get("joins", [])

    def find_data_source_for_metric(self, metric_name: str) -> str | None:
        """Find which data source contains a given metric."""
        for src_name, src_cfg in self.data_sources.items():
            if metric_name in src_cfg.get("metrics", []):
                return src_name
        return None

    def find_data_source_for_dimension(self, dimension_name: str) -> str | None:
        """Find which data source contains a given dimension."""
        for src_name, src_cfg in self.data_sources.items():
            if dimension_name in src_cfg.get("dimensions", []):
                return src_name
        return None


@dataclass
class RuleContext:
    """Read-only context passed to every rule during execution."""

    semantic_config: SemanticConfig
    user_id: str | None = None
    user_role: str | None = None
    permission_config: dict | None = None
    original_question: str | None = None
    max_limit: int = 10000
```

- [ ] **Step 3: Run pytest to verify the module imports cleanly**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "from nl2dsl.optimizer.context import SemanticConfig, RuleContext; print('OK')"
```

Expected: `OK`

### Task 0.2: Create RuleMetadata and base types

**Files:**
- Create: `nl2dsl/optimizer/metadata.py`
- Create: `nl2dsl/optimizer/base.py`

- [ ] **Step 1: Create `nl2dsl/optimizer/metadata.py`**

```python
"""RuleMetadata — registration metadata for each rule."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuleMetadata:
    """Registration metadata for a rule.

    Declared as a ClassVar on each BaseRule subclass.
    """

    # Identity
    error_code: str
    """Unique error code, e.g. 'M001'."""

    category: str
    """Category: Metric | Dimension | Filter | Intent | Planning | Time | Ambiguity | Governance | Structural"""

    description: str
    """Human-readable one-line description."""

    # Scheduling
    priority: int
    """1-6: P1=Block, P2=Identity, P3=Consistency, P4=Auth, P5=Completeness, P6=Ambiguity"""

    enabled: bool = True
    """Whether this rule is active. Supports A/B testing."""

    # Behavior
    auto_fixable: bool = False
    """True if the rule provides a fix() method that can auto-correct."""

    severity: str = "Warn"
    """Fix | Warn | Reject"""

    confidence: str = "medium"
    """high | medium | low"""

    is_fatal: bool = False
    """True = Fatal Reject (stop pipeline immediately). False = Normal Reject (continue collecting)."""

    # Benchmark
    benchmark_weight: float = 0.0
    """Weight in Evaluation scoring (aligned with Eval dimension weights)."""
```

- [ ] **Step 2: Create `nl2dsl/optimizer/base.py`**

```python
"""BaseRule abstract class and RuleResult data class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from nl2dsl.optimizer.metadata import RuleMetadata


@dataclass
class RuleResult:
    """The result of running a single rule's check() method."""

    # Identity
    error_code: str
    category: str
    severity: str  # Fix | Warn | Reject
    confidence: str  # high | medium | low
    is_fatal: bool = False

    # Content
    description: str = ""
    before: Any | None = None
    after: Any | None = None
    location: str | None = None  # e.g. "metrics[0].func"

    # Clarification (for A001/A002/T002)
    clarification_required: bool = False
    clarification_question: str | None = None
    candidate_values: list[str] = field(default_factory=list)

    # Metadata
    applied: bool = False
    """Whether a Fix was actually applied to the DSL."""

    @classmethod
    def no_issue(cls, error_code: str, category: str) -> RuleResult:
        """Convenience factory for a 'no issue found' result."""
        return cls(
            error_code=error_code,
            category=category,
            severity="Fix",
            confidence="high",
            description="",
        )

    @classmethod
    def from_metadata(
        cls,
        metadata: RuleMetadata,
        *,
        description: str = "",
        before: Any | None = None,
        after: Any | None = None,
        location: str | None = None,
        clarification_required: bool = False,
        clarification_question: str | None = None,
        candidate_values: list[str] | None = None,
        applied: bool = False,
    ) -> RuleResult:
        """Build a RuleResult from a rule's metadata."""
        return cls(
            error_code=metadata.error_code,
            category=metadata.category,
            severity=metadata.severity,
            confidence=metadata.confidence,
            is_fatal=metadata.is_fatal,
            description=description,
            before=before,
            after=after,
            location=location,
            clarification_required=clarification_required,
            clarification_question=clarification_question,
            candidate_values=candidate_values or [],
            applied=applied,
        )


class BaseRule(ABC):
    """Abstract base class for all optimization rules.

    Subclasses must:
      - Define `metadata` as a ClassVar[RuleMetadata]
      - Implement `check(dsl, context) -> RuleResult`
      - Optionally override `fix(dsl, result) -> dict` for auto-fixable rules
    """

    metadata: ClassVar[RuleMetadata]

    @abstractmethod
    def check(self, dsl: dict, context: Any) -> RuleResult:
        """Detect a semantic issue in the DSL.

        Args:
            dsl: The current DSL dict (normalized).
            context: RuleContext with semantic config, user info, etc.

        Returns:
            RuleResult describing the issue found, or RuleResult.no_issue().
        """
        ...

    def fix(self, dsl: dict, result: RuleResult) -> dict:
        """Apply a correction to the DSL.

        Default implementation: if result.after is set and the rule
        targets a specific location, apply the fix.

        Override for complex fix logic.

        Args:
            dsl: The current DSL dict.
            result: The RuleResult from check() with before/after populated.

        Returns:
            Modified DSL dict.
        """
        if not self.metadata.auto_fixable:
            return dsl
        if result.after is None:
            return dsl
        return self._apply_location_fix(dsl, result)

    def _apply_location_fix(self, dsl: dict, result: RuleResult) -> dict:
        """Apply a fix at a specific location path like 'metrics[0].func'."""
        if not result.location:
            return dsl
        import copy

        dsl = copy.deepcopy(dsl)

        parts = result.location.replace("[", ".").replace("]", "").split(".")
        target = dsl
        for part in parts[:-1]:
            if part.isdigit():
                target = target[int(part)]
            else:
                target = target[part]
        final_key = parts[-1]
        if final_key.isdigit():
            target[int(final_key)] = result.after
        else:
            target[final_key] = result.after
        return dsl
```

- [ ] **Step 3: Verify imports**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "from nl2dsl.optimizer.metadata import RuleMetadata; from nl2dsl.optimizer.base import BaseRule, RuleResult; print('OK')"
```

Expected: `OK`

### Task 0.3: Create RuleRegistry

**Files:**
- Create: `nl2dsl/optimizer/registry.py`

- [ ] **Step 1: Create `nl2dsl/optimizer/registry.py`**

```python
"""RuleRegistry — decorator-based rule registration and discovery."""

from __future__ import annotations

from typing import Type

from nl2dsl.optimizer.base import BaseRule


class RuleRegistry:
    """Central registry for all optimization rules.

    Rules register via the @RuleRegistry.register decorator.
    The registry provides filtered queries by priority, category,
    and enabled status.
    """

    _rules: dict[str, Type[BaseRule]] = {}

    @classmethod
    def register(cls, rule_class: Type[BaseRule]) -> Type[BaseRule]:
        """Decorator: register a rule class by its metadata.error_code."""
        metadata = rule_class.metadata
        cls._rules[metadata.error_code] = rule_class
        return rule_class

    @classmethod
    def get(cls, error_code: str) -> Type[BaseRule] | None:
        """Get a rule class by error code."""
        return cls._rules.get(error_code)

    @classmethod
    def get_all(cls, enabled_only: bool = True) -> list[Type[BaseRule]]:
        """Get all registered rule classes."""
        rules = list(cls._rules.values())
        if enabled_only:
            rules = [r for r in rules if r.metadata.enabled]
        return rules

    @classmethod
    def get_by_priority(
        cls, priority: int, enabled_only: bool = True
    ) -> list[Type[BaseRule]]:
        """Get rules at a specific priority level."""
        return [
            r
            for r in cls.get_all(enabled_only)
            if r.metadata.priority == priority
        ]

    @classmethod
    def get_by_category(
        cls, category: str, enabled_only: bool = True
    ) -> list[Type[BaseRule]]:
        """Get rules in a specific category."""
        return [
            r
            for r in cls.get_all(enabled_only)
            if r.metadata.category == category
        ]

    @classmethod
    def build_priority_queue(
        cls, enabled_only: bool = True
    ) -> dict[int, list[Type[BaseRule]]]:
        """Build a priority-grouped dict {priority: [rule_classes]}.

        Groups are sorted by priority (1-6). Rules within each group
        can execute in any order (no intra-priority dependencies).
        """
        queue: dict[int, list[Type[BaseRule]]] = {}
        for rule_cls in cls.get_all(enabled_only):
            p = rule_cls.metadata.priority
            queue.setdefault(p, []).append(rule_cls)
        return dict(sorted(queue.items()))

    @classmethod
    def clear(cls) -> None:
        """Clear all registered rules. Mainly for testing."""
        cls._rules.clear()

    @classmethod
    def count(cls, enabled_only: bool = True) -> int:
        """Return the number of registered rules."""
        return len(cls.get_all(enabled_only))
```

- [ ] **Step 2: Verify RuleRegistry works**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata

@RuleRegistry.register
class DemoRule(BaseRule):
    metadata = RuleMetadata(
        error_code='S002',
        category='Structural',
        description='Missing data source',
        priority=1,
        severity='Reject',
        confidence='high',
        is_fatal=True,
    )
    def check(self, dsl, context):
        return RuleResult.no_issue('S002', 'Structural')

assert RuleRegistry.count() == 1
assert RuleRegistry.get('S002') is DemoRule
print('OK')
"
```

Expected: `OK`

### Task 0.4: Create Normalizer

**Files:**
- Create: `nl2dsl/optimizer/normalizer.py`

- [ ] **Step 1: Create `nl2dsl/optimizer/normalizer.py`**

```python
"""Normalizer — structural DSL normalization without semantic config."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NormalizerLog:
    """Record of normalization actions taken."""

    actions: list[str] = field(default_factory=list)

    def add(self, action: str) -> None:
        self.actions.append(action)


class Normalizer:
    """Structural normalizer for raw DSL dicts.

    Does NOT access semantic config. Only enforces structural
    correctness: defaults, type coercion, dedup, format normalization.
    """

    DEFAULT_LIMIT = 100

    def normalize(self, raw_dsl: dict) -> tuple[dict, NormalizerLog]:
        """Normalize a raw DSL dict.

        Returns:
            (normalized_dsl_dict, NormalizerLog)
        """
        import copy

        dsl = copy.deepcopy(raw_dsl)
        log = NormalizerLog()

        # 1. Ensure top-level fields exist with defaults
        defaults = {
            "metrics": None,
            "dimensions": None,
            "filters": None,
            "having": None,
            "order_by": None,
            "limit": self.DEFAULT_LIMIT,
            "offset": 0,
            "data_source": "",
            "time_field": None,
            "time_range": None,
            "joins": None,
        }
        for key, default in defaults.items():
            if key not in dsl:
                dsl[key] = default
                log.add(f"Added missing field '{key}' = {default!r}")

        # 2. Type coercion
        dsl, coercion_log = self._coerce_types(dsl)
        log.actions.extend(coercion_log)

        # 3. Filter structure normalization
        if dsl.get("filters") is not None:
            dsl["filters"] = self._normalize_filters(dsl["filters"], log)

        # 4. Dedup dimensions
        dims = dsl.get("dimensions")
        if isinstance(dims, list) and len(dims) > 0:
            seen = set()
            deduped = []
            for d in dims:
                if d not in seen:
                    seen.add(d)
                    deduped.append(d)
            if len(deduped) < len(dims):
                log.add(f"Deduped dimensions: {dims} -> {deduped}")
                dsl["dimensions"] = deduped

        # 5. Dedup metrics by (func, field) pair
        metrics = dsl.get("metrics")
        if isinstance(metrics, list) and len(metrics) > 0:
            seen = set()
            deduped = []
            for m in metrics:
                key = (m.get("func", ""), m.get("field", ""))
                if key not in seen:
                    seen.add(key)
                    deduped.append(m)
            if len(deduped) < len(metrics):
                log.add(f"Deduped metrics: {len(metrics)} -> {len(deduped)}")
                dsl["metrics"] = deduped

        # 6. Generate missing aliases for metrics
        dsl = self._ensure_aliases(dsl, log)

        return dsl, log

    def _coerce_types(self, dsl: dict) -> tuple[dict, list[str]]:
        """Coerce field types to their expected formats."""
        log: list[str] = []

        # Coerce limit to int
        if "limit" in dsl and dsl["limit"] is not None:
            try:
                dsl["limit"] = int(dsl["limit"])
            except (ValueError, TypeError):
                log.add(f"Could not coerce limit={dsl['limit']!r} to int, using default")
                dsl["limit"] = self.DEFAULT_LIMIT

        # Coerce offset to int
        if "offset" in dsl and dsl["offset"] is not None:
            try:
                dsl["offset"] = int(dsl["offset"])
            except (ValueError, TypeError):
                dsl["offset"] = 0
                log.add("Coerced invalid offset to 0")

        # Coerce empty data_source
        if dsl.get("data_source") is None:
            dsl["data_source"] = ""
            log.add("Coerced null data_source to empty string")

        # Coerce empty string lists to None
        for field in ("metrics", "dimensions", "joins", "order_by"):
            val = dsl.get(field)
            if isinstance(val, list) and len(val) == 0:
                dsl[field] = None
                log.add(f"Coerced empty {field} list to None")

        return dsl, log

    def _normalize_filters(self, filters, log: NormalizerLog) -> list[dict]:
        """Accept multiple filter representations, return unified list of dicts."""
        if filters is None:
            return None

        # Already a list of filter dicts
        if isinstance(filters, list):
            normalized = []
            for f in filters:
                if isinstance(f, dict):
                    normalized.append(self._normalize_single_filter(f))
            return normalized if normalized else None

        # Tree format: {"op": "and", "children": [...]}
        if isinstance(filters, dict):
            if "op" in filters and "children" in filters:
                log.add("Normalized filter tree to flat list (recursive)")
                return self._flatten_filter_tree(filters, log)
            # Single filter dict
            return [self._normalize_single_filter(filters)]

        return None

    def _normalize_single_filter(self, f: dict) -> dict:
        """Ensure a single filter dict has required keys."""
        return {
            "field": f.get("field", ""),
            "operator": f.get("operator", "="),
            "value": f.get("value"),
        }

    def _flatten_filter_tree(self, node: dict, log: NormalizerLog) -> list[dict]:
        """Flatten a filter tree into a list. For non-trivial trees, this is lossy
        (loses AND/OR structure), so we log a warning.
        """
        results = []
        op = node.get("op", "and")
        children = node.get("children", [])

        for child in children:
            if isinstance(child, dict):
                if "op" in child and "children" in child:
                    # Nested tree
                    results.extend(self._flatten_filter_tree(child, log))
                else:
                    results.append(self._normalize_single_filter(child))

        if op == "or":
            log.add("Warning: flattened OR filter tree — logical structure may be lost")
        return results

    def _ensure_aliases(self, dsl: dict, log: NormalizerLog) -> dict:
        """Generate default aliases for metrics that lack them."""
        metrics = dsl.get("metrics")
        if not metrics:
            return dsl

        for i, m in enumerate(metrics):
            if isinstance(m, dict) and not m.get("alias"):
                func = m.get("func", "").upper()
                field = m.get("field", "unknown")
                alias = f"{func.lower()}_{field}" if func else field
                m["alias"] = alias
                log.add(f"Generated alias '{alias}' for metrics[{i}]")

        return dsl
```

- [ ] **Step 2: Verify Normalizer with basic cases**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "
from nl2dsl.optimizer.normalizer import Normalizer

n = Normalizer()

# Test 1: Default field injection
dsl, log = n.normalize({'data_source': 'orders'})
assert dsl['limit'] == 100
assert dsl['metrics'] is None
assert dsl['dimensions'] is None
assert 'Added missing field' in log.actions[0]
print('Test 1 PASS: defaults injected')

# Test 2: Type coercion
dsl, log = n.normalize({'data_source': 'orders', 'limit': '50'})
assert dsl['limit'] == 50
assert isinstance(dsl['limit'], int)
print('Test 2 PASS: limit coerced')

# Test 3: Dimension dedup
dsl, log = n.normalize({'data_source': 'orders', 'dimensions': ['a', 'b', 'a']})
assert dsl['dimensions'] == ['a', 'b']
print('Test 3 PASS: dimensions deduped')

# Test 4: Alias generation
dsl, log = n.normalize({'data_source': 'orders', 'metrics': [{'func': 'sum', 'field': 'amount'}]})
assert dsl['metrics'][0]['alias'] == 'sum_amount'
print('Test 4 PASS: alias generated')

# Test 5: Empty lists -> None
dsl, log = n.normalize({'data_source': 'orders', 'metrics': []})
assert dsl['metrics'] is None
print('Test 5 PASS: empty list -> None')

print('ALL Normalizer tests PASSED')
"
```

Expected: All 5 tests pass.

### Task 0.5: Create OptimizationReport

**Files:**
- Create: `nl2dsl/optimizer/report.py`

- [ ] **Step 1: Create `nl2dsl/optimizer/report.py`**

```python
"""OptimizationReport — the output of one optimization run."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from nl2dsl.optimizer.base import RuleResult


@dataclass
class OptimizationReport:
    """Complete report from one optimization run."""

    # Identity
    report_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    query_id: str | None = None

    # Statistics
    total_rules_checked: int = 0
    total_rules_triggered: int = 0

    fixes_applied: list[dict] = field(default_factory=list)
    fixes_bypassed: list[dict] = field(default_factory=list)
    warnings_issued: list[dict] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    fatal_rejection: dict | None = None

    # Metrics
    fix_rate: float = 0.0
    warning_rate: float = 0.0
    rejection_rate: float = 0.0
    fatal: bool = False

    # Performance
    elapsed_ms: int = 0
    phases: dict[str, int] = field(default_factory=dict)

    # DSL comparison
    dsl_before: dict | None = None
    dsl_after: dict | None = None
    diff: list[str] = field(default_factory=list)

    def add_result(self, result: RuleResult) -> None:
        """Classify and record a RuleResult."""
        result_dict = {
            "error_code": result.error_code,
            "category": result.category,
            "severity": result.severity,
            "confidence": result.confidence,
            "description": result.description,
            "before": result.before,
            "after": result.after,
            "location": result.location,
            "clarification_required": result.clarification_required,
            "clarification_question": result.clarification_question,
            "applied": result.applied,
        }

        if result.severity == "Fix" and result.applied:
            self.fixes_applied.append(result_dict)
        elif result.severity == "Fix" and not result.applied:
            self.fixes_bypassed.append(result_dict)
        elif result.severity == "Warn":
            self.warnings_issued.append(result_dict)
        elif result.severity == "Reject":
            if result.is_fatal:
                self.fatal_rejection = result_dict
                self.fatal = True
            else:
                self.rejections.append(result_dict)

    def finalize(self, elapsed_ms: int, phases: dict[str, int] | None = None) -> None:
        """Compute summary metrics after all rules have run."""
        self.elapsed_ms = elapsed_ms
        if phases:
            self.phases = phases

        total = max(self.total_rules_triggered, 1)
        self.fix_rate = len(self.fixes_applied) / total
        self.warning_rate = len(self.warnings_issued) / total
        self.rejection_rate = (
            len(self.rejections) + (1 if self.fatal_rejection else 0)
        ) / total

    def compute_diff(self) -> None:
        """Generate a human-readable diff between dsl_before and dsl_after."""
        if not self.dsl_before or not self.dsl_after:
            return
        diffs = []
        for key in self.dsl_before:
            before_val = self.dsl_before.get(key)
            after_val = self.dsl_after.get(key)
            if before_val != after_val:
                diffs.append(f"{key}: {before_val!r} → {after_val!r}")
        self.diff = diffs

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "report_id": self.report_id,
            "query_id": self.query_id,
            "total_rules_checked": self.total_rules_checked,
            "total_rules_triggered": self.total_rules_triggered,
            "fixes_applied": self.fixes_applied,
            "fixes_bypassed": self.fixes_bypassed,
            "warnings_issued": self.warnings_issued,
            "rejections": self.rejections,
            "fatal_rejection": self.fatal_rejection,
            "fix_rate": self.fix_rate,
            "warning_rate": self.warning_rate,
            "rejection_rate": self.rejection_rate,
            "fatal": self.fatal,
            "elapsed_ms": self.elapsed_ms,
            "phases": self.phases,
            "diff": self.diff,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
```

- [ ] **Step 2: Verify Report is functional**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "
from nl2dsl.optimizer.report import OptimizationReport
from nl2dsl.optimizer.base import RuleResult

r = OptimizationReport()
r.total_rules_checked = 5
r.total_rules_triggered = 3

# Add a fix
r.add_result(RuleResult(
    error_code='M001', category='Metric', severity='Fix',
    confidence='high', description='Fixed agg func', applied=True,
    before={'func': 'avg'}, after={'func': 'sum'},
    location='metrics[0].func',
))
# Add a warning
r.add_result(RuleResult(
    error_code='F003', category='Filter', severity='Warn',
    confidence='medium', description='Missing time range',
))
# Add a rejection
r.add_result(RuleResult(
    error_code='S002', category='Structural', severity='Reject',
    confidence='high', description='Missing data source', is_fatal=True,
))

r.finalize(elapsed_ms=15)
assert r.fatal == True
assert len(r.fixes_applied) == 1
assert len(r.warnings_issued) == 1
assert r.fatal_rejection is not None
print(r.to_json())
print('PASS')
"
```

Expected: JSON output and `PASS`.

### Task 0.6: Create RuleEngine (Dispatcher + Pipeline)

**Files:**
- Create: `nl2dsl/optimizer/engine.py`

- [ ] **Step 1: Create `nl2dsl/optimizer/engine.py`**

```python
"""RuleEngine — dispatcher, priority queue, and pipeline execution."""

from __future__ import annotations

import time
from typing import Type

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.context import RuleContext
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.report import OptimizationReport


class RuleEngine:
    """Executes rules in priority order against a normalized DSL.

    Pipeline:
      1. Build priority queue from RuleRegistry
      2. For each priority level (P1→P6):
         a. Execute all rules' check() methods
         b. Collect RuleResults
         c. Apply Fixes (call fix())
         d. Check for Fatal Reject → stop if found
         e. Update DSL for next priority level
      3. Compose OptimizationReport

    Normal Reject errors (is_fatal=False) do NOT stop the pipeline
    — they are recorded and execution continues to collect more issues.
    """

    def __init__(self, context: RuleContext):
        self._context = context

    def run(
        self,
        dsl: dict,
        *,
        enabled_rules: list[str] | None = None,
        disabled_rules: list[str] | None = None,
    ) -> tuple[dict, OptimizationReport]:
        """Run the full optimization pipeline.

        Args:
            dsl: Normalized DSL dict.
            enabled_rules: If set, ONLY run these error codes (whitelist).
            disabled_rules: If set, skip these error codes (blacklist).

        Returns:
            (optimized_dsl_dict, OptimizationReport)
        """
        start_time = time.time()
        report = OptimizationReport()
        report.dsl_before = dict(dsl)  # shallow copy for diff

        current_dsl = dict(dsl)
        phases: dict[str, int] = {}

        # Build priority queue
        queue = RuleRegistry.build_priority_queue(enabled_only=True)
        report.total_rules_checked = sum(len(rules) for rules in queue.values())

        # Execute each priority level
        for priority in sorted(queue.keys()):
            phase_start = time.time()
            rules = queue[priority]

            # Filter by whitelist/blacklist
            rules = self._filter_rules(rules, enabled_rules, disabled_rules)
            if not rules:
                continue

            # Execute all rules at this priority level
            for rule_cls in rules:
                result = self._execute_rule(rule_cls, current_dsl)
                if result is None:
                    continue

                report.total_rules_triggered += 1

                # Apply fix if applicable
                if result.severity == "Fix" and rule_cls.metadata.auto_fixable:
                    try:
                        rule_instance = rule_cls()
                        current_dsl = rule_instance.fix(current_dsl, result)
                        result.applied = True
                    except Exception:
                        result.applied = False

                report.add_result(result)

                # Fatal Reject → stop immediately
                if result.is_fatal and result.severity == "Reject":
                    elapsed = int((time.time() - start_time) * 1000)
                    report.dsl_after = current_dsl
                    report.compute_diff()
                    report.finalize(elapsed, phases)
                    return current_dsl, report

            phases[f"P{priority}"] = int((time.time() - phase_start) * 1000)

        elapsed = int((time.time() - start_time) * 1000)
        report.dsl_after = current_dsl
        report.compute_diff()
        report.finalize(elapsed, phases)
        return current_dsl, report

    def _execute_rule(
        self, rule_cls: Type[BaseRule], dsl: dict
    ) -> RuleResult | None:
        """Instantiate and execute a single rule's check().

        Returns None if the rule finds no issue (empty description).
        """
        try:
            rule = rule_cls()
            result = rule.check(dsl, self._context)
            if not result.description:
                return None  # No issue found
            return result
        except Exception as exc:
            # Rule crashed → emit a warning-level result
            return RuleResult(
                error_code=rule_cls.metadata.error_code,
                category=rule_cls.metadata.category,
                severity="Warn",
                confidence="low",
                description=f"Rule execution error: {exc}",
                is_fatal=False,
            )

    @staticmethod
    def _filter_rules(
        rules: list[Type[BaseRule]],
        enabled: list[str] | None,
        disabled: list[str] | None,
    ) -> list[Type[BaseRule]]:
        """Apply whitelist/blacklist filtering."""
        if enabled is not None:
            enabled_set = set(enabled)
            return [r for r in rules if r.metadata.error_code in enabled_set]
        if disabled is not None:
            disabled_set = set(disabled)
            return [r for r in rules if r.metadata.error_code not in disabled_set]
        return rules
```

- [ ] **Step 2: Verify RuleEngine with the demo rule S002**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "
from nl2dsl.optimizer.registry import RuleRegistry
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.engine import RuleEngine

# Register a demo S002 rule
@RuleRegistry.register
class S002_MissingDataSource(BaseRule):
    metadata = RuleMetadata(
        error_code='S002',
        category='Structural',
        description='DSL is missing a data_source',
        priority=1,
        severity='Reject',
        confidence='high',
        is_fatal=True,
    )
    def check(self, dsl, context):
        if not dsl.get('data_source'):
            return RuleResult.from_metadata(
                self.metadata,
                description='data_source is empty or missing',
                before={'data_source': ''},
            )
        return RuleResult.no_issue('S002', 'Structural')

# Test 1: Trigger fatal reject
config = SemanticConfig()
ctx = RuleContext(semantic_config=config)
engine = RuleEngine(ctx)

dsl = {'data_source': ''}
result_dsl, report = engine.run(dsl)
assert report.fatal == True
assert report.fatal_rejection['error_code'] == 'S002'
print('Test 1 PASS: Missing data_source triggers fatal reject')

# Test 2: No issue
dsl2 = {'data_source': 'orders'}
result_dsl2, report2 = engine.run(dsl2)
assert report2.fatal == False
assert report2.total_rules_triggered == 0
print('Test 2 PASS: Valid data_source passes')

RuleRegistry.clear()
print('ALL RuleEngine tests PASSED')
"
```

Expected: Both tests pass.

### Task 0.7: Create the optimize() entry point

**Files:**
- Modify: `nl2dsl/optimizer/__init__.py`

- [ ] **Step 1: Update `nl2dsl/optimizer/__init__.py`**

```python
"""Semantic Query Optimizer — rule-engine-based DSL optimization.

Usage:
    from nl2dsl.optimizer import optimize

    optimized_dsl, report = optimize(
        dsl,
        semantic_config=semantic_config,
        user_role="analyst",
        original_question="本月华东区GMV",
    )
"""

from __future__ import annotations

from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.engine import RuleEngine
from nl2dsl.optimizer.normalizer import Normalizer
from nl2dsl.optimizer.report import OptimizationReport

# Import all rule modules so @RuleRegistry.register executes
from nl2dsl.optimizer.rules import structural  # noqa: F401


def optimize(
    dsl: dict,
    *,
    semantic_config: SemanticConfig,
    user_id: str | None = None,
    user_role: str | None = None,
    permission_config: dict | None = None,
    original_question: str | None = None,
    enabled_rules: list[str] | None = None,
    disabled_rules: list[str] | None = None,
    max_limit: int = 10000,
) -> tuple[dict, OptimizationReport]:
    """Run semantic optimization on a DSL dict.

    Pipeline: Normalize → Rule Engine → (future: Canonical Resolver)

    Args:
        dsl: Raw DSL dict (LLM output).
        semantic_config: Loaded semantic layer configuration.
        user_id: Optional user identifier.
        user_role: Optional user role for permission checks.
        permission_config: Optional permission configuration dict.
        original_question: Original NL question for ambiguity/time checks.
        enabled_rules: Whitelist of error codes to run.
        disabled_rules: Blacklist of error codes to skip.
        max_limit: Maximum query limit (default 10000).

    Returns:
        (optimized_dsl_dict, OptimizationReport)
    """
    # Phase 1: Normalize
    normalizer = Normalizer()
    normalized_dsl, _normalizer_log = normalizer.normalize(dsl)

    # Phase 2: Rule Engine
    context = RuleContext(
        semantic_config=semantic_config,
        user_id=user_id,
        user_role=user_role,
        permission_config=permission_config,
        original_question=original_question,
        max_limit=max_limit,
    )

    engine = RuleEngine(context)
    optimized_dsl, report = engine.run(
        normalized_dsl,
        enabled_rules=enabled_rules,
        disabled_rules=disabled_rules,
    )

    return optimized_dsl, report
```

- [ ] **Step 2: Create the rules package with minimal structural rules**

```bash
mkdir -p D:/demo/db-gpt/NL2DSL/nl2dsl/optimizer/rules
```

- [ ] **Step 3: Create `nl2dsl/optimizer/rules/__init__.py`**

```python
"""Optimizer rules — each module registers its rules via @RuleRegistry.register."""
```

- [ ] **Step 4: Create `nl2dsl/optimizer/rules/structural.py`**

```python
"""Structural rules: S001 (Empty Query), S002 (Missing DataSource)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class S001_EmptyQuery(BaseRule):
    metadata = RuleMetadata(
        error_code="S001",
        category="Structural",
        description="DSL has no metrics and no dimensions — equivalent to SELECT *",
        priority=1,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        metrics = dsl.get("metrics")
        dimensions = dsl.get("dimensions")
        if not metrics and not dimensions:
            return RuleResult.from_metadata(
                self.metadata,
                description="Both metrics and dimensions are empty — query would be SELECT *",
                before={"metrics": metrics, "dimensions": dimensions},
            )
        return RuleResult.no_issue("S001", "Structural")


@RuleRegistry.register
class S002_MissingDataSource(BaseRule):
    metadata = RuleMetadata(
        error_code="S002",
        category="Structural",
        description="DSL is missing a data_source",
        priority=1,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        data_source = dsl.get("data_source", "")
        if not data_source:
            return RuleResult.from_metadata(
                self.metadata,
                description="data_source is empty or missing — cannot determine query target",
                before={"data_source": data_source},
            )
        return RuleResult.no_issue("S002", "Structural")
```

- [ ] **Step 5: Run end-to-end test of the full P0 pipeline**

```bash
cd D:/demo/db-gpt/NL2DSL && python -c "
from nl2dsl.optimizer import optimize
from nl2dsl.optimizer.context import SemanticConfig

config = SemanticConfig()

# Test 1: S002 fatal reject
dsl, report = optimize({'metrics': [{'func': 'sum', 'field': 'amount'}]}, semantic_config=config)
assert report.fatal == True
assert report.fatal_rejection['error_code'] == 'S002'
print('Test 1 PASS: S002 fatal reject')

# Test 2: S001 fatal reject
dsl, report = optimize({'data_source': 'orders'}, semantic_config=config)
assert report.fatal == True
assert report.fatal_rejection['error_code'] == 'S001'
print('Test 2 PASS: S001 fatal reject')

# Test 3: Valid DSL passes both
dsl, report = optimize(
    {'data_source': 'orders', 'metrics': [{'func': 'sum', 'field': 'pay_amount', 'alias': 'gmv'}]},
    semantic_config=config,
)
assert report.fatal == False
assert report.total_rules_triggered == 0
print('Test 3 PASS: valid DSL passes')
print(report.to_json())

# Test 4: Normalizer adds defaults
dsl, report = optimize(
    {'data_source': 'orders', 'metrics': [{'func': 'sum', 'field': 'pay_amount'}]},
    semantic_config=config,
)
assert dsl['metrics'][0]['alias'] == 'sum_pay_amount'
print('Test 4 PASS: alias auto-generated')
print('ALL E2E tests PASSED')
"
```

Expected: All 4 tests pass.

### Task 0.8: Write P0 unit tests

**Files:**
- Create: `tests/unit/optimizer/__init__.py` (empty)
- Create: `tests/unit/optimizer/test_normalizer.py`
- Create: `tests/unit/optimizer/test_registry.py`
- Create: `tests/unit/optimizer/test_engine.py`
- Create: `tests/unit/optimizer/test_report.py`

- [ ] **Step 1: Create `tests/unit/optimizer/test_normalizer.py`**

```python
"""Tests for Normalizer — structural DSL normalization."""

import pytest
from nl2dsl.optimizer.normalizer import Normalizer


@pytest.fixture
def normalizer():
    return Normalizer()


class TestNormalizerDefaults:
    def test_injects_missing_fields(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders"})
        assert dsl["limit"] == 100
        assert dsl["offset"] == 0
        assert dsl["metrics"] is None
        assert dsl["dimensions"] is None
        assert dsl["filters"] is None
        assert dsl["having"] is None
        assert dsl["order_by"] is None
        assert dsl["time_field"] is None
        assert dsl["time_range"] is None
        assert dsl["joins"] is None

    def test_does_not_overwrite_existing_fields(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "limit": 50})
        assert dsl["limit"] == 50


class TestNormalizerTypeCoercion:
    def test_coerces_limit_string_to_int(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "limit": "50"})
        assert dsl["limit"] == 50
        assert isinstance(dsl["limit"], int)

    def test_coerces_invalid_limit_to_default(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "limit": "abc"})
        assert dsl["limit"] == 100

    def test_coerces_null_data_source_to_empty_string(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": None})
        assert dsl["data_source"] == ""


class TestNormalizerDedup:
    def test_dedup_dimensions(self, normalizer):
        dsl, log = normalizer.normalize(
            {"data_source": "orders", "dimensions": ["a", "b", "a", "c", "b"]}
        )
        assert dsl["dimensions"] == ["a", "b", "c"]

    def test_dedup_metrics_by_func_field(self, normalizer):
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [
                    {"func": "sum", "field": "amount"},
                    {"func": "sum", "field": "amount"},
                    {"func": "count", "field": "amount"},
                ],
            }
        )
        assert len(dsl["metrics"]) == 2

    def test_single_dimension_not_affected(self, normalizer):
        dsl, log = normalizer.normalize(
            {"data_source": "orders", "dimensions": ["product_name"]}
        )
        assert dsl["dimensions"] == ["product_name"]


class TestNormalizerAliases:
    def test_generates_alias_for_unaliased_metric(self, normalizer):
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [{"func": "sum", "field": "pay_amount"}],
            }
        )
        assert dsl["metrics"][0]["alias"] == "sum_pay_amount"

    def test_preserves_existing_alias(self, normalizer):
        dsl, log = normalizer.normalize(
            {
                "data_source": "orders",
                "metrics": [
                    {"func": "sum", "field": "pay_amount", "alias": "gmv"}
                ],
            }
        )
        assert dsl["metrics"][0]["alias"] == "gmv"


class TestNormalizerEmptyLists:
    def test_empty_metrics_becomes_none(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "metrics": []})
        assert dsl["metrics"] is None

    def test_empty_dimensions_becomes_none(self, normalizer):
        dsl, log = normalizer.normalize({"data_source": "orders", "dimensions": []})
        assert dsl["dimensions"] is None
```

- [ ] **Step 2: Create `tests/unit/optimizer/test_registry.py`**

```python
"""Tests for RuleRegistry."""

import pytest
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@pytest.fixture(autouse=True)
def clear_registry():
    """Ensure registry is clean before and after each test."""
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


def _make_rule(error_code: str, priority: int, category: str, enabled: bool = True):
    """Factory to create a minimal rule class for testing."""

    @RuleRegistry.register
    class _TestRule(BaseRule):
        metadata = RuleMetadata(
            error_code=error_code,
            category=category,
            description=f"Test rule {error_code}",
            priority=priority,
            enabled=enabled,
        )

        def check(self, dsl, context):
            return RuleResult.no_issue(error_code, category)

    return _TestRule


class TestRuleRegistryRegistration:
    def test_register_and_get(self):
        rule_cls = _make_rule("T001", priority=5, category="Time")
        assert RuleRegistry.count() == 1
        assert RuleRegistry.get("T001") is rule_cls

    def test_get_nonexistent_returns_none(self):
        assert RuleRegistry.get("NOPE") is None

    def test_multiple_registrations(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("S002", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")
        assert RuleRegistry.count() == 3


class TestRuleRegistryFiltering:
    def test_get_by_priority(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("S002", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")

        p1 = RuleRegistry.get_by_priority(1)
        assert len(p1) == 2
        assert all(r.metadata.priority == 1 for r in p1)

    def test_get_by_category(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")
        _make_rule("M002", priority=5, category="Metric")

        metric_rules = RuleRegistry.get_by_category("Metric")
        assert len(metric_rules) == 2

    def test_disabled_rules_excluded(self):
        _make_rule("S001", priority=1, category="Structural", enabled=True)
        _make_rule("S002", priority=1, category="Structural", enabled=False)

        assert RuleRegistry.count(enabled_only=True) == 1
        assert RuleRegistry.count(enabled_only=False) == 2


class TestRuleRegistryPriorityQueue:
    def test_build_priority_queue(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("M001", priority=2, category="Metric")
        _make_rule("A001", priority=6, category="Ambiguity")

        queue = RuleRegistry.build_priority_queue()
        assert list(queue.keys()) == [1, 2, 6]
        assert len(queue[1]) == 1
        assert len(queue[2]) == 1
        assert len(queue[6]) == 1

    def test_same_priority_grouped(self):
        _make_rule("S001", priority=1, category="Structural")
        _make_rule("S002", priority=1, category="Structural")
        _make_rule("I001", priority=1, category="Intent")

        queue = RuleRegistry.build_priority_queue()
        assert list(queue.keys()) == [1]
        assert len(queue[1]) == 3
```

- [ ] **Step 3: Create `tests/unit/optimizer/test_engine.py`**

```python
"""Tests for RuleEngine."""

import pytest
from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.context import SemanticConfig, RuleContext
from nl2dsl.optimizer.engine import RuleEngine
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@pytest.fixture(autouse=True)
def clear_registry():
    RuleRegistry.clear()
    yield
    RuleRegistry.clear()


@pytest.fixture
def context():
    return RuleContext(semantic_config=SemanticConfig())


class TestRuleEngineFatalReject:
    def test_fatal_reject_stops_pipeline(self, context):
        @RuleRegistry.register
        class FatalRule(BaseRule):
            metadata = RuleMetadata(
                error_code="S001",
                category="Structural",
                description="Always fatal",
                priority=1,
                severity="Reject",
                confidence="high",
                is_fatal=True,
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="Fatal error",
                )

        @RuleRegistry.register
        class ShouldNotRun(BaseRule):
            metadata = RuleMetadata(
                error_code="M001",
                category="Metric",
                description="Should not run",
                priority=2,
                severity="Fix",
                confidence="high",
                auto_fixable=True,
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="I should not have been called",
                )

        engine = RuleEngine(context)
        dsl, report = engine.run({"data_source": "orders"})
        assert report.fatal is True
        assert report.total_rules_triggered == 1  # only FatalRule fired
        assert report.fatal_rejection["error_code"] == "S001"

    def test_normal_reject_does_not_stop(self, context):
        @RuleRegistry.register
        class NormalRejectRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M004",
                category="Metric",
                description="Normal reject",
                priority=3,
                severity="Reject",
                confidence="high",
                is_fatal=False,
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="Normal rejection",
                )

        @RuleRegistry.register
        class LaterRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M002",
                category="Metric",
                description="Should still run",
                priority=5,
                severity="Warn",
                confidence="low",
            )

            def check(self, dsl, ctx):
                return RuleResult.from_metadata(
                    self.metadata,
                    description="Warning from later rule",
                )

        engine = RuleEngine(context)
        dsl, report = engine.run({"data_source": "orders"})
        assert report.fatal is False
        assert report.total_rules_triggered == 2
        assert len(report.rejections) == 1
        assert len(report.warnings_issued) == 1


class TestRuleEngineFixes:
    def test_fix_is_applied_and_dsl_updated(self, context):
        @RuleRegistry.register
        class FixRule(BaseRule):
            metadata = RuleMetadata(
                error_code="M003",
                category="Metric",
                description="Add missing alias",
                priority=2,
                severity="Fix",
                confidence="high",
                auto_fixable=True,
            )

            def check(self, dsl, ctx):
                metrics = dsl.get("metrics", [])
                for i, m in enumerate(metrics):
                    if not m.get("alias"):
                        return RuleResult.from_metadata(
                            self.metadata,
                            description="Missing alias",
                            before={"alias": None},
                            after={"alias": "fixed_alias"},
                            location=f"metrics[{i}].alias",
                        )
                return RuleResult.no_issue("M003", "Metric")

        engine = RuleEngine(context)
        dsl, report = engine.run(
            {
                "data_source": "orders",
                "metrics": [{"func": "sum", "field": "amount"}],
            }
        )
        assert report.total_rules_triggered == 1
        assert len(report.fixes_applied) == 1
        assert dsl["metrics"][0]["alias"] == "fixed_alias"


class TestRuleEngineWhitelistBlacklist:
    def test_enabled_rules_whitelist(self, context):
        @RuleRegistry.register
        class RuleA(BaseRule):
            metadata = RuleMetadata(
                error_code="M001", category="Metric", description="A",
                priority=2, severity="Fix", confidence="high", auto_fixable=True,
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="A triggered")

        @RuleRegistry.register
        class RuleB(BaseRule):
            metadata = RuleMetadata(
                error_code="M002", category="Metric", description="B",
                priority=5, severity="Warn", confidence="low",
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="B triggered")

        engine = RuleEngine(context)
        dsl, report = engine.run(
            {"data_source": "orders"}, enabled_rules=["M001"]
        )
        assert report.total_rules_triggered == 1
        assert report.fixes_applied[0]["error_code"] == "M001"

    def test_disabled_rules_blacklist(self, context):
        @RuleRegistry.register
        class RuleA(BaseRule):
            metadata = RuleMetadata(
                error_code="M001", category="Metric", description="A",
                priority=2, severity="Fix", confidence="high", auto_fixable=True,
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="A triggered")

        @RuleRegistry.register
        class RuleB(BaseRule):
            metadata = RuleMetadata(
                error_code="M002", category="Metric", description="B",
                priority=5, severity="Warn", confidence="low",
            )
            def check(self, dsl, ctx):
                return RuleResult.from_metadata(self.metadata, description="B triggered")

        engine = RuleEngine(context)
        dsl, report = engine.run(
            {"data_source": "orders"}, disabled_rules=["M001"]
        )
        assert report.total_rules_triggered == 1
        assert report.warnings_issued[0]["error_code"] == "M002"
```

- [ ] **Step 4: Create `tests/unit/optimizer/test_report.py`**

```python
"""Tests for OptimizationReport."""

from nl2dsl.optimizer.base import RuleResult
from nl2dsl.optimizer.report import OptimizationReport


class TestOptimizationReport:
    def test_empty_report(self):
        r = OptimizationReport()
        r.finalize(elapsed_ms=0)
        assert r.total_rules_checked == 0
        assert r.total_rules_triggered == 0
        assert r.fix_rate == 0.0
        assert r.fatal is False

    def test_add_fix_result(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="M001", category="Metric", severity="Fix",
            confidence="high", description="Fixed", applied=True,
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert len(r.fixes_applied) == 1
        assert len(r.warnings_issued) == 0

    def test_add_warning_result(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="F003", category="Filter", severity="Warn",
            confidence="medium", description="Missing time range",
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert len(r.warnings_issued) == 1
        assert len(r.fixes_applied) == 0

    def test_add_fatal_rejection(self):
        r = OptimizationReport()
        result = RuleResult(
            error_code="S001", category="Structural", severity="Reject",
            confidence="high", description="Empty query", is_fatal=True,
        )
        r.total_rules_triggered = 1
        r.add_result(result)
        assert r.fatal is True
        assert r.fatal_rejection is not None

    def test_metrics_computation(self):
        r = OptimizationReport()
        r.total_rules_checked = 5
        r.total_rules_triggered = 4
        r.fixes_applied = [{"error_code": "M001"}]
        r.fixes_applied = [{"error_code": "M001"}, {"error_code": "F001"}]
        r.warnings_issued = [{"error_code": "F003"}]
        r.rejections = [{"error_code": "M004"}]
        r.finalize(elapsed_ms=42)
        assert r.fix_rate == 2 / 4
        assert r.warning_rate == 1 / 4
        assert r.rejection_rate == 1 / 4
        assert r.elapsed_ms == 42

    def test_json_serialization(self):
        r = OptimizationReport(query_id="q_001")
        r.total_rules_checked = 3
        r.total_rules_triggered = 1
        r.finalize(elapsed_ms=10)
        json_str = r.to_json()
        assert '"report_id"' in json_str
        assert '"query_id": "q_001"' in json_str
        assert '"elapsed_ms": 10' in json_str

    def test_diff_computation(self):
        r = OptimizationReport()
        r.dsl_before = {"data_source": "", "limit": 100}
        r.dsl_after = {"data_source": "orders", "limit": 50}
        r.compute_diff()
        assert len(r.diff) == 2
        assert any("data_source" in d for d in r.diff)
```

- [ ] **Step 5: Run all P0 tests**

```bash
cd D:/demo/db-gpt/NL2DSL && python -m pytest tests/unit/optimizer/ -v --tb=short
```

Expected: All tests pass (approximately 22 tests).

### Task 0.9: Git commit for P0

- [ ] **Commit P0**

```bash
cd D:/demo/db-gpt/NL2DSL && git add nl2dsl/optimizer/ tests/unit/optimizer/ && git commit -m "feat(optimizer): P0 infrastructure — Rule Engine skeleton

- SemanticConfig: typed wrapper around semantic layer YAML config
- Normalizer: structural DSL normalization (no semantic deps)
- BaseRule + RuleResult: abstract rule interface
- RuleMetadata: registration metadata with priority/severity/confidence
- RuleRegistry: decorator-based rule registration and querying
- RuleEngine: priority-ordered pipeline with Fatal/Normal Reject
- OptimizationReport: structured optimization report with JSON export
- S001/S002: structural blocking rules (empty query, missing data source)
- optimize(): public entry point (normalize → engine pipeline)
- 22 unit tests covering Normalizer, Registry, Engine, Report"
```

---

## Phase 1: Core Rules (P1 Block + P2 Identity)

**Goal:** 7 rules for deterministic corrections and structural blocking.

### Task 1.1: I001 — Unknown DataSource

**Files:**
- Create: `nl2dsl/optimizer/rules/intent.py`
- Create: `tests/unit/optimizer/rules/test_intent.py`

Rule logic:
- `check()`: Look up `dsl["data_source"]` in `context.semantic_config.data_sources`. If not found → Fatal Reject.
- No `fix()` (Fatal Reject, no auto-fix possible).

### Task 1.2: M001 — Wrong Aggregation Function

**Files:**
- Modify: `nl2dsl/optimizer/rules/metric.py` (create)

Rule logic:
- `check()`: For each metric with an alias registered in `semantic_config.metrics`, compare `func` with `semantic_config.get_metric_func(alias)`. If mismatch → Fix.
- `fix()`: Replace `func` in the metric dict with the registered value. Set `location` to `metrics[i].func`.

### Task 1.3: M003 — Missing Alias

**Files:**
- Modify: `nl2dsl/optimizer/rules/metric.py`

Rule logic:
- `check()`: For each metric without an alias, trigger Fix.
- `fix()`: Generate alias as `{func}_{field}` (e.g., `sum_amount`).

### Task 1.4: D003 — Redundant Dimension

**Files:**
- Modify: `nl2dsl/optimizer/rules/dimension.py` (create)

Rule logic:
- `check()`: If dimensions list has duplicates → Fix.
- `fix()`: Deduplicate, keeping first occurrence.

### Task 1.5: F002 — Operator-Type Mismatch

**Files:**
- Modify: `nl2dsl/optimizer/rules/filter.py` (create)

Rule logic:
- `check()`: For each filter, check operator vs. field type:
  - `LIKE` on INTEGER → Fix (`LIKE` → `=`)
  - `>` on BOOLEAN → Fix (`>` → `=`)
  - `BETWEEN` on non-numeric → Warn
- `fix()`: Replace operator with compatible one.

### Task 1.6: Write P1 tests

**Files:**
- Create: `tests/unit/optimizer/rules/__init__.py`
- Create: `tests/unit/optimizer/rules/test_structural.py`
- Create: `tests/unit/optimizer/rules/test_metric.py`
- Create: `tests/unit/optimizer/rules/test_dimension.py`
- Create: `tests/unit/optimizer/rules/test_filter.py`

Each test file: ≥3 test cases per rule (triggers, does not trigger, fix correctness).

### Task 1.7: Update __init__.py to import all P1 rules

**Files:**
- Modify: `nl2dsl/optimizer/__init__.py`

Add imports:
```python
from nl2dsl.optimizer.rules import intent     # noqa: F401
from nl2dsl.optimizer.rules import metric     # noqa: F401
from nl2dsl.optimizer.rules import dimension  # noqa: F401
from nl2dsl.optimizer.rules import filter as _filter_rules  # noqa: F401
```

### Task 1.8: Integration test — multiple P1+P2 rules on one DSL

**Files:**
- Create: `tests/unit/optimizer/test_integration.py`

Test: A DSL with M001 (wrong func) + F002 (LIKE on numeric) → both rules execute and both fixes applied.

### Task 1.9: Commit P1

```bash
git add nl2dsl/optimizer/rules/ tests/unit/optimizer/rules/ tests/unit/optimizer/test_integration.py nl2dsl/optimizer/__init__.py
git commit -m "feat(optimizer): P1 core rules — S001, S002, I001, M001, M003, D003, F002"
```

---

## Phase 2: Extended Rules (P3 Consistency + P4 Auth)

**Goal:** 6 rules — M004, I002, D002, F001, G001, G002.

### Task 2.1: M004 — Metric-DataSource Mismatch

Check if metric's registered data sources contain the DSL's data_source. Reject if not.

### Task 2.2: I002 — DataSource-Only Metric

If no metric belongs to current data_source, find the correct one. Fix if unique, Reject if ambiguous.

### Task 2.3: D002 — Dimension Not In DataSource

Check each dimension against the data_source's dimension list. Reject if not reachable.

### Task 2.4: F001 — Invalid Enum Value

Fuzzy match filter values against dimension value_maps:
1. Exact → high confidence
2. Prefix → high confidence
3. Edit distance ≤ 1 → high confidence
4. Edit distance ≤ 2 → medium confidence
5. No match → Warn (low confidence)

### Task 2.5: G001 — Sensitive Field Access

Check if any requested field is in `permission_config.sensitive_fields`. Fatal Reject if no masking rule.

### Task 2.6: G002 — Metric Not Authorized

Check `user_role` against `permission_config.metric_permissions`. Fatal Reject if unauthorized.

### Task 2.7: Write P2 tests and commit

---

## Phase 3: Advisory Rules (P5 Completeness + P6 Ambiguity)

**Goal:** 13 rules — M002, D001, F003, F004, F005, P001, P002, P003, P004, T001, T002, A001, A002.

Key algorithms:

**P001 JOIN path derivation:**
1. Collect all tables from metrics and dimensions
2. If >1 table and DSL lacks JOIN, check JOIN path graph from data_source
3. Unique path → Fix (inject JOIN)
4. Multiple paths → Warn (list candidates)

**A001/A002 Ambiguity detection:**
1. For each metric/dimension, do fuzzy name match against registry
2. Also check description keyword overlap and synonyms (if available)
3. ≥2 candidates → Reject + clarification_required + candidate list

**T002 Time context detection:**
1. Keyword match against original_question: "同比", "环比", "去年同期", "对比"
2. If found but DSL has no comparison info → Reject + Clarify

### Task 3.1-3.13: Implement each rule with tests

### Task 3.14: Full 6-level priority integration test

Test a DSL that triggers rules at P1, P2, P3, P4, P5, P6 — verify execution order and Fatal Reject stop.

---

## Phase 4: Evaluation Integration

**Goal:** Connect optimizer to the Evaluation Framework. CLI flags, Baseline vs Optimizer comparison, new scoring dimensions.

### Task 4.1: CLI extensions

**Files:**
- Modify: `nl2dsl/evaluation/v2_cli.py`

Add arguments: `--optimizer`, `--compare`, `--rules`, `--disable-rules`, `--verbose-optimizer`.

### Task 4.2: Runner dual-path

**Files:**
- Modify: `nl2dsl/evaluation/v2_runner.py`

Add `run_with_optimizer()` method that wraps the existing query pipeline with `optimize()`.

### Task 4.3: Report extensions

**Files:**
- Modify: `nl2dsl/evaluation/v2_reporter.py`

Add Optimization category with 3 dimensions: Rule Fix Rate (5%), Rule Coverage (3%), Optimization Gain (5%).

### Task 4.4: Comparison report

When `--compare` is used, run both Baseline and Optimizer paths and output side-by-side report with deltas.

### Task 4.5: Tests and commit

---

## Phase 5: Documentation

**Goal:** Usage guide, contribution guide, CLAUDE.md sync.

### Task 5.1: Optimizer usage guide

**Files:**
- Create: `docs/evaluation/optimizer-guide.md`

### Task 5.2: Rule contribution guide

**Files:**
- Create: `docs/specs/semantic-optimizer-contributing.md`

### Task 5.3: Update CLAUDE.md

Add optimizer entries to Task Routing Rules and Engineering Rules.

### Task 5.4: Final commit

---

## Dependency Graph

```
P0 (infrastructure)
  │
  ▼
P1 (core rules: 7 rules)
  │
  ├──────► P2 (extended rules: 6 rules)
  │           │
  │           ▼
  │        P3 (advisory rules: 13 rules)
  │           │
  └───────────┴──────► P4 (evaluation integration)
                           │
                           ▼
                        P5 (documentation)
```

- P1 and P2 rule-writing can partially overlap (different files, no code deps)
- P4 requires P0-P3 completion
- P5 requires P4 completion (needs real data for docs)

---

## Risk Mitigation Checklist

- [ ] Reuse `nl2dsl/semantic/` config loading — do NOT duplicate
- [ ] F001 edit distance threshold set conservatively (≤2)
- [ ] P001 V1: single-path JOIN only; multi-path → Warn
- [ ] Performance benchmark in P0: verify < 20ms for full rule set
- [ ] Clarify division of labor with existing `correct_dsl` graph node

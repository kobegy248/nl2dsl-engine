"""真实评测执行模型。

Phase 0：用真实查询链路产出统一的 :class:`EvaluationObservation`，
取代过去从测试用例 ``expected`` 构造 actual DSL 的做法。

核心组件
--------
- :class:`EvaluationObservation`：单次真实运行的观测对象。
- :class:`EvaluationExecutor`：执行协议（Protocol）。
- :class:`ExecutorConfig`：构建真实 App 所需的依赖集合。
- :class:`ApiEvaluationExecutor`：通过 FastAPI TestClient 调用真实 API 的执行器。
- :class:`FakeEvaluationExecutor`：测试用固定 Observation 执行器。

设计约束
--------
- 严禁从 ``expected`` 构造 actual DSL。
- ``llm`` 模式下若没有可用 LLM Client，返回 ``unavailable``，不静默退化到规则生成。
- 每个矩阵组合（generator × optimizer）独立构建执行环境，避免共享 sticky 状态。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Protocol, runtime_checkable

from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.execution")


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


@dataclass
class EvaluationObservation:
    """单次真实查询运行的观测结果。

    评分器只读取 :attr:`dsl_after_optimizer`（最终 DSL）与治理信息；
    ``status`` 不是 success/warning 时，评分按 0 处理且不计为通过。
    """

    case_id: str
    domain: str
    generator_mode: str           # rule | llm
    optimizer_enabled: bool
    status: str                   # success | warning | clarification | error | unavailable
    query_id: str | None = None
    dsl_before_optimizer: dict | None = None
    dsl_after_optimizer: dict | None = None
    sql: str | None = None
    data: list[dict] | None = None
    trace: list[dict] = field(default_factory=list)
    error: str | None = None
    execution_time_ms: int = 0
    # 该次运行对应领域的治理注入过滤条件（tenant_id + 行级权限），
    # 评分前从 actual DSL 剥离。多领域评测下每个领域不同。
    injected_filters: list[dict] = field(default_factory=list)

    @property
    def final_dsl(self) -> dict:
        """评分使用的最终 DSL（优化后优先，否则优化前）。"""
        return self.dsl_after_optimizer or self.dsl_before_optimizer or {}

    @property
    def is_runnable_status(self) -> bool:
        """是否为可评分的成功路径状态。"""
        return self.status in ("success", "warning")

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Executor protocol & config
# ---------------------------------------------------------------------------


@runtime_checkable
class EvaluationExecutor(Protocol):
    """执行单个测试用例的真实查询链路。"""

    def execute(
        self,
        case: Any,
        *,
        generator_mode: str,
        optimizer_enabled: bool,
    ) -> EvaluationObservation:
        ...


@dataclass
class DomainAppConfig:
    """单个业务领域的执行环境配置（多领域评测使用）。

    每个领域拥有独立的 registry / engine / 权限，避免跨领域共享错误的语义注册表。
    """

    domain: str
    engine: Any                       # SQLAlchemy Engine
    registry_dict: dict
    permissions: dict = field(default_factory=dict)
    sensitive_columns: dict = field(default_factory=dict)
    masking_rules: dict = field(default_factory=dict)
    eval_user_id: str = "u001"
    eval_tenant_id: str = "t001"


@dataclass
class ExecutorConfig:
    """构建真实 App 所需的依赖集合。

    支持两种用法：

    1. 单领域（兼容）：提供 ``engine`` / ``registry_dict`` / ``permissions`` 等扁平字段，
       代表 ``default_domain``（默认 ecommerce）一个领域。
    2. 多领域：提供 ``domains: dict[str, DomainAppConfig]``，每个业务领域独立配置；
       用例按 ``case.domain`` 路由到对应领域，未知领域返回 error（不静默回退 ecommerce）。
    """

    engine: Any = None
    registry_dict: dict | None = None
    permissions: dict = field(default_factory=dict)
    sensitive_columns: dict = field(default_factory=dict)
    masking_rules: dict = field(default_factory=dict)
    llm_client: Any = None
    enable_clarification: bool = False
    eval_user_id: str = "u001"
    eval_tenant_id: str = "t001"
    # 单领域模式下该配置服务的业务领域（默认 ecommerce）。
    default_domain: str = "ecommerce"
    # 多领域配置：domain -> DomainAppConfig。
    domains: dict[str, DomainAppConfig] | None = None

    def get_domain_config(self, domain: str) -> DomainAppConfig | None:
        """返回指定领域的配置；未知领域返回 None（由执行器返回 error）。"""
        if self.domains:
            return self.domains.get(domain)
        # 单领域模式：仅服务 default_domain。
        if domain == self.default_domain:
            return DomainAppConfig(
                domain=self.default_domain,
                engine=self.engine,
                registry_dict=self.registry_dict or {},
                permissions=self.permissions,
                sensitive_columns=self.sensitive_columns,
                masking_rules=self.masking_rules,
                eval_user_id=self.eval_user_id,
                eval_tenant_id=self.eval_tenant_id,
            )
        return None

    def injected_filters_for(self, domain: str) -> list[dict]:
        """返回指定领域评测身份对应的治理注入过滤条件。"""
        dc = self.get_domain_config(domain)
        if dc is None:
            return []
        user_cfg = (dc.permissions or {}).get(dc.eval_user_id) or {}
        injected: list[dict] = [{"field": "tenant_id", "operator": "=", "value": dc.eval_tenant_id}]
        row_filters = user_cfg.get("row_filters") or {}
        for fld, spec in row_filters.items():
            if isinstance(spec, dict) and spec:
                injected.append({
                    "field": fld,
                    "operator": spec.get("operator", "="),
                    "value": spec.get("value"),
                })
        return injected

    @property
    def injected_filters(self) -> list[dict]:
        """兼容：返回 default_domain 的注入过滤条件。"""
        return self.injected_filters_for(self.default_domain)


# ---------------------------------------------------------------------------
# API executor
# ---------------------------------------------------------------------------


def _map_http_status(status_code: int, body_status: str | None) -> str:
    """将 HTTP 响应状态映射为 Observation 状态。"""
    if status_code == 200:
        return body_status or "success"
    if body_status == "clarification":
        return "clarification"
    return "error"


class ApiEvaluationExecutor:
    """通过 FastAPI TestClient 调用真实 ``/api/v1/query`` 的执行器。

    - ``rule`` 模式：构建 App 时强制 ``llm_client=None``，使用规则生成器。
    - ``llm`` 模式：必须提供 ``llm_client``，否则直接返回 ``unavailable``，
      绝不静默退化到规则生成。
    - optimizer 开关通过 ``create_app(enable_optimizer=...)`` 显式控制，
      OFF 时图中不注册 ``optimize_dsl`` 节点。
    - 每个业务领域独立构建 App（``app_domain``），按 ``case.domain`` 路由；
      未知领域返回 error，不静默回退 ecommerce。
    """

    def __init__(self, config: ExecutorConfig):
        self._config = config
        # 每个 (domain, generator, optimizer) 组合独立构建，缓存以避免重复编译图。
        self._client_cache: dict[tuple[str, str, bool], Any] = {}

    @property
    def injected_filters(self) -> list[dict]:
        """兼容：返回 default_domain 的注入过滤条件。"""
        return self._config.injected_filters

    def _build_client(self, domain: str, dc: DomainAppConfig, generator_mode: str, optimizer_enabled: bool):
        from fastapi.testclient import TestClient

        from nl2dsl.api_factory import create_app

        key = (domain, generator_mode, optimizer_enabled)
        cached = self._client_cache.get(key)
        if cached is not None:
            return cached

        # rule 模式强制不使用 LLM；llm 模式使用配置中的 client（由 execute 保证非 None）。
        llm_client = None if generator_mode == "rule" else self._config.llm_client

        app = create_app(
            engine=dc.engine,
            registry_dict=dc.registry_dict,
            permissions=dc.permissions,
            sensitive_columns=dc.sensitive_columns,
            masking_rules=dc.masking_rules,
            enable_clarification=self._config.enable_clarification,
            llm_client=llm_client,
            generator_mode=generator_mode,
            enable_optimizer=optimizer_enabled,
            app_domain=domain,
        )
        client = TestClient(app)
        self._client_cache[key] = client
        return client

    def execute(
        self,
        case: Any,
        *,
        generator_mode: str,
        optimizer_enabled: bool,
    ) -> EvaluationObservation:
        domain = getattr(case, "domain", "ecommerce") or "ecommerce"
        base = dict(
            case_id=case.id,
            domain=domain,
            generator_mode=generator_mode,
            optimizer_enabled=optimizer_enabled,
            injected_filters=self._config.injected_filters_for(domain),
        )

        # 未知 / 未配置领域：明确失败，不静默回退 ecommerce。
        dc = self._config.get_domain_config(domain)
        if dc is None:
            return EvaluationObservation(
                status="error",
                error=f"未配置的业务领域：domain={domain}（评测执行器拒绝静默回退 ecommerce）",
                **base,
            )

        # llm 模式无可用 Client → unavailable，不静默 fallback。
        if generator_mode == "llm" and self._config.llm_client is None:
            return EvaluationObservation(
                status="unavailable",
                error="LLM client not available for llm generator mode",
                **base,
            )

        start = time.time()
        client = self._build_client(domain, dc, generator_mode, optimizer_enabled)

        try:
            resp = client.post(
                "/api/v1/query",
                json={
                    "question": case.query,
                    "user_id": dc.eval_user_id,
                    "tenant_id": dc.eval_tenant_id,
                    "domain": domain,
                },
            )
        except Exception as exc:  # 网络层 / App 启动异常
            logger.error("[%s] API 调用异常：%s", case.id, exc)
            return EvaluationObservation(
                status="error",
                error=str(exc),
                execution_time_ms=int((time.time() - start) * 1000),
                **base,
            )

        elapsed = int((time.time() - start) * 1000)
        try:
            body = resp.json()
        except Exception:
            body = {}

        status = _map_http_status(resp.status_code, body.get("status"))
        query_id = body.get("query_id")
        dsl = body.get("dsl")
        sql = body.get("sql")
        data = body.get("data")
        error = body.get("message") or body.get("error") if status == "error" else None

        # 从审计日志取 Trace（真实链路轨迹），不依赖响应体是否暴露 trace。
        # 详情接口要求 tenant_id（租户隔离），传入该领域的评测租户。
        trace: list[dict] = []
        if query_id:
            try:
                detail = client.get(
                    f"/api/v1/admin/audit/queries/{query_id}",
                    params={"tenant_id": dc.eval_tenant_id},
                )
                if detail.status_code == 200:
                    item = detail.json().get("item", {}) or {}
                    trace = item.get("trace") or []
                    # 审计中的 dsl/sql 是治理后最终结果，作为权威来源补全。
                    if not dsl and item.get("dsl"):
                        dsl = item["dsl"]
                    if not sql and item.get("sql"):
                        sql = item["sql"]
            except Exception as exc:
                logger.warning("[%s] 读取审计 trace 失败：%s", case.id, exc)

        return EvaluationObservation(
            status=status,
            query_id=query_id,
            dsl_after_optimizer=dsl,
            sql=sql,
            data=data,
            trace=trace,
            error=error,
            execution_time_ms=elapsed,
            **base,
        )


class FakeEvaluationExecutor:
    """测试用执行器：按预设映射返回固定 Observation。

    用法：``FakeEvaluationExecutor({case_id: EvaluationObservation(...)})`` 或
    传入一个返回 Observation 的 callable。
    """

    def __init__(
        self,
        mapping: dict[str, EvaluationObservation] | Any | None = None,
        default: EvaluationObservation | None = None,
    ):
        self._mapping = mapping or {}
        self._default = default

    def execute(self, case, *, generator_mode, optimizer_enabled) -> EvaluationObservation:
        if isinstance(self._mapping, dict):
            obs = self._mapping.get(case.id)
            if obs is not None:
                return obs
        elif callable(self._mapping):
            return self._mapping(case, generator_mode=generator_mode, optimizer_enabled=optimizer_enabled)
        if self._default is not None:
            return self._default
        return EvaluationObservation(
            case_id=case.id,
            domain=getattr(case, "domain", "ecommerce"),
            generator_mode=generator_mode,
            optimizer_enabled=optimizer_enabled,
            status="success",
            dsl_after_optimizer={},
        )

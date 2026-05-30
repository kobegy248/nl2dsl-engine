"""Plan node: intent classification + task decomposition for NL2DSL agent.

The planner analyzes a user's natural language question and produces a Plan
containing:
1. Intent classification (compare, trend, correlation, single_query)
2. Task decomposition into SubQuery objects
3. Reasoning explaining the plan

When an LLM client is available, the planner uses it for richer planning.
Otherwise it falls back to keyword-based classification and rule-based
decomposition.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from nl2dsl.agent.models import Plan, SubQuery
from nl2dsl.agent.strategies import IntentRegistry
from nl2dsl.graph.state import QueryState
from nl2dsl.utils.logger import get_logger

logger = get_logger("agent.planner")

# ---------------------------------------------------------------------------
# Intent classification keywords (kept for backward compatibility)
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS = {
    "compare": [
        "对比", "比较", "同比", "环比", "和...比", "vs", "VS", "相比",
    ],
    "trend": [
        "趋势", "走势", "变化", "增长", "下降",
    ],
    "correlation": [
        "关联", "影响", "相关", "关系", "取决于",
    ],
}

# Order matters: earlier intents take priority
_INTENT_PRIORITY = ("compare", "trend", "correlation")

# Splitters used for decomposing compare / correlation questions
_SPLIT_CHARS = ("和", "与", "vs", "VS")


# ---------------------------------------------------------------------------
# Public API (backward-compatible free functions)
# ---------------------------------------------------------------------------


def classify_intent(question: str) -> str:
    """Classify user intent based on keyword matching.

    Args:
        question: The user's natural language question.

    Returns:
        One of: "compare", "trend", "correlation", "single_query".
    """
    for intent in _INTENT_PRIORITY:
        if any(kw in question for kw in _INTENT_KEYWORDS[intent]):
            return intent
    return "single_query"


def _split_question(question: str) -> list[str]:
    """Split a question by comparison/correlation splitters.

    Returns a list of non-empty parts. Falls back to [question] if no
    splitter is found.
    """
    # Build a regex that matches any of the split characters
    pattern = "|".join(re.escape(ch) for ch in _SPLIT_CHARS)
    parts = [p.strip() for p in re.split(pattern, question) if p.strip()]
    return parts if parts else [question]


def _decompose_by_intent(
    question: str,
    intent: str,
    intents: IntentRegistry,
) -> Plan:
    """Create a Plan using the intent registry configuration.

    Args:
        question: The user's question.
        intent: The classified intent.
        intents: IntentRegistry with decomposition strategies.

    Returns:
        A Plan with sub-queries derived from the intent config.
    """
    sub_queries: list[SubQuery] = []

    # Look up decomposition strategy from registry
    config = intents.intents.get(intent)
    decomposition = config.decomposition if config else "passthrough"

    if decomposition == "split_by_objects":
        parts = _split_question(question)
        if len(parts) >= 2:
            sub_queries = [
                SubQuery(id="sq-1", description=parts[0], depends_on=[]),
                SubQuery(id="sq-2", description=parts[1], depends_on=[]),
            ]
        else:
            sub_queries = [SubQuery(id="sq-1", description=question, depends_on=[])]

    elif decomposition == "single_with_time_grouping":
        sub_queries = [
            SubQuery(
                id="sq-1",
                description=f"{question}（按时间分组）",
                depends_on=[],
            ),
        ]

    elif decomposition == "total_plus_groups":
        sub_queries = [
            SubQuery(id="sq-1", description=f"{question}（总计）", depends_on=[]),
            SubQuery(id="sq-2", description=f"{question}（分组明细）", depends_on=[]),
        ]

    elif decomposition == "single_with_ordering":
        sub_queries = [
            SubQuery(
                id="sq-1",
                description=f"{question}（按排序）",
                depends_on=[],
            ),
        ]

    else:  # passthrough or unknown
        sub_queries = [SubQuery(id="sq-1", description=question, depends_on=[])]

    reasoning = (
        f"基于意图配置 '{intent}'（分解策略: {decomposition}），"
        f"将问题分解为 {len(sub_queries)} 个子查询。"
    )

    return Plan(
        intent=intent,
        sub_queries=sub_queries,
        reasoning=reasoning,
    )


def _decompose_fallback(question: str, intent: str) -> Plan:
    """Create a Plan using rule-based decomposition (no LLM).

    This is a backward-compatible wrapper that delegates to
    _decompose_by_intent with a default IntentRegistry.

    Args:
        question: The user's question.
        intent: The classified intent.

    Returns:
        A Plan with sub-queries derived from the intent.
    """
    # For backward compatibility, use the old hardcoded logic
    # when no registry is available, but delegate to _decompose_by_intent
    # when a registry is present.
    sub_queries: list[SubQuery] = []

    if intent == "compare":
        parts = _split_question(question)
        if len(parts) >= 2:
            sub_queries = [
                SubQuery(id="sq-1", description=parts[0], depends_on=[]),
                SubQuery(id="sq-2", description=parts[1], depends_on=[]),
            ]
        else:
            sub_queries = [SubQuery(id="sq-1", description=question, depends_on=[])]

    elif intent == "trend":
        sub_queries = [
            SubQuery(
                id="sq-1",
                description=f"{question}（按时间分组）",
                depends_on=[],
            ),
        ]

    elif intent == "correlation":
        parts = _split_question(question)
        if len(parts) >= 2:
            sub_queries = [
                SubQuery(id="sq-1", description=parts[0], depends_on=[]),
                SubQuery(id="sq-2", description=parts[1], depends_on=[]),
            ]
        else:
            sub_queries = [SubQuery(id="sq-1", description=question, depends_on=[])]

    else:  # single_query or unknown
        sub_queries = [SubQuery(id="sq-1", description=question, depends_on=[])]

    reasoning = (
        f"基于关键词识别为 '{intent}' 意图，"
        f"将问题分解为 {len(sub_queries)} 个子查询。"
    )

    return Plan(
        intent=intent,
        sub_queries=sub_queries,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Planner class (config-driven + LLM-based)
# ---------------------------------------------------------------------------


class Planner:
    """Config-driven planner with LLM support and rule-based fallback.

    The Planner classifies user intent and decomposes questions into
    executable sub-queries. It uses an :class:`IntentRegistry` loaded
    from ``configs/intents.yaml`` by default, and can optionally use an
    LLM client for richer planning.

    Args:
        llm_client: Optional LLM client with an ``agenerate`` or
            ``generate`` method. If provided, the planner tries LLM-based
            planning first and falls back to rules on failure.
        intents: Optional :class:`IntentRegistry` instance. Defaults to
            loading from ``configs/intents.yaml``.
    """

    def __init__(
        self,
        llm_client=None,
        intents: IntentRegistry | None = None,
    ):
        self._llm = llm_client
        self._intents = intents or IntentRegistry.load("configs/intents.yaml")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_by_keywords(self, question: str) -> str:
        """Classify intent using the IntentRegistry keywords."""
        matched = self._intents.get_intent_by_keywords(question)
        return matched or "single_query"

    def _rule_based_plan(self, question: str) -> Plan:
        """Create a plan using keyword classification + rule decomposition."""
        intent = self._classify_by_keywords(question)
        return _decompose_by_intent(question, intent, self._intents)

    async def _llm_plan(self, question: str, registry_dict: dict) -> Plan:
        """Create a plan using the LLM client.

        Args:
            question: The user's question.
            registry_dict: Registry containing available metrics and dimensions.

        Returns:
            A Plan parsed from the LLM response.

        Raises:
            Exception: If the LLM call fails or returns invalid data.
        """
        prompt = _build_plan_prompt(question, registry_dict)
        system_prompt = (
            "你是一个数据分析意图识别助手。只输出 JSON，不要 markdown 代码块标记。"
        )

        # Try async generate first, then sync fallback
        if getattr(self._llm, "agenerate", None) is not None:
            raw = await self._llm.agenerate(prompt, system_prompt)
        elif getattr(self._llm, "generate", None) is not None:
            raw = self._llm.generate(prompt, system_prompt)
        else:
            raise TypeError(
                f"LLM client has no generate/agenerate method: {type(self._llm)}"
            )

        if not raw:
            raise ValueError("LLM returned empty response")

        return _parse_llm_plan(raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan(
        self,
        question: str,
        registry_dict: dict | None = None,
    ) -> Plan:
        """Create an execution plan for the given question.

        Tries LLM-based planning first (if an LLM client is available),
        and falls back to rule-based planning on any failure.

        Args:
            question: The user's natural language question.
            registry_dict: Optional registry of available metrics/dimensions
                for the LLM prompt.

        Returns:
            A :class:`Plan` with intent, sub-queries, and reasoning.
        """
        if self._llm is not None:
            try:
                plan = await self._llm_plan(
                    question, registry_dict or {}
                )
                logger.info(
                    "[plan] LLM plan: intent=%s, sub_queries=%d",
                    plan.intent,
                    len(plan.sub_queries),
                )
                return plan
            except Exception as exc:
                logger.warning(
                    "[plan] LLM call failed, falling back: %s", exc
                )
                return self._rule_based_plan(question)

        return self._rule_based_plan(question)


# ---------------------------------------------------------------------------
# LLM prompt / parse helpers
# ---------------------------------------------------------------------------


def _build_plan_prompt(question: str, registry_dict: dict) -> str:
    """Build the LLM prompt for plan generation.

    Args:
        question: The user's question.
        registry_dict: Registry containing available metrics and dimensions.

    Returns:
        A prompt string for the LLM.
    """
    metrics = registry_dict.get("metrics", {})
    dimensions = registry_dict.get("dimensions", {})

    metrics_lines = []
    for alias, info in metrics.items():
        desc = info.get("description", "") if isinstance(info, dict) else ""
        metrics_lines.append(f"- {alias}: {desc}")

    dimensions_lines = []
    for alias, info in dimensions.items():
        desc = info.get("description", "") if isinstance(info, dict) else ""
        dimensions_lines.append(f"- {alias}: {desc}")

    metrics_text = "\n".join(metrics_lines) if metrics_lines else "（无）"
    dimensions_text = "\n".join(dimensions_lines) if dimensions_lines else "（无）"

    return f"""你是一个智能数据分析助手。请分析用户的自然语言查询，识别其意图并将查询分解为可执行的子任务。

【用户问题】
{question}

【可用指标】
{metrics_text}

【可用维度】
{dimensions_text}

【任务】
1. 识别用户意图（compare/trend/correlation/single_query 之一）
2. 将查询分解为子查询列表
3. 解释你的推理过程

【输出格式】
只输出 JSON，不要解释文字：
{{
  "intent": "compare",
  "sub_queries": [
    {{"id": "sq-1", "description": "...", "depends_on": []}},
    {{"id": "sq-2", "description": "...", "depends_on": []}}
  ],
  "reasoning": "...",
  "requires_approval": false
}}

规则：
- compare: 对比/比较类问题，拆分为 2+ 子查询
- trend: 趋势/走势类问题，1 个子查询（按时间维度分组）
- correlation: 关联/影响类问题，拆分为 2+ 子查询
- single_query: 简单查询，1 个子查询
- depends_on: 如果子查询依赖其他子查询的结果，填写依赖的 id 列表
- requires_approval: 如果涉及敏感操作（如删除数据），设为 true"""


def _parse_llm_plan(raw: str) -> Plan:
    """Parse LLM response into a Plan object.

    Supports JSON wrapped in markdown code blocks.

    Args:
        raw: The raw LLM response string.

    Returns:
        A Plan object.

    Raises:
        json.JSONDecodeError: If the response cannot be parsed as JSON.
        KeyError: If required fields are missing.
    """
    text = raw.strip()

    # Try markdown code block first
    fence_match = re.search(r"```(?:json)?\s*\n(\{[\s\S]*?\})\s*\n```", text)
    if fence_match:
        data = json.loads(fence_match.group(1))
    else:
        # Fallback: find first { to last }
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start:end + 1])
        else:
            data = json.loads(text)

    sub_queries = [
        SubQuery(
            id=sq.get("id", f"sq-{i + 1}"),
            description=sq.get("description", ""),
            depends_on=sq.get("depends_on", []),
            dsl=sq.get("dsl"),
        )
        for i, sq in enumerate(data.get("sub_queries", []))
    ]

    return Plan(
        intent=data.get("intent", "single_query"),
        sub_queries=sub_queries,
        reasoning=data.get("reasoning", ""),
        requires_approval=data.get("requires_approval", False),
    )


# ---------------------------------------------------------------------------
# LangGraph node factory (backward compatible)
# ---------------------------------------------------------------------------


def _make_plan_node(
    llm_client,
    registry_dict: dict,
) -> Callable[[QueryState], dict]:
    """Factory that creates the plan graph node.

    Args:
        llm_client: LLM client with a ``generate(prompt, system_prompt)`` method,
            or None to use fallback classification.
        registry_dict: Dictionary of available metrics/dimensions for the LLM prompt.

    Returns:
        A node function suitable for use in a LangGraph pipeline.
    """
    # Import here to avoid circular dependency at module load time
    from nl2dsl.graph.nodes import with_error_handler

    @with_error_handler("plan")
    def plan_node(state: QueryState) -> dict:
        # If a plan is already present (e.g., from API layer pre-planning), skip.
        existing_plan = state.get("plan")
        if existing_plan is not None:
            return {
                "plan": existing_plan,
                "trace": {
                    "step": "plan",
                    "status": "skipped",
                    "reason": "plan_already_present",
                    "intent": existing_plan.intent,
                },
            }

        question = state["question"]

        # Try LLM path first
        if llm_client is not None:
            try:
                prompt = _build_plan_prompt(question, registry_dict)
                raw = llm_client.generate(
                    prompt,
                    "你是一个数据分析意图识别助手。只输出 JSON，不要 markdown 代码块标记。",
                )
                if raw:
                    plan = _parse_llm_plan(raw)
                    logger.info(
                        "[plan] LLM plan: intent=%s, sub_queries=%d",
                        plan.intent,
                        len(plan.sub_queries),
                    )
                    return {
                        "plan": plan,
                        "trace": {
                            "step": "plan",
                            "status": "success",
                            "source": "llm",
                            "intent": plan.intent,
                            "sub_queries_count": len(plan.sub_queries),
                        },
                    }
            except json.JSONDecodeError as exc:
                logger.warning("[plan] LLM returned invalid JSON, falling back: %s", exc)
            except Exception as exc:
                logger.warning("[plan] LLM call failed, falling back: %s", exc)

        # Fallback: keyword-based classification + rule-based decomposition
        intent = classify_intent(question)
        plan = _decompose_fallback(question, intent)
        logger.info(
            "[plan] Fallback plan: intent=%s, sub_queries=%d",
            plan.intent,
            len(plan.sub_queries),
        )
        return {
            "plan": plan,
            "trace": {
                "step": "plan",
                "status": "success",
                "source": "fallback",
                "intent": plan.intent,
                "sub_queries_count": len(plan.sub_queries),
            },
        }

    return plan_node

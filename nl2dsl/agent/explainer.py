"""Explain node: natural language explanation generation for NL2DSL agent.

The explainer generates concise natural language explanations of query results.
When an LLM client is available, it uses LLM-based generation for richer,
context-aware explanations. Otherwise it falls back to template-based
explanations tailored to the query intent.
"""

from __future__ import annotations

from typing import Callable

from nl2dsl.agent.models import Plan, SubQuery
from nl2dsl.graph.state import QueryState
from nl2dsl.utils.logger import get_logger

logger = get_logger("agent.explainer")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _format_data_summary(data: list[dict], max_rows: int = 3) -> str:
    """Format data rows into a brief summary string.

    Args:
        data: List of data row dictionaries.
        max_rows: Maximum number of rows to show.

    Returns:
        A brief summary string with key=value pairs for each row.
        Returns empty string if data is empty.
    """
    if not data:
        return ""

    rows = []
    for i, row in enumerate(data[:max_rows]):
        pairs = [f"{k}={v}" for k, v in row.items()]
        rows.append(", ".join(pairs))

    summary = "; ".join(rows)
    if len(data) > max_rows:
        summary += f" ...（共{len(data)}条数据）"

    return summary


def _build_explanation_prompt(question: str, plan: Plan, data: list[dict]) -> str:
    """Build the LLM prompt for explanation generation.

    Args:
        question: The user's natural language question.
        plan: The execution plan containing intent and reasoning.
        data: The query result data.

    Returns:
        A prompt string for the LLM.
    """
    data_summary = _format_data_summary(data)
    sub_query_descriptions = [
        f"- {sq.id}: {sq.description}" for sq in plan.sub_queries
    ]
    sub_queries_text = "\n".join(sub_query_descriptions) if sub_query_descriptions else "（无）"

    return f"""你是一个智能数据分析助手。请根据用户的查询问题、执行计划和查询结果，生成一段简洁的自然语言解释。

【用户问题】
{question}

【查询意图】
{plan.intent}

【推理过程】
{plan.reasoning}

【子查询】
{sub_queries_text}

【查询结果】
{data_summary or "（无数据）"}

【要求】
1. 使用第一人称"我"来表述
2. 简洁明了，不超过200字
3. 直接回答用户的问题，说明查询结果
4. 不要包含技术细节（如SQL、DSL等）
5. 如果数据为空，说明未查询到相关数据

请生成解释："""


def _generate_template_explanation(question: str, plan: Plan, data: list[dict]) -> str:
    """Generate a template-based explanation based on intent.

    Args:
        question: The user's natural language question.
        plan: The execution plan containing intent and reasoning.
        data: The query result data.

    Returns:
        A natural language explanation string.
    """
    reasoning = plan.reasoning
    if reasoning and not reasoning.endswith("。"):
        reasoning += "。"

    intent = plan.intent
    data_summary = _format_data_summary(data)

    if intent == "single_query":
        if data_summary:
            return f"您的问题是'{question}'。{reasoning}查询结果为：{data_summary}"
        return f"您的问题是'{question}'。{reasoning}未查询到相关数据。"

    elif intent == "compare":
        sub_query_summaries = []
        for sq in plan.sub_queries:
            # Find data rows that might match this sub-query
            sq_data = [
                row for row in data
                if any(
                    kw in str(row.values()) for kw in sq.description.split()
                )
            ]
            if not sq_data:
                sq_data = data[:1] if data else []
            sq_summary = _format_data_summary(sq_data, max_rows=1)
            if sq_summary:
                sub_query_summaries.append(f"{sq.description}：{sq_summary}")
            else:
                sub_query_summaries.append(sq.description)

        summaries_text = "；".join(sub_query_summaries)
        return f"您的问题是'{question}'。{reasoning}其中，{summaries_text}。"

    elif intent == "trend":
        trend_summary = _compute_trend_summary(data)
        return f"您的问题是'{question}'。{reasoning}{trend_summary}"

    elif intent == "correlation":
        correlation_summary = _compute_correlation_summary(data)
        return f"您的问题是'{question}'。{reasoning}{correlation_summary}"

    # Default fallback
    if data_summary:
        return f"您的问题是'{question}'。{reasoning}查询结果为：{data_summary}"
    return f"您的问题是'{question}'。{reasoning}未查询到相关数据。"


def _compute_trend_summary(data: list[dict]) -> str:
    """Compute a trend summary from time-series data.

    Args:
        data: List of data rows, ideally with time-related columns.

    Returns:
        A brief trend description string.
    """
    if len(data) < 2:
        return "数据点不足，无法判断趋势。"

    # Extract numeric values from rows
    numeric_values = []
    for row in data:
        for val in row.values():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                numeric_values.append(val)
                break

    if len(numeric_values) < 2:
        return "数据点不足，无法判断趋势。"

    first_val = numeric_values[0]
    last_val = numeric_values[-1]

    if last_val > first_val:
        return f"数据呈上升趋势，从{first_val}增长至{last_val}。"
    elif last_val < first_val:
        return f"数据呈下降趋势，从{first_val}下降至{last_val}。"
    else:
        return f"数据基本持平，维持在{first_val}左右。"


def _compute_correlation_summary(data: list[dict]) -> str:
    """Compute a correlation summary from data.

    Args:
        data: List of data rows with at least two numeric columns.

    Returns:
        A brief correlation description string.
    """
    if len(data) < 2:
        return "数据点不足，无法计算相关性。"

    # Extract pairs of numeric values
    pairs = []
    for row in data:
        nums = [v for v in row.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(nums) >= 2:
            pairs.append((nums[0], nums[1]))

    if len(pairs) < 2:
        return "数据点不足，无法计算相关性。"

    # Simple direction check: compare first and last points
    x0, y0 = pairs[0]
    x1, y1 = pairs[-1]

    if x1 > x0 and y1 > y0:
        return "两个指标呈正相关关系，一个增长时另一个也增长。"
    elif x1 > x0 and y1 < y0:
        return "两个指标呈负相关关系，一个增长时另一个下降。"
    elif x1 < x0 and y1 > y0:
        return "两个指标呈负相关关系，一个下降时另一个增长。"
    elif x1 < x0 and y1 < y0:
        return "两个指标呈正相关关系，一个下降时另一个也下降。"
    else:
        return "两个指标的相关性不明显。"


# ---------------------------------------------------------------------------
# Graph node factory
# ---------------------------------------------------------------------------


def _make_explain_node(
    llm_client,
) -> Callable[[QueryState], dict]:
    """Factory that creates the explain graph node.

    Args:
        llm_client: LLM client with a ``generate(prompt, system_prompt)`` method,
            or None to use template-based fallback.

    Returns:
        A node function suitable for use in a LangGraph pipeline.
    """
    # Import here to avoid circular dependency at module load time
    from nl2dsl.graph.nodes import with_error_handler

    @with_error_handler("explain")
    def explain_node(state: QueryState) -> dict:
        question = state["question"]
        plan = state.get("plan")
        data = state.get("data") or []

        # If no plan, create a default single-query plan
        if plan is None:
            plan = Plan(
                intent="single_query",
                sub_queries=[SubQuery(id="sq-1", description=question, depends_on=[])],
                reasoning="直接回答用户问题",
            )
            logger.info("[explain] No plan found, using default single_query plan")

        # Try LLM path first
        if llm_client is not None:
            try:
                prompt = _build_explanation_prompt(question, plan, data)
                raw = llm_client.generate(
                    prompt,
                    "你是一个简洁的数据分析解释助手。用第一人称'我'生成解释，不超过200字。",
                )
                if raw and raw.strip():
                    explanation = raw.strip()
                    logger.info("[explain] LLM explanation generated (len=%d)", len(explanation))
                    return {
                        "explanation": explanation,
                        "trace": {
                            "step": "explain",
                            "status": "success",
                            "source": "llm",
                            "explanation_length": len(explanation),
                        },
                    }
            except Exception as exc:
                logger.warning("[explain] LLM call failed, falling back to template: %s", exc)

        # Fallback: template-based explanation
        explanation = _generate_template_explanation(question, plan, data)
        logger.info(
            "[explain] Template explanation generated (intent=%s, len=%d)",
            plan.intent,
            len(explanation),
        )
        return {
            "explanation": explanation,
            "trace": {
                "step": "explain",
                "status": "success",
                "source": "template",
                "intent": plan.intent,
            },
        }

    return explain_node

"""Confidence node: evaluates DSL quality on three dimensions.

1. Syntax confidence (rule-based): validator.validate(dsl) -> 1.0 or 0.0
2. Semantic confidence (LLM-based): LLM judges if DSL answers the question (0-1)
3. History confidence: MVP always returns 1.0 (no historical tracking yet)

Formula: confidence = min(syntax, semantic) * history

Routing decisions:
- >= 0.8: "continue" — proceed with execution
- 0.6-0.79: "warning" — proceed with warning flag
- < 0.6: "clarify" — route to clarification
"""

from __future__ import annotations

import re
from typing import Callable

from nl2dsl.dsl.validator import DSLValidator
from nl2dsl.exceptions import ValidationError
from nl2dsl.graph.state import QueryState
from nl2dsl.utils.logger import get_logger

logger = get_logger("agent.confidence")


def _evaluate_syntax(validator: DSLValidator, dsl) -> float:
    """Evaluate syntax confidence via validator.

    Returns 1.0 if validation passes, 0.0 if it fails.
    """
    try:
        validator.validate(dsl)
        return 1.0
    except ValidationError:
        return 0.0


def _evaluate_semantic(dsl, question: str, llm_client) -> tuple[float, str]:
    """Evaluate semantic confidence via LLM.

    Ask the LLM to judge if the DSL answers the user's question.
    Returns (score_0_1, source) where source is "llm", "neutral_no_llm",
    or "neutral_fallback".
    """
    if llm_client is None:
        return 0.5, "neutral_no_llm"

    # Serialize DSL safely for the prompt
    try:
        import json

        dsl_json = json.dumps(dsl.model_dump(), ensure_ascii=False, indent=2, default=str)
    except Exception:
        dsl_json = str(dsl)

    prompt = f"""你是一个 DSL 质量评估助手。请判断下面的 DSL 是否能正确回答用户的问题。

【用户问题】
{question}

【DSL】
{dsl_json}

【评分标准】
- 1.0：DSL 完全正确地回答了用户问题
- 0.8-0.99：DSL 基本正确，但可能有 minor 问题
- 0.6-0.79：DSL 部分正确，但缺少某些条件或维度
- 0.4-0.59：DSL 有较大偏差
- 0-0.39：DSL 完全错误，无法回答用户问题

【输出要求】
只输出一个 0-1 的小数分数，不要任何解释文字。"""

    try:
        raw = llm_client.generate(prompt, "你是一个简洁的 DSL 质量评估助手。只输出 0-1 之间的小数分数。")
        if not raw:
            return 0.5, "neutral_fallback"

        # Extract first number (including decimal) from response
        text = raw.strip()
        match = re.search(r"(-?\d+\.?\d*)", text)
        if match:
            score = float(match.group(1))
            score = max(0.0, min(1.0, score))
            return score, "llm"
        return 0.5, "neutral_fallback"
    except Exception as exc:
        logger.warning("[confidence] LLM semantic evaluation failed: %s", exc)
        return 0.5, "neutral_fallback"


def _evaluate_history(_dsl, _question: str, _user_id: str) -> float:
    """Evaluate history confidence.

    MVP: always returns 1.0 (no historical tracking yet).
    """
    return 1.0


def _compute_routing(confidence: float, semantic_source: str = "") -> str:
    """Determine routing decision based on confidence score.

    Returns:
        "continue" if confidence >= 0.8
        "warning" if 0.6 <= confidence < 0.8
        "clarify" if confidence < 0.6 (but not when semantic_source is neutral)
    """
    if confidence >= 0.8:
        return "continue"
    if confidence >= 0.6:
        return "warning"
    # When no LLM is available or LLM call failed, semantic score is neutral;
    # don't block execution since we can't meaningfully evaluate semantics
    if semantic_source in ("neutral_no_llm", "neutral_fallback"):
        return "continue"
    return "clarify"


def _build_explanation(
    confidence: float,
    syntax_score: float,
    semantic_score: float,
    history_score: float,
    routing: str,
) -> str:
    """Build a natural language explanation of the confidence score."""
    parts = [
        f"DSL 质量评分: {confidence * 100:.0f}%",
        f"语法正确性: {syntax_score * 100:.0f}%",
        f"语义匹配度: {semantic_score * 100:.0f}%",
        f"历史可信度: {history_score:.2f}",
    ]

    if routing == "continue":
        parts.append("路由决策: 继续执行（置信度充足）")
    elif routing == "warning":
        parts.append("路由决策: 警告（置信度偏低，建议复核）")
    else:
        parts.append("路由决策: 需要澄清（置信度不足）")

    return "; ".join(parts)


def _make_confidence_node(
    validator: DSLValidator,
    llm_client,
) -> Callable[[QueryState], dict]:
    """Factory that creates the confidence graph node.

    Args:
        validator: DSLValidator instance for syntax checking.
        llm_client: LLM client with a ``generate(prompt, system_prompt)`` method,
            or None to use neutral fallback for semantic scoring.

    Returns:
        A node function suitable for use in a LangGraph pipeline.
    """
    # Import here to avoid circular dependency at module load time
    from nl2dsl.graph.nodes import with_error_handler

    @with_error_handler("confidence")
    def confidence_node(state: QueryState) -> dict:
        dsl = state.get("dsl")
        if dsl is None:
            raise ValidationError("DSL is None, cannot evaluate confidence")

        question = state["question"]
        user_id = state["user_id"]

        # Evaluate three dimensions
        syntax_score = _evaluate_syntax(validator, dsl)
        semantic_score, semantic_source = _evaluate_semantic(dsl, question, llm_client)
        history_score = _evaluate_history(dsl, question, user_id)

        # Formula: confidence = min(syntax, semantic) * history
        confidence = min(syntax_score, semantic_score) * history_score

        # Routing decision
        routing = _compute_routing(confidence, semantic_source)

        # Sub-query downgrade: when this query is a sub-query dispatched by
        # AgentOrchestrator (pre-built plan exists), downgrade "clarify" to
        # "warning" so the sub-query still executes instead of silently failing.
        # This applies to all intent types (single_query, compare, ranking, etc.).
        existing_plan = state.get("plan")
        if routing == "clarify" and existing_plan is not None:
            routing = "warning"
            explanation_suffix = "（子查询模式：置信度不足但继续执行）"
        else:
            explanation_suffix = ""

        # Build explanation
        explanation = _build_explanation(
            confidence, syntax_score, semantic_score, history_score, routing
        ) + explanation_suffix

        # Build result dict
        result: dict = {
            "confidence": confidence,
            "explanation": explanation,
            "trace": {
                "step": "confidence",
                "status": "success",
                "confidence": confidence,
                "routing": routing,
                "details": {
                    "syntax_score": syntax_score,
                    "semantic_score": semantic_score,
                    "semantic_source": semantic_source,
                    "history_score": history_score,
                },
            },
        }

        # Set status based on routing thresholds
        if routing == "warning":
            result["status"] = "warning"
        elif routing == "clarify":
            result["status"] = "clarification"

        return result

    return confidence_node

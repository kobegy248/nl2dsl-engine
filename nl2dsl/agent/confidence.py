"""Confidence node: evaluates DSL quality on three dimensions.

1. Syntax confidence (rule-based): validator.validate(dsl) -> 100.0 or 0.0
2. Semantic confidence (LLM-based): LLM judges if DSL answers the question (0-100)
3. History confidence: MVP always returns 1.0 (no historical tracking yet)

Formula: confidence = min(syntax, semantic) * history

Routing decisions:
- >= 80: "continue" — proceed with execution
- 60-79: "warning" — proceed with warning flag
- < 60: "clarify" — route to clarification
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

    Returns 100.0 if validation passes, 0.0 if it fails.
    """
    try:
        validator.validate(dsl)
        return 100.0
    except ValidationError:
        return 0.0


def _evaluate_semantic(dsl, question: str, llm_client) -> tuple[float, str]:
    """Evaluate semantic confidence via LLM.

    Ask the LLM to judge if the DSL answers the user's question.
    Returns (score, source) where source is "llm", "neutral_no_llm",
    or "neutral_fallback".
    """
    if llm_client is None:
        return 50.0, "neutral_no_llm"

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
- 100 分：DSL 完全正确地回答了用户问题
- 80-99 分：DSL 基本正确，但可能有 minor 问题
- 60-79 分：DSL 部分正确，但缺少某些条件或维度
- 40-59 分：DSL 有较大偏差
- 0-39 分：DSL 完全错误，无法回答用户问题

【输出要求】
只输出一个 0-100 的整数分数，不要任何解释文字。"""

    try:
        raw = llm_client.generate(prompt, "你是一个简洁的 DSL 质量评估助手。只输出数字分数。")
        if not raw:
            return 50.0, "neutral_fallback"

        # Extract first number (including negative) from response
        text = raw.strip()
        match = re.search(r"(-?\d+)", text)
        if match:
            score = int(match.group(1))
            score = max(0.0, min(100.0, float(score)))
            return score, "llm"
        return 50.0, "neutral_fallback"
    except Exception as exc:
        logger.warning("[confidence] LLM semantic evaluation failed: %s", exc)
        return 50.0, "neutral_fallback"


def _evaluate_history(_dsl, _question: str, _user_id: str) -> float:
    """Evaluate history confidence.

    MVP: always returns 1.0 (no historical tracking yet).
    """
    return 1.0


def _compute_routing(confidence: float) -> str:
    """Determine routing decision based on confidence score.

    Returns:
        "continue" if confidence >= 80
        "warning" if 60 <= confidence < 80
        "clarify" if confidence < 60
    """
    if confidence >= 80.0:
        return "continue"
    if confidence >= 60.0:
        return "warning"
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
        f"DSL 质量评分: {confidence:.1f}/100",
        f"语法正确性: {syntax_score:.1f}/100",
        f"语义匹配度: {semantic_score:.1f}/100",
        f"历史可信度: {history_score:.1f}",
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
        routing = _compute_routing(confidence)

        # Build explanation
        explanation = _build_explanation(
            confidence, syntax_score, semantic_score, history_score, routing
        )

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

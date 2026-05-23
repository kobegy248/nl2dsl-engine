from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT, build_user_prompt


def test_system_prompt_contains_rules():
    assert "只输出 JSON" in DSL_SYSTEM_PROMPT
    assert "data_source" in DSL_SYSTEM_PROMPT
    assert "只输出 JSON" in DSL_SYSTEM_PROMPT


def test_build_user_prompt_format():
    prompt = build_user_prompt("查询销售额", "上下文内容")
    assert "【上下文】" in prompt
    assert "【用户问题】" in prompt
    assert "查询销售额" in prompt
    assert "上下文内容" in prompt
    assert "输出 DSL JSON" in prompt

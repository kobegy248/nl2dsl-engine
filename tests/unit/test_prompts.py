from nl2dsl.llm.prompts import DSL_SYSTEM_PROMPT, DSL_JSON_SCHEMA, build_user_prompt


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


def test_system_prompt_has_no_examples():
    """Zero-shot: no '### 例' or '## 示例' sections."""
    assert "## 示例" not in DSL_SYSTEM_PROMPT
    assert "### 例" not in DSL_SYSTEM_PROMPT
    assert "用户：" not in DSL_SYSTEM_PROMPT


def test_system_prompt_has_cot_steps():
    """Prompt includes CoT thinking steps."""
    assert "思维链" in DSL_SYSTEM_PROMPT or "检查步骤" in DSL_SYSTEM_PROMPT
    assert "指标" in DSL_SYSTEM_PROMPT
    assert "维度" in DSL_SYSTEM_PROMPT
    assert "过滤条件" in DSL_SYSTEM_PROMPT


def test_system_prompt_covers_all_operators():
    """All 12 operators are documented."""
    operators = ["=", "!=", ">", "<", ">=", "<=", "between", "in", "like", "is_null"]
    for op in operators:
        assert op in DSL_SYSTEM_PROMPT, f"Operator '{op}' missing from prompt"


def test_system_prompt_covers_filter_tree():
    """Condition tree (and/or/not) is documented."""
    assert '"op"' in DSL_SYSTEM_PROMPT
    assert '"children"' in DSL_SYSTEM_PROMPT
    assert "and" in DSL_SYSTEM_PROMPT
    assert "or" in DSL_SYSTEM_PROMPT
    assert "not" in DSL_SYSTEM_PROMPT


def test_system_prompt_covers_having():
    """HAVING rules are documented."""
    assert "having" in DSL_SYSTEM_PROMPT.lower()


def test_system_prompt_covers_negation():
    """Negation handling is documented."""
    assert "非" in DSL_SYSTEM_PROMPT or "不是" in DSL_SYSTEM_PROMPT or "排除" in DSL_SYSTEM_PROMPT


def test_system_prompt_covers_time():
    """Time handling rules are documented."""
    assert "time_field" in DSL_SYSTEM_PROMPT or "时间" in DSL_SYSTEM_PROMPT


def test_json_schema_is_valid():
    """DSL_JSON_SCHEMA is valid JSON."""
    import json

    schema = json.loads(DSL_JSON_SCHEMA)
    assert schema["type"] == "object"
    assert "metrics" in schema["properties"]
    assert "dimensions" in schema["properties"]
    assert "filters" in schema["properties"]
    assert "having" in schema["properties"]
    assert "$defs" in schema
    assert "filter_tree" in schema["$defs"]
    assert "filter_leaf" in schema["$defs"]


def test_build_user_prompt_includes_question():
    prompt = build_user_prompt("查询华东销售额", "some context")
    assert "查询华东销售额" in prompt
    assert "some context" in prompt

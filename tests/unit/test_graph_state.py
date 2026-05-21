"""Tests for graph state model."""

import pytest

from nl2dsl.graph.state import QueryState, add_to_list


class TestAddToListReducer:
    def test_adds_item_to_empty_list(self):
        result = add_to_list(None, {"step": "test"})
        assert result == [{"step": "test"}]

    def test_appends_to_existing_list(self):
        result = add_to_list([{"step": "a"}], {"step": "b"})
        assert result == [{"step": "a"}, {"step": "b"}]

    def test_returns_none_for_none_input(self):
        result = add_to_list(None, None)
        assert result is None


class TestQueryState:
    def test_can_create_minimal_state(self):
        state = QueryState(
            question="test query",
            user_id="u001",
            tenant_id="t001",
        )
        assert state["question"] == "test query"
        assert state["user_id"] == "u001"

    def test_trace_field_uses_reducer(self):
        from langgraph.graph import StateGraph, END
        from nl2dsl.graph.state import QueryState

        builder = StateGraph(QueryState)

        def node_a(state: QueryState):
            return {"trace": [{"step": "a"}]}

        def node_b(state: QueryState):
            return {"trace": [{"step": "b"}]}

        builder.add_node("a", node_a)
        builder.add_node("b", node_b)
        builder.set_entry_point("a")
        builder.add_edge("a", "b")
        builder.add_edge("b", END)
        graph = builder.compile()

        result = graph.invoke({"question": "q", "user_id": "u", "tenant_id": "t"})
        assert result["trace"] == [{"step": "a"}, {"step": "b"}]

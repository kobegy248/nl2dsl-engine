"""StateGraph builder for the NL2DSL query pipeline."""

from __future__ import annotations

from langgraph.graph import StateGraph

from nl2dsl.graph.state import QueryState


def build_graph():
    """Build and compile the NL2DSL query pipeline StateGraph."""
    raise NotImplementedError("build_graph() will be implemented in a later task")

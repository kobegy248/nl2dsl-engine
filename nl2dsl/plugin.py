"""Plugin framework core."""
from __future__ import annotations
from typing import Any, Callable

from nl2dsl.graph.state import QueryState


class Registry:
    def __init__(self):
        self._components: dict[str, Any] = {}

    def register(self, name: str, component: Any) -> "Registry":
        self._components[name] = component
        return self

    def get(self, name: str) -> Any:
        if name not in self._components:
            raise KeyError(f"Component '{name}' not found")
        return self._components[name]

    def has(self, name: str) -> bool:
        return name in self._components

    def names(self) -> set[str]:
        return set(self._components.keys())


class Pipeline:
    def __init__(self):
        self._nodes: dict[str, Callable[[QueryState], dict]] = {}
        self._before: dict[str, list[Callable[[QueryState], dict]]] = {}
        self._after: dict[str, list[Callable[[QueryState], dict]]] = {}
        self._replacements: dict[str, Callable[[QueryState], dict]] = {}
        self._added: list[tuple[str, Callable[[QueryState], dict], str]] = []

    def set_default_nodes(self, nodes: dict[str, Callable]) -> "Pipeline":
        self._nodes = dict(nodes)
        return self

    def before(self, node: str, handler: Callable) -> "Pipeline":
        self._before.setdefault(node, []).append(handler)
        return self

    def after(self, node: str, handler: Callable) -> "Pipeline":
        self._after.setdefault(node, []).append(handler)
        return self

    def replace(self, node: str, handler: Callable) -> "Pipeline":
        self._replacements[node] = handler
        return self

    def add_node(self, name: str, handler: Callable, after: str) -> "Pipeline":
        self._added.append((name, handler, after))
        return self

    def compile(self) -> dict[str, Callable]:
        result = dict(self._nodes)
        for name, func in self._replacements.items():
            if name not in result:
                raise ValueError(f"Cannot replace unknown node '{name}'")
            result[name] = func
        for name, func, after in self._added:
            if after not in result:
                raise ValueError(f"Cannot add after unknown node '{after}'")
            result[name] = func
        for name in result:
            b = self._before.get(name, [])
            a = self._after.get(name, [])
            if b or a:
                result[name] = _wrap(result[name], b, a)
        return result

    def node_names(self) -> list[str]:
        names = list(self._nodes.keys())
        for name, _, _ in self._added:
            if name not in names:
                names.append(name)
        return names


def _wrap(func, before_hooks, after_hooks):
    def wrapper(state):
        for hook in before_hooks:
            r = hook(state)
            if r and r.get("status") == "error":
                return r
            if r:
                state = {**state, **r}
        result = func(state)
        for hook in after_hooks:
            hr = hook({**state, **result})
            if hr and hr.get("status") == "error":
                return hr
            if hr:
                result = {**result, **hr}
        return {**state, **result}
    return wrapper

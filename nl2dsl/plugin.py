"""Plugin framework core."""
from __future__ import annotations
from typing import Any


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

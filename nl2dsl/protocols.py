"""Component Protocol definitions for NL2DSL plugin framework."""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from nl2dsl.dsl.models import DSL


@runtime_checkable
class LLMBackend(Protocol):
    def generate(self, prompt: str, system_prompt: str = "") -> str: ...

    @property
    def model_name(self) -> str: ...


@runtime_checkable
class DSLGenerator(Protocol):
    def generate(self, question: str, schema: dict) -> DSL: ...


@runtime_checkable
class SQLBuilder(Protocol):
    def build(self, dsl: DSL) -> str: ...


@runtime_checkable
class SQLExecutor(Protocol):
    def execute(self, sql: str, timeout: int = 30) -> list[dict]: ...


@runtime_checkable
class SQLScanner(Protocol):
    def scan(self, sql: str) -> None: ...


@runtime_checkable
class Validator(Protocol):
    def validate(self, dsl: DSL) -> None: ...


@runtime_checkable
class SemanticResolver(Protocol):
    def resolve(self, dsl: DSL) -> DSL: ...


@runtime_checkable
class QuerySandbox(Protocol):
    def check(self, sql: str): ...


@runtime_checkable
class ClarificationDetector(Protocol):
    def detect(self, question: str) -> list: ...

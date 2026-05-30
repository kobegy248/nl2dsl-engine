"""Intent configuration and registry for the Agent orchestration layer.

Intents are loaded from ``configs/intents.yaml`` so new intents can be added
without modifying code.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import BaseModel


class IntentConfig(BaseModel):
    """Configuration for a single intent."""

    keywords: list[str]
    decomposition: str
    aggregation: str
    description: str


class IntentRegistry(BaseModel):
    """Registry of all configured intents."""

    intents: dict[str, IntentConfig]

    @classmethod
    def load(cls, path: str | pathlib.Path | None = None) -> "IntentRegistry":
        """Load the registry from a YAML file.

        Args:
            path: Path to the YAML file. Defaults to ``configs/intents.yaml``
                relative to the project root.

        Returns:
            An ``IntentRegistry`` populated from the YAML file.
        """
        if path is None:
            root = pathlib.Path(__file__).resolve().parents[2]
            path = root / "configs" / "intents.yaml"

        with open(path, encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh)

        return cls.model_validate(data)

    def get_intent_by_keywords(self, question: str) -> str | None:
        """Match a natural-language question to an intent name.

        The first intent whose keyword list has at least one keyword that
        appears in *question* is returned.  Matching is case-insensitive.
        If no intent matches, ``None`` is returned (callers should fall
        back to ``single_query``).

        Args:
            question: The user's natural-language question.

        Returns:
            The matched intent name, or ``None``.
        """
        lower_question = question.lower()
        for name, config in self.intents.items():
            for kw in config.keywords:
                if kw.lower() in lower_question:
                    return name
        return None

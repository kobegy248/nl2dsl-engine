import yaml
from pathlib import Path


class SemanticRegistry:
    def __init__(self):
        self.metrics: dict = {}
        self.dimensions: dict = {}
        self.data_sources: dict = {}

    def load(self, path: str) -> None:
        content = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        self.metrics = data.get("metrics", {})
        self.dimensions = data.get("dimensions", {})
        self.data_sources = data.get("data_sources", {})

    def has_metric(self, name: str) -> bool:
        return name in self.metrics

    def has_dimension(self, name: str) -> bool:
        return name in self.dimensions

    def has_data_source(self, name: str) -> bool:
        return name in self.data_sources

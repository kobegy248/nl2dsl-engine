"""Dataset loader for evaluation test cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from nl2dsl.evaluation.models import EvalTestCase as TestCase
from nl2dsl.utils.logger import get_logger

logger = get_logger("evaluation.dataset")


class DatasetLoader:
    """Load and validate evaluation datasets from YAML files.

    Expected directory structure::

        dataset_dir/
            ecommerce/
                basic.yaml
                filters.yaml
                joins.yaml
            bank/
                basic.yaml
            supply_chain/
                basic.yaml

    Each YAML file follows the schema::

        version: "1.0"
        domain: ecommerce
        description: "Basic ecommerce queries"
        test_cases:
          - id: ec_basic_001
            query: "查询华东地区的销售额"
            description: "..."
            tags: ["aggregation", "filter"]
            expected_dsl:
              data_source: orders
              metrics:
                - func: sum
                  field: pay_amount
                  alias: sales_amount
              ...
    """

    def __init__(self, dataset_dir: Path | str):
        self.dataset_dir = Path(dataset_dir)

    def load_all(self) -> list[TestCase]:
        """Load all test cases from all YAML files under dataset_dir."""
        cases: list[TestCase] = []
        if not self.dataset_dir.exists():
            logger.warning("Dataset directory not found: %s", self.dataset_dir)
            return cases

        for yaml_file in sorted(self.dataset_dir.rglob("*.yaml")):
            file_cases = self._load_file(yaml_file)
            cases.extend(file_cases)
            logger.info("Loaded %d cases from %s", len(file_cases), yaml_file)

        logger.info("Total test cases loaded: %d", len(cases))
        return cases

    def load_domain(self, domain: str) -> list[TestCase]:
        """Load test cases for a specific domain."""
        domain_dir = self.dataset_dir / domain
        if not domain_dir.exists():
            logger.warning("Domain directory not found: %s", domain_dir)
            return []

        cases: list[TestCase] = []
        for yaml_file in sorted(domain_dir.glob("*.yaml")):
            cases.extend(self._load_file(yaml_file))

        return cases

    def filter_by_tags(self, cases: list[TestCase], tags: list[str]) -> list[TestCase]:
        """Filter cases that have any of the given tags."""
        tag_set = set(tags)
        return [c for c in cases if any(t in tag_set for t in c.tags)]

    def _load_file(self, path: Path) -> list[TestCase]:
        """Load test cases from a single YAML file."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load %s: %s", path, exc)
            return []

        if not isinstance(data, dict):
            logger.error("Invalid YAML format in %s: expected dict", path)
            return []

        domain = data.get("domain", "")
        test_cases = data.get("test_cases", [])
        if not isinstance(test_cases, list):
            logger.error("Invalid test_cases in %s: expected list", path)
            return []

        cases: list[TestCase] = []
        for raw in test_cases:
            if not isinstance(raw, dict):
                continue
            try:
                tc = TestCase(
                    id=raw.get("id", ""),
                    query=raw.get("query", ""),
                    description=raw.get("description", ""),
                    domain=domain,
                    tags=raw.get("tags", []),
                    expected_dsl=raw.get("expected_dsl", {}),
                )
                cases.append(tc)
            except Exception as exc:
                logger.error("Failed to parse test case in %s: %s", path, exc)

        return cases


# --- V2 Dataset Loader ---

from nl2dsl.evaluation.models import V2TestCase


class V2DatasetLoader:
    """从 YAML 文件加载 V2 评测数据集。"""

    def __init__(self, dataset_dir: Path | str):
        self.dataset_dir = Path(dataset_dir)

    def load_all(self) -> list[V2TestCase]:
        """加载所有 YAML 文件中的 V2 测试用例。"""
        cases: list[V2TestCase] = []
        if not self.dataset_dir.exists():
            logger.warning("数据集目录未找到：%s", self.dataset_dir)
            return cases

        for yaml_file in sorted(self.dataset_dir.rglob("*.yaml")):
            file_cases = self._load_file(yaml_file)
            cases.extend(file_cases)
            logger.info("从 %s 加载了 %d 条 V2 用例", yaml_file, len(file_cases))

        logger.info("共加载 V2 测试用例：%d 条", len(cases))
        return cases

    def _load_file(self, path: Path) -> list[V2TestCase]:
        """从单个 YAML 文件加载 V2 测试用例。"""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("加载 %s 失败：%s", path, exc)
            return []

        if not isinstance(data, dict):
            return []

        test_cases = data.get("test_cases", [])
        if not isinstance(test_cases, list):
            return []

        cases: list[V2TestCase] = []
        for raw in test_cases:
            if not isinstance(raw, dict):
                continue
            try:
                tc = V2TestCase(
                    id=raw.get("id", ""),
                    query=raw.get("query", ""),
                    difficulty=raw.get("difficulty", "easy"),
                    category=raw.get("category", "basic"),
                    tags=raw.get("tags", []),
                    expected=raw.get("expected", {}),
                )
                cases.append(tc)
            except Exception as exc:
                logger.error("解析 %s 中的 V2 测试用例失败：%s", path, exc)

        return cases

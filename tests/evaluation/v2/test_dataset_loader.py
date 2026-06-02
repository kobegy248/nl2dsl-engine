import pytest
import tempfile
from pathlib import Path
from nl2dsl.evaluation.dataset import V2DatasetLoader


@pytest.fixture
def sample_dataset(tmp_path):
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "basic.yaml").write_text("""
test_cases:
  - id: BASIC_001
    query: 查询销售额
    difficulty: easy
    category: basic
    expected:
      intent: aggregate
      metric: sales_amount
""", encoding="utf-8")
    return dataset_dir


def test_load_v2_cases(sample_dataset):
    loader = V2DatasetLoader(sample_dataset)
    cases = loader.load_all()
    assert len(cases) == 1
    assert cases[0].id == "BASIC_001"
    assert cases[0].expected["metric"] == "sales_amount"

"""Initialize semantic layer from database metadata.

Usage:
    python scripts/init_semantic.py --db-url sqlite:///./test.db --output configs/metrics.yaml
"""

from __future__ import annotations

import argparse
import yaml
from sqlalchemy import create_engine, MetaData, inspect


def extract_schema(db_url: str) -> dict:
    """Extract table and column info from database."""
    engine = create_engine(db_url)
    inspector = inspect(engine)
    metadata = {"tables": {}}

    for table_name in inspector.get_table_names():
        columns = []
        for col in inspector.get_columns(table_name):
            columns.append({
                "name": col["name"],
                "type": str(col["type"]),
                "comment": col.get("comment", ""),
            })
        metadata["tables"][table_name] = columns

    return metadata


def generate_metrics_yaml(schema: dict, output: str) -> None:
    """Generate a starter metrics.yaml from schema."""
    template = {
        "metrics": {},
        "dimensions": {},
        "data_sources": {},
    }

    for table_name, columns in schema["tables"].items():
        ds_name = table_name.replace("_fact", "").replace("_dim", "")
        template["data_sources"][ds_name] = {
            "table": table_name,
            "metrics": [],
            "dimensions": [],
        }

        for col in columns:
            col_name = col["name"]
            comment = col.get("comment", "")

            # Guess dimensions vs metrics by column name patterns
            if any(kw in col_name.lower() for kw in ["_amount", "_price", "_qty", "_count"]):
                metric_name = col_name.replace("_amount", "").replace("_price", "")
                if metric_name:
                    template["metrics"][metric_name] = {
                        "expr": f"SUM({col_name})",
                        "description": comment or f"汇总 {col_name}",
                    }
                    template["data_sources"][ds_name]["metrics"].append(metric_name)
            else:
                template["dimensions"][col_name] = {
                    "column": col_name,
                    "description": comment or col_name,
                }
                template["data_sources"][ds_name]["dimensions"].append(col_name)

    with open(output, "w", encoding="utf-8") as f:
        yaml.dump(template, f, allow_unicode=True, sort_keys=False)

    print(f"Generated {output} with {len(template['metrics'])} metrics, {len(template['dimensions'])} dimensions")


def main():
    parser = argparse.ArgumentParser(description="Initialize semantic layer config from DB")
    parser.add_argument("--db-url", required=True, help="Database URL")
    parser.add_argument("--output", default="configs/metrics.yaml", help="Output YAML path")
    args = parser.parse_args()

    schema = extract_schema(args.db_url)
    generate_metrics_yaml(schema, args.output)


if __name__ == "__main__":
    main()

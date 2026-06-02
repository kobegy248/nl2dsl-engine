"""规范化关联解析器。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalJoin:
    """规范化的关联表示。"""

    entity: str
    on_field: str
    join_type: str


class JoinResolver:
    """将关联表/别名解析为规范化的实体表示。"""

    def __init__(self, data_sources_config: dict):
        """
        参数：
            data_sources_config: {data_source: {joins: {table_name: {entity, on, type, alias}}}}
        """
        self._entity_by_table: dict[str, str] = {}
        self._entity_by_alias: dict[str, str] = {}
        self._join_config: dict[str, dict] = {}

        for ds_name, ds_cfg in data_sources_config.items():
            # 支持两种格式:
            # 1. {data_source: {joins: {table: {entity, on, type, alias}}}}
            # 2. {table: {entity, on, type, alias}} (扁平格式)
            if "joins" in ds_cfg:
                joins = ds_cfg.get("joins", {})
            elif "entity" in ds_cfg or "on" in ds_cfg:
                # 扁平格式：ds_name 就是 table_name
                joins = {ds_name: ds_cfg}
            else:
                joins = {}
            for table_name, j_cfg in joins.items():
                entity = j_cfg.get("entity", table_name)
                alias = j_cfg.get("alias", "")
                self._entity_by_table[table_name] = entity
                self._join_config[table_name] = j_cfg
                if alias:
                    self._entity_by_alias[alias] = entity

    def resolve(self, table: str, on_field: str, join_type: str) -> CanonicalJoin:
        """将关联解析为规范化的表示。"""
        # 尝试按表名匹配
        entity = self._entity_by_table.get(table)
        if not entity:
            # 尝试按别名匹配
            entity = self._entity_by_alias.get(table, table)

        return CanonicalJoin(
            entity=entity,
            on_field=on_field,
            join_type=join_type.lower(),
        )

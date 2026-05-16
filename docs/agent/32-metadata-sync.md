# 32. 数据库元数据提取与导入

## 32.1 元数据提取器（`nl2dsl/sql_engine/metadata.py`）

| 类/方法 | 说明 |
|---------|------|
| `MetadataExtractor(db_url)` | 连接数据库提取元数据 |
| `list_tables() -> list[str]` | 列出所有表名 |
| `extract_table(name) -> TableInfo` | 提取单表元数据（字段、主键、注释） |
| `extract_all() -> Iterator[TableInfo]` | 提取所有表 |
| `to_text(table) -> str` | 转为文本描述（用于嵌入） |

数据结构：
- `TableInfo`: name, columns, primary_key, comment
- `ColumnInfo`: name, type, nullable, default, comment

## 32.2 初始化脚本（`scripts/init_vector_store.py`）

支持两种导入来源：

```bash
# 仅从 YAML 导入（默认）
python scripts/init_vector_store.py

# 仅从数据库元数据导入
python scripts/init_vector_store.py --from-db

# 同时从两者导入
python scripts/init_vector_store.py --from-db --from-yaml
```

## 32.3 数据去重与合并策略

| 场景 | 策略 |
|------|------|
| YAML 和数据库都有同一表 | 以 YAML 为准（人工配置优先级更高） |
| 数据库新增表 | 下次同步自动导入 |
| 数据库删除表 | 定时同步时清理 |
| YAML 修改指标 | 重新执行 init 脚本覆盖 |

## 32.4 自动同步（可选）

`MetadataSync` 类：
- `sync()` — 全量同步（删除旧表数据 → 重新导入）
- `start_auto_sync(interval_minutes)` — 定时后台同步

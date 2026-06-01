# Query Sandbox 设计

## 设计目标

在 SQL 正式执行前，通过**预演执行**检测潜在风险，避免昂贵查询拖垮数据库。

与 SQL Scanner 的区别：

| | SQL Scanner | Query Sandbox |
|--|-------------|---------------|
| **时机** | 静态分析（编译后） | 动态预演（执行前） |
| **能力** | 正则匹配危险模式 | 实际运行 EXPLAIN + LIMIT 预览 |
| **检测内容** | DELETE/UPDATE/DROP/注入 | 全表扫描、执行超时、返回量过大 |
| **阻断方式** | 直接拒绝 | 标记风险，可人工审核后放行 |

## 检查规则

QuerySandbox 执行三级检查：

### 1. EXPLAIN QUERY PLAN（成本预估）

运行 `EXPLAIN QUERY PLAN` 分析 SQL 的执行计划，统计 SCAN/SEARCH 操作次数，估算扫描行数。

- 阈值：`max_scan_rows = 100_000`
- 超过阈值 → 标记风险：`"预估扫描 X 行，超过阈值 Y"`

### 2. LIMIT 预览执行（时间检测）

在 SQL 末尾注入 `LIMIT 10`，执行预览查询，测量实际执行时间。

- 阈值：`max_exec_time_ms = 5_000`
- 超过阈值 → 标记风险：`"预览执行时间 Xms，超过阈值 Yms"`

### 3. WHERE 条件检测（安全兜底）

检查 SQL 是否包含 `WHERE` 子句。

- 无条件 → 标记风险：`"SQL 缺少 WHERE 条件，可能触发全表扫描"`
- 注意：聚合查询（如 `SELECT COUNT(*)`）可能合法无条件，需结合场景判断

## 执行流程

```
build_sql 生成 SQL
    │
    ▼
scan_sql（正则扫描危险模式）──[危险]──> 直接拒绝
    │[安全]
    ▼
sandbox_check（沙箱预演）
    │
    ├── 风险为空 ──→ 继续执行 execute_sql
    │
    └── 风险存在 ──→ human_review（人工确认）
                          │[确认]
                          ▼
                       execute_sql
```

## 配置参数

```python
QuerySandbox(
    engine=engine,               # SQLAlchemy Engine
    max_scan_rows=100_000,       # 最大允许扫描行数
    max_exec_time_ms=5_000,      # 最大允许预览执行时间（毫秒）
    preview_limit=10,            # 预览查询 LIMIT 条数
)
```

## 输出格式

```python
@dataclass
class SandboxResult:
    passed: bool           # True = 无风险，False = 有风险
    risks: list[str]       # 风险描述列表
    sample_rows: list[dict] # 预览查询返回的样例数据
    estimated_rows: int    # 预估扫描行数（-1 = 无法估算）
    execution_time_ms: float  # 预览执行耗时
```

## 安全设计

1. **防御性注入**：`_inject_limit()` 严格校验参数类型（必须为 `int`），且只接受 `SELECT` 语句
2. **EXPLAIN 防护**：`_explain()` 只在 SQL 以 `SELECT` 开头时执行，防止其他语句类型
3. **错误隔离**：预览执行失败不影响主流程，仅将错误信息加入 `risks` 列表

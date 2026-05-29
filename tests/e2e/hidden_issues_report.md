# NL2DSL 隐藏问题分析报告

## 一、安全问题（Security）

### 1.1 ColumnLevelSecurity 只检查 dimensions，不检查 metrics 和 filters
**严重程度**: 高  
**文件**: `nl2dsl/permission/column_level.py:14-20`

`check()` 方法只遍历 `dsl.dimensions`：
```python
for dim in dsl.dimensions:
    if dim in self._sensitive:
        raise PermissionError(...)
```

但 metrics 的 `field` 和 filters 的 `field` 也可能引用敏感列。例如：
-  metric: `{"func": "count", "field": "acct_no", "alias": "xxx"}` — `acct_no` 是敏感列，但不会触发权限检查
-  filter: `{"field": "cust_nm", "operator": "=", "value": "张三"}` — `cust_nm` 是敏感列，但不会触发权限检查

**影响**: 用户可以通过 metrics 或 filters 绕过列级权限控制，访问敏感数据。  
**修复**: 同时检查 `dsl.metrics` 中的 `field` 和 `dsl.filters` 中的 `field`。

---

### 1.2 SQLScanner 正则表达式可被绕过
**严重程度**: 高  
**文件**: `nl2dsl/sql_engine/scanner.py`

当前使用正则表达式检查危险模式：
```python
FORBIDDEN_PATTERNS = [
    (re.compile(r"(?i)\b(DELETE|UPDATE|DROP|INSERT|ALTER|CREATE|TRUNCATE)\b"), "危险操作"),
    (re.compile(r"(?i)/\*.*?\*/"), "块注释"),
    (re.compile(r"(?i)--[^\n]*"), "行注释"),
    (re.compile(r"(?i)\bUNION\b"), "UNION"),
    (re.compile(r"(?i);\s*\w+"), "多语句"),
]
```

绕过方式：
- `DE/**/LETE` — 块注释拆分关键字，绕过 `\bDELETE\b`
- `UNI/**/ON` — 绕过 `\bUNION\b`
- `;/**/SELECT` — 绕过 `;\s*\w+`

**影响**: 攻击者可以通过注释注入危险 SQL 操作。  
**修复**: 在检查前先移除所有注释，再对清理后的 SQL 做模式匹配。或使用 SQL parser 而非正则。

---

### 1.3 RowLevelSecurity 硬编码 tenant_id 字段
**严重程度**: 中  
**文件**: `nl2dsl/permission/row_level.py:25-31`

```python
tenant_id = user_perm.get("tenant_id")
if tenant_id:
    new_filters.append(Filter(field="tenant_id", operator="=", value=tenant_id))
```

硬编码了 `tenant_id` 字段名。如果 data_source 的表没有这个字段，SQL 执行会失败。

**影响**: 多租户隔离在特定表上无法工作，或导致查询报错。  
**修复**: 从 data_source 配置中读取租户隔离字段名，而非硬编码。

---

### 1.4 FeedbackCollector 无输入验证
**严重程度**: 中  
**文件**: `nl2dsl/feedback/collector.py`

`collect()` 方法直接将用户输入写入文件：
```python
with open(self._path, "a", encoding="utf-8") as f:
    f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

没有对 `corrected_dsl` 的大小做限制，恶意用户可以写入超大 JSON 耗尽磁盘。

**影响**: 磁盘空间耗尽攻击（DoS）。  
**修复**: 限制 `corrected_dsl` 序列化后的字符串长度（如 100KB），超限拒绝。

---

### 1.5 collect_results.py 使用 eval 解析 DSL
**严重程度**: 中  
**文件**: `tests/e2e/collect_results.py:86`

```python
dsl = eval(dsl_str, {"__builtins__": {}}, {})
```

虽然限制了 builtins，但 `eval` 仍然可以执行 Python 代码（如通过属性访问调用方法）。

**影响**: 如果测试文件被篡改，可能执行任意代码。  
**修复**: 使用 `ast.literal_eval()` 替代 `eval()`。

---

## 二、性能问题（Performance）

### 2.1 SQLExecutor 无返回行数限制
**严重程度**: 高  
**文件**: `nl2dsl/sql_engine/executor.py`

```python
def execute(self, sql: str) -> list[dict]:
    with self._engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = [dict(row._mapping) for row in result]
        return rows
```

没有任何行数限制。如果查询返回 1000 万行，内存会被耗尽。

**影响**: OOM 风险，服务不可用。  
**修复**: 在 execute 层添加硬限制（如最多返回 10 万行），或在 SQLBuilder 编译时自动注入 LIMIT。

---

### 2.2 QuerySandbox._explain 估计极不准确
**严重程度**: 中  
**文件**: `nl2dsl/query/sandbox.py:100-105`

```python
scan_count = sum(1 for r in rows if "SCAN" in str(r) or "SEARCH" in str(r))
return scan_count * 1000
```

使用 `scan_count * 1000` 的启发式估计，与真实行数可能相差几个数量级。

**影响**: 沙箱的扫描量阈值判断不可靠，可能放行危险查询或误杀正常查询。  
**修复**: 查询数据库统计信息（如 SQLite 的 `sqlite_stat1` 表）获取真实行数估计。

---

### 2.3 RAGRetriever 每次查询都重新 embed
**严重程度**: 中  
**文件**: `nl2dsl/rag/retriever.py`

`build_context()` 每次调用都要 embed query（CPU 密集型），但同一查询可能被重复执行。

**影响**: 高并发时 embedder 成为瓶颈，响应延迟增加。  
**修复**: 添加 embedding 缓存（如 LRUCache），缓存常用查询的 embedding。

---

### 2.4 Engine 每个 domain 独立数据库连接无池化
**严重程度**: 中  
**文件**: `nl2dsl/engine.py:200-201`

```python
db = create_engine(db_url, echo=False)
```

使用默认的 `create_engine` 配置，没有设置连接池大小、超时等参数。

**影响**: 高并发下可能耗尽数据库连接。  
**修复**: 配置连接池参数 `pool_size`, `max_overflow`, `pool_timeout`。

---

## 三、错误处理问题（Error Handling）

### 3.1 _mock_dsl_from_question 硬编码电商逻辑，不支持银行领域
**严重程度**: 高  
**文件**: `nl2dsl/graph/nodes.py:389-504`

`_mock_dsl_from_question` 函数中硬编码了：
- data_source 列表: `["orders", "products", "customers"]`
- 指标: `sales_amount`, `gmv`, `order_count` 等
- 维度: `product_name`, `brand`, `category` 等
- 表名: `customer_dim`, `product_dim`

当 bank domain 查询 fallback 到 mock 时，会生成完全错误的 DSL。

**影响**: 银行领域的 mock fallback 路径不可用。  
**修复**: 从 `registry_dict` 中动态读取 metrics/dimensions/data_sources，而非硬编码。

---

### 3.2 _post_process_dsl 硬编码 data_source 白名单
**严重程度**: 高  
**文件**: `nl2dsl/graph/nodes.py:329-331`

```python
if dsl_dict["data_source"] not in ["orders", "products", "customers"]:
    dsl_dict["data_source"] = default_data_source
```

硬编码了电商 data_source，银行领域的 `customer_accounts`、`transactions` 等会被强制改为 `orders`。

**影响**: 银行领域的 DSL 生成被错误修改。  
**修复**: 从 `registry_dict` 中读取合法的 data_source 列表。

---

### 3.3 human_review 在无 checkpointer 时无法恢复
**严重程度**: 高  
**文件**: `nl2dsl/graph/builder.py:186-213`

当 `checkpointer=None` 时，`human_review` 节点不会中断（没有 `interrupt_before`）。但 `route_after_sandbox` 仍可能路由到 `human_review`，导致查询进入 `pending_review` 状态且永远无法恢复。

**影响**: 沙箱告警的查询会永久卡住。  
**修复**: 当 `checkpointer=None` 时，sandbox 告警应直接路由到 `execute` 或 `end`，跳过 `human_review`。

---

### 3.4 query_stream 无异常处理
**严重程度**: 中  
**文件**: `nl2dsl/api_factory.py:503-540`

`query_stream` 路由中 `event_generator` 没有 try-catch：
```python
async def event_generator():
    async for chunk in query_graph.astream(state, config, stream_mode="updates"):
        yield f"data: {json.dumps(chunk, default=str)}\n\n"
```

如果 astream 失败，异常会直接抛出，客户端收不到 SSE 错误事件。

**影响**: 客户端连接异常断开，无法获取错误信息。  
**修复**: 在 event_generator 中添加 try-catch，yield 错误事件。

---

### 3.5 LLMClient.generate 无重试和超时
**严重程度**: 中  
**文件**: `nl2dsl/llm/client.py:24-42`

直接调用 API，没有重试逻辑和超时控制。网络波动会导致查询失败。

**影响**: 偶发的网络问题导致查询失败，用户体验差。  
**修复**: 添加指数退避重试（最多 3 次）和请求超时（如 30 秒）。

---

### 3.6 api_factory.query_resume 传入 None 状态
**严重程度**: 中  
**文件**: `nl2dsl/api_factory.py:542-565`

```python
if req.action == "approve":
    result = await query_graph.ainvoke(None, config)
```

传入 `None` 作为输入状态。当 `checkpointer=None` 时，LangGraph 无法从 None 恢复状态。

**影响**: resume 功能在没有 checkpointer 时不可用。  
**修复**: 需要 checkpointer 才能支持 resume，应在启动时检查并给出明确错误。

---

## 四、设计问题（Design）

### 4.1 SemanticResolver 不解析 dimensions（已绕过但未根治）
**严重程度**: 中  
**文件**: `nl2dsl/semantic/resolver.py:13-16`

```python
def resolve(self, dsl: DSL) -> DSL:
    new_metrics = self._resolve_metrics(dsl.metrics)
    new_filters = self._resolve_filters(dsl.filters)
    return dsl.model_copy(update={"metrics": new_metrics, "filters": new_filters})
```

`resolve()` 只解析 metrics 和 filters，不解析 dimensions。dimensions 的语义→物理映射被推迟到 SQLBuilder 中处理。

**影响**: 架构职责不清晰，dimensions 的解析分散在两个组件中。  
**修复**: SemanticResolver 应该负责所有语义解析，包括 dimensions。

---

### 4.2 DSLValidator 不验证 filters 中的字段
**严重程度**: 中  
**文件**: `nl2dsl/dsl/validator.py`

`validate()` 只检查 data_source、metrics alias、dimensions，不验证 filters 中的 `field` 是否存在于 dimensions 或 metrics 中。

**影响**: 非法的 filter 字段会流入 SQLBuilder，导致 SQL 生成失败或引用不存在的列。  
**修复**: 验证 filters 中的 field 是否存在于已注册的 dimensions 中。

---

### 4.3 _build_fallback_prompt 硬编码电商 Schema
**严重程度**: 低  
**文件**: `nl2dsl/graph/nodes.py:90-119`

`_build_fallback_prompt` 函数硬编码了电商领域的表结构和指标定义。当 RAG 不可用时，LLM 只能基于这些硬编码信息生成 DSL，不支持银行领域。

**影响**: 银行领域在无 RAG 时 DSL 生成质量差。  
**修复**: 从 `registry_dict` 动态构建 fallback prompt。

---

### 4.4 Engine._load_defaults 中 yaml.safe_load 未处理异常
**严重程度**: 低  
**文件**: `nl2dsl/engine.py:193`

```python
pd = yaml.safe_load(perm_path.read_text(encoding="utf-8"))
```

如果 permissions.yaml 格式错误（如 YAML 语法错误），会抛出异常导致整个 domain 初始化失败。

**影响**: 单个配置错误导致整个系统无法启动。  
**修复**: 用 try-catch 包裹 yaml 加载，记录错误但继续加载其他 domain。

---

### 4.5 MilvusLiteStore.search 固定字段列表可能缺失
**严重程度**: 低  
**文件**: `nl2dsl/rag/store.py:58-68`

```python
output_fields=["text", "type", "name"],
```

如果记录中没有 `type` 或 `name` 字段，Milvus 查询可能报错。

**影响**: RAG 检索失败。  
**修复**: 确保所有 upsert 的记录都包含这些字段，或在查询时处理缺失字段。

---

## 五、测试覆盖盲区

| 模块 | 未覆盖场景 | 风险 |
|------|-----------|------|
| api_factory | `query_stream` 路由 | SSE 异常处理未测试 |
| api_factory | `query_resume` 路由 | 状态恢复逻辑未测试 |
| graph/builder | `human_review` 中断流程 | 无 checkpointer 时行为未测试 |
| rag/sync | 增量同步逻辑 | YAML 变更检测未测试 |
| engine | 多 domain 并发 | 组件隔离性未测试 |
| sql_engine | 大数据量查询 | LIMIT 保护未测试 |
| permission | 列权限绕过（metrics/filters） | 安全漏洞未测试 |
| sql_scanner | 正则绕过场景 | 安全漏洞未测试 |
| sandbox | 无 WHERE 的全表扫描 | 已修复但需持续验证 |
| llm/client | 网络超时/重试 | 无测试 |

---

## 六、优先级排序

### P0（立即修复）
1. ColumnLevelSecurity 检查 metrics 和 filters 中的敏感列
2. SQLScanner 注释绕过漏洞
3. _mock_dsl_from_question 和 _post_process_dsl 硬编码问题
4. human_review 在无 checkpointer 时的死锁

### P1（本周修复）
5. SQLExecutor 返回行数限制
6. RowLevelSecurity 硬编码 tenant_id 字段
7. query_stream 异常处理
8. LLMClient 重试和超时

### P2（后续优化）
9. QuerySandbox 准确的行数估计
10. RAGRetriever embedding 缓存
11. SemanticResolver 解析 dimensions
12. DSLValidator 验证 filters 字段

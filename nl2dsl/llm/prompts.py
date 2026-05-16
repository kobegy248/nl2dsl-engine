DSL_SYSTEM_PROMPT = """你是一个数据查询助手。请根据提供的信息将用户问题转换为 DSL（JSON 格式）。

规则：
1. 只输出 JSON，不要输出其他内容
2. data_source 必须是给定的数据源名称
3. metrics 中的 alias 必须是已注册的指标名
4. dimensions 中的 field 必须是已注册的维度名
5. 禁止 SELECT *，必须指定 metrics 或 dimensions

输出格式：
{
  "metrics": [{"func": "sum", "field": "order_amount", "alias": "sales_amount"}],
  "dimensions": ["product_name"],
  "filters": [{"field": "region", "operator": "=", "value": "华东"}],
  "order_by": [{"field": "sales_amount", "direction": "desc"}],
  "limit": 10,
  "data_source": "orders"
}
"""


def build_user_prompt(question: str, context: str) -> str:
    return f"""【上下文】
{context}

【用户问题】
{question}

请输出 DSL JSON："""

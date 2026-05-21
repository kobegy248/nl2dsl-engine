"""LLM 模型速度对比测试."""

import time
from nl2dsl.llm.client import LLMClient
from nl2dsl.config import settings

system_prompt = "你是一个数据查询助手，只输出 JSON。"
user_prompt = "查询华东地区销售额最高的10个产品"


def benchmark(model: str, runs: int = 3):
    client = LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=model,
    )
    times = []
    for i in range(runs):
        t0 = time.time()
        result = client.generate(user_prompt, system_prompt)
        t1 = time.time()
        elapsed = (t1 - t0) * 1000
        times.append(elapsed)
        print(f"  Run {i + 1}: {elapsed:.0f}ms  (response {len(result)} chars)")

    avg = sum(times) / len(times)
    print(f"  Average: {avg:.0f}ms\n")
    return avg


if __name__ == "__main__":
    print("=" * 50)
    print("Model: qwen3:4b")
    print("=" * 50)
    t4b = benchmark("qwen3:4b")

    print("=" * 50)
    print("Model: qwen3:8b")
    print("=" * 50)
    t8b = benchmark("qwen3:8b")

    print("=" * 50)
    print(f"Summary: 4b avg={t4b:.0f}ms  |  8b avg={t8b:.0f}ms")
    print(f"Speedup: {t8b / t4b:.1f}x" if t4b > 0 else "N/A")

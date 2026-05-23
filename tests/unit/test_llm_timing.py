"""测试 LLM 调用耗时."""

import time
from unittest.mock import patch, MagicMock

import pytest

from nl2dsl.llm.client import LLMClient
from nl2dsl.config import settings


def _ollama_available() -> bool:
    """检查 Ollama 服务是否可访问."""
    import urllib.request

    try:
        base = settings.llm_base_url.replace("/v1", "")
        urllib.request.urlopen(base, timeout=2)
        return True
    except Exception:
        return False


OLLAMA_AVAILABLE = _ollama_available()


class TestLLMTimingMock:
    """Mock 方式测试 LLM 耗时记录逻辑."""

    @pytest.fixture
    def client(self):
        return LLMClient(
            api_key="test-key", base_url="https://test.example.com", model="test-model"
        )

    def test_generate_records_time(self, client, caplog):
        """验证 generate 方法内部记录了耗时日志."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"data_source": "orders"}'))
        ]
        mock_response.usage = {"prompt_tokens": 10, "completion_tokens": 5}

        with patch.object(
            client._client.chat.completions, "create", return_value=mock_response
        ):
            with caplog.at_level("INFO", logger="nl2dsl.llm"):
                result = client.generate("查询销售额", system_prompt="你是一个助手")

        assert "orders" in result
        # 验证日志中包含耗时信息 (格式: "LLM response: tokens=... time=XXms ...")
        assert any("time=" in rec.message for rec in caplog.records), f"日志记录: {[r.message for r in caplog.records]}"

    def test_generate_time_monotonic(self, client):
        """验证 LLM 调用前后时间单调递增."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"data_source": "orders"}'))
        ]
        mock_response.usage = {"prompt_tokens": 10, "completion_tokens": 5}

        with patch.object(
            client._client.chat.completions, "create", return_value=mock_response
        ):
            t0 = time.time()
            client.generate("查询销售额", system_prompt="你是一个助手")
            t1 = time.time()

        # Mock 调用应瞬间完成，耗时 < 100ms
        elapsed_ms = (t1 - t0) * 1000
        assert elapsed_ms < 100, f"Mock 调用耗时异常: {elapsed_ms:.2f}ms"

    def test_generate_with_delayed_response(self, client):
        """测试延迟响应场景下的耗时准确性."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"data_source": "orders"}'))
        ]
        mock_response.usage = {"prompt_tokens": 10, "completion_tokens": 5}

        def delayed_create(*args, **kwargs):
            time.sleep(0.05)  # 模拟 50ms 延迟
            return mock_response

        with patch.object(
            client._client.chat.completions, "create", side_effect=delayed_create
        ):
            t0 = time.time()
            client.generate("查询销售额", system_prompt="你是一个助手")
            t1 = time.time()

        elapsed_ms = (t1 - t0) * 1000
        # 允许 20ms 容差
        assert elapsed_ms >= 30, f"预期耗时 >= 50ms, 实际 {elapsed_ms:.2f}ms"


class TestLLMTimingReal:
    """真实 LLM 调用耗时测试（需本地 Ollama 服务）."""

    @pytest.fixture
    def real_client(self):
        """创建连接配置中 LLM 的真实客户端."""
        return LLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama 服务不可用，跳过真实调用测试",
    )
    def test_real_llm_call_timing(self, real_client):
        """测试真实 LLM 调用的耗时."""
        system_prompt = "你是一个数据查询助手，只输出 JSON。"
        user_prompt = "查询华东地区销售额最高的产品"

        t0 = time.time()
        result = real_client.generate(user_prompt, system_prompt)
        t1 = time.time()

        elapsed_ms = (t1 - t0) * 1000

        # 基本验证
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

        # 耗时断言（本地 Ollama 一般 < 30s）
        assert elapsed_ms < 60000, f"LLM 调用耗时过长: {elapsed_ms:.2f}ms"

        # 打印耗时供人工查看
        print(f"\n[LLM Timing] model={settings.llm_model} time={elapsed_ms:.2f}ms")
        print(f"[LLM Timing] response_length={len(result)}")

    @pytest.mark.skipif(
        not OLLAMA_AVAILABLE,
        reason="Ollama 服务不可用，跳过真实调用测试",
    )
    def test_real_llm_call_multiple(self, real_client):
        """多次调用取平均耗时."""
        system_prompt = "你是一个数据查询助手，只输出 JSON。"
        user_prompt = "查询2024年各品牌的总销售额"

        times = []
        for i in range(3):
            t0 = time.time()
            result = real_client.generate(user_prompt, system_prompt)
            t1 = time.time()
            times.append((t1 - t0) * 1000)
            assert result is not None

        avg_ms = sum(times) / len(times)
        min_ms = min(times)
        max_ms = max(times)

        print(f"\n[LLM Timing] 3 calls avg={avg_ms:.2f}ms min={min_ms:.2f}ms max={max_ms:.2f}ms")

        # 平均值应合理
        assert avg_ms < 30000, f"平均耗时过长: {avg_ms:.2f}ms"

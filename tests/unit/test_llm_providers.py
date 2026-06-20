"""多 Provider LLM 注册中心测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nl2dsl.llm.providers import (
    LLMProviderRegistry,
    ProviderConfig,
)


def _fake_settings(*, api_key="", base_url="https://default.example.com",
                   model="default-model", provider="default", providers=""):
    return SimpleNamespace(
        llm_api_key=api_key,
        llm_base_url=base_url,
        llm_model=model,
        llm_provider=provider,
        llm_providers=providers,
    )


# ----------------------------------------------------------------- loading
def test_default_provider_from_flat_fields():
    s = _fake_settings(api_key="sk-default", base_url="https://a", model="m-a")
    reg = LLMProviderRegistry(s)
    assert reg.list_providers() == ["default"]
    cfg = reg.get_config()
    assert cfg.name == "default"
    assert cfg.api_key == "sk-default"
    assert cfg.base_url == "https://a"
    assert cfg.model == "m-a"
    assert cfg.is_configured


def test_named_providers_loaded_from_json():
    providers = json.dumps({
        "deepseek": {
            "api_key": "sk-ds",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-pro",
        },
        "glm": {
            "api_key": "sk-glm",
            "base_url": "https://open.bigmodel.cn/api/paas/v4/",
            "model": "glm-4.5-air",
        },
    })
    s = _fake_settings(providers=providers, provider="deepseek")
    reg = LLMProviderRegistry(s)
    assert set(reg.list_providers()) == {"default", "deepseek", "glm"}
    assert reg.active_name == "deepseek"
    ds = reg.get_config("deepseek")
    assert ds.model == "deepseek-v4-pro"
    assert ds.is_configured


def test_invalid_json_providers_is_ignored():
    s = _fake_settings(providers="not-json", api_key="sk-x")
    reg = LLMProviderRegistry(s)
    # 只有 default 残留，非法 JSON 不应崩溃
    assert reg.list_providers() == ["default"]
    assert reg.get_config().api_key == "sk-x"


def test_default_provider_always_present_even_with_named():
    s = _fake_settings(
        api_key="sk-flat",
        providers=json.dumps({"foo": {"api_key": "sk-foo", "base_url": "u", "model": "m"}}),
    )
    reg = LLMProviderRegistry(s)
    assert "default" in reg.list_providers()
    assert reg.get_config("default").api_key == "sk-flat"


# --------------------------------------------------------------- switching
def test_set_active_switches_provider():
    providers = json.dumps({
        "deepseek": {"api_key": "sk-ds", "base_url": "u-ds", "model": "m-ds"},
        "glm": {"api_key": "sk-glm", "base_url": "u-glm", "model": "m-glm"},
    })
    s = _fake_settings(providers=providers, provider="deepseek")
    reg = LLMProviderRegistry(s)
    assert reg.active_name == "deepseek"

    reg.set_active("glm")
    assert reg.active_name == "glm"
    assert reg.get_config().model == "m-glm"


def test_set_active_unknown_raises():
    s = _fake_settings(api_key="sk-x")
    reg = LLMProviderRegistry(s)
    with pytest.raises(KeyError):
        reg.set_active("nope")


def test_get_config_unknown_raises():
    s = _fake_settings(api_key="sk-x")
    reg = LLMProviderRegistry(s)
    with pytest.raises(KeyError):
        reg.get_config("missing")


def test_active_falls_back_when_configured_name_missing():
    # llm_provider 指向不存在的 name -> 回退到首个可用 provider
    s = _fake_settings(api_key="sk-x", provider="ghost")
    reg = LLMProviderRegistry(s)
    assert reg.active_name == "default"


# ------------------------------------------------------------- build_client
def test_build_client_returns_none_without_api_key():
    s = _fake_settings(api_key="", base_url="u", model="m")
    reg = LLMProviderRegistry(s)
    assert reg.build_client() is None


def test_build_client_constructs_llmclient_for_active(monkeypatch):
    s = _fake_settings(api_key="sk-1", base_url="https://u", model="m-1")
    reg = LLMProviderRegistry(s)

    built = {}

    def fake_init(self, api_key, base_url, model):
        built["api_key"] = api_key
        built["base_url"] = base_url
        built["model"] = model

    from nl2dsl.llm import providers as prov_mod

    monkeypatch.setattr(
        "nl2dsl.llm.client.LLMClient.__init__", fake_init, raising=True
    )
    client = reg.build_client()
    assert client is not None
    assert built == {"api_key": "sk-1", "base_url": "https://u", "model": "m-1"}


def test_build_client_respects_runtime_switch(monkeypatch):
    providers = json.dumps({
        "deepseek": {"api_key": "sk-ds", "base_url": "u-ds", "model": "m-ds"},
        "glm": {"api_key": "sk-glm", "base_url": "u-glm", "model": "m-glm"},
    })
    s = _fake_settings(providers=providers, provider="deepseek")
    reg = LLMProviderRegistry(s)

    captured = []

    def fake_init(self, api_key, base_url, model):
        captured.append(model)

    monkeypatch.setattr(
        "nl2dsl.llm.client.LLMClient.__init__", fake_init, raising=True
    )

    reg.build_client()
    reg.set_active("glm")
    reg.build_client()

    assert captured == ["m-ds", "m-glm"]


# ------------------------------------------------------------- register API
def test_register_new_provider_then_switch():
    s = _fake_settings(api_key="sk-x")
    reg = LLMProviderRegistry(s)
    reg.register(ProviderConfig("qwen", "sk-qwen", "u-qwen", "m-qwen"))
    assert "qwen" in reg.list_providers()
    reg.set_active("qwen")
    assert reg.get_config().model == "m-qwen"


# ---------------------------------------------- module-level convenience API
def test_module_helpers_delegate_to_singleton():
    from nl2dsl.llm import providers as prov_mod

    # 单例至少含 default provider
    assert "default" in prov_mod.list_providers()
    assert prov_mod.active_provider() in prov_mod.list_providers()
    summaries = prov_mod.describe_providers()
    assert any(item["name"] == "default" for item in summaries)
    # api_key 必须脱敏
    for item in summaries:
        assert "api_key" not in item

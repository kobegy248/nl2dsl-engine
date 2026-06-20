"""多 Provider LLM 注册中心。

支持同时注册多个 OpenAI 兼容的模型服务，并随时切换激活的 provider：

- 通过配置切换：设置 ``NL2DSL_LLM_PROVIDER=<name>`` 环境变量（重启生效）。
- 通过代码切换：调用 :func:`set_active_provider`（运行时即时生效，无需重启）。

Provider 来源：
  1. ``NL2DSL_LLM_PROVIDERS``（JSON 字符串）：命名 provider，每个为
     ``{api_key, base_url, model}``。
  2. 平铺字段 ``NL2DSL_LLM_API_KEY`` / ``NL2DSL_LLM_BASE_URL`` / ``NL2DSL_LLM_MODEL``：
     始终作为名为 ``"default"`` 的 provider 暴露，保持向后兼容。

激活的 provider 由 ``NL2DSL_LLM_PROVIDER`` 选择，默认 ``"default"``。
未配置 api_key 的 provider 在构建客户端时返回 ``None``，沿用引擎既有
"无 LLM" 契约（回退到规则生成）。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Optional

from nl2dsl.config import Settings, settings
from nl2dsl.utils.logger import get_logger

logger = get_logger("llm")


@dataclass
class ProviderConfig:
    """单个模型服务的连接配置。"""

    name: str
    api_key: str
    base_url: str
    model: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


class LLMProviderRegistry:
    """管理多个命名 provider 并解析当前激活的 provider。"""

    def __init__(self, settings_obj: Optional[Settings] = None):
        self._lock = threading.Lock()
        self._settings = settings_obj or settings
        self._providers: dict[str, ProviderConfig] = self._load_providers(self._settings)
        active = getattr(self._settings, "llm_provider", "default") or "default"
        self._active: str = active if active in self._providers else (
            next(iter(self._providers)) if self._providers else "default"
        )

    @staticmethod
    def _load_providers(s: Settings) -> dict[str, ProviderConfig]:
        providers: dict[str, ProviderConfig] = {}

        # "default" provider 始终来自平铺字段，保证向后兼容
        providers["default"] = ProviderConfig(
            name="default",
            api_key=getattr(s, "llm_api_key", "") or "",
            base_url=getattr(s, "llm_base_url", "") or "",
            model=getattr(s, "llm_model", "") or "",
        )

        # 命名 provider 来自 JSON
        raw = (getattr(s, "llm_providers", "") or "").strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.error("NL2DSL_LLM_PROVIDERS 不是合法 JSON，已忽略: %s", exc)
                data = {}
            if isinstance(data, dict):
                for name, spec in data.items():
                    if not isinstance(spec, dict):
                        continue
                    providers[str(name)] = ProviderConfig(
                        name=str(name),
                        api_key=str(spec.get("api_key", "") or ""),
                        base_url=str(spec.get("base_url", "") or ""),
                        model=str(spec.get("model", "") or ""),
                    )
        return providers

    # ------------------------------------------------------------------ query
    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    @property
    def active_name(self) -> str:
        return self._active

    def get_config(self, name: Optional[str] = None) -> ProviderConfig:
        key = name or self._active
        if key not in self._providers:
            raise KeyError(
                f"LLM provider '{key}' 未注册，可用: {self.list_providers()}"
            )
        return self._providers[key]

    # --------------------------------------------------------------- mutate
    def register(self, config: ProviderConfig) -> None:
        """运行时注册一个新 provider。"""
        with self._lock:
            self._providers[config.name] = config
            logger.info("LLM provider 已注册: %s", config.name)

    def set_active(self, name: str) -> None:
        """切换激活的 provider（运行时即时生效，无需重启）。"""
        with self._lock:
            if name not in self._providers:
                raise KeyError(
                    f"无法切换到未注册的 LLM provider '{name}'，可用: {self.list_providers()}"
                )
            self._active = name
            logger.info("激活的 LLM provider 已切换为 '%s'", name)

    # ------------------------------------------------------------------ build
    def build_client(self, name: Optional[str] = None):
        """构建指定（或当前激活）provider 的 LLMClient。

        provider 无 api_key 时返回 ``None``，沿用 "无 LLM" 契约。
        """
        from nl2dsl.llm.client import LLMClient  # 局部导入避免循环依赖

        cfg = self.get_config(name)
        if not cfg.api_key:
            logger.warning("LLM provider '%s' 未配置 api_key，跳过客户端构建", cfg.name)
            return None
        return LLMClient(api_key=cfg.api_key, base_url=cfg.base_url, model=cfg.model)


# -------------------------------------------------------------------- 单例
registry = LLMProviderRegistry()


def get_llm_client():
    """返回当前激活 provider 的 LLMClient，未配置则返回 None。"""
    return registry.build_client()


def set_active_provider(name: str) -> None:
    """运行时切换激活的 LLM provider。"""
    registry.set_active(name)


def list_providers() -> list[str]:
    """返回所有已注册 provider 的名称。"""
    return registry.list_providers()


def active_provider() -> str:
    """返回当前激活 provider 的名称。"""
    return registry.active_name


def describe_providers() -> list[dict[str, Any]]:
    """返回所有 provider 的摘要（不含完整 api_key），供调试 / 展示。"""
    out: list[dict[str, Any]] = []
    for name, cfg in registry._providers.items():  # noqa: SLF001
        out.append({
            "name": cfg.name,
            "active": cfg.name == registry.active_name,
            "base_url": cfg.base_url,
            "model": cfg.model,
            "configured": cfg.is_configured,
            "api_key_masked": (cfg.api_key[:4] + "***") if cfg.api_key else "",
        })
    return out

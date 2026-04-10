from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()


def _getenv(*keys: str, default: str | None = None) -> str | None:
    for key in keys:
        value = os.getenv(key)
        if value is not None and str(value).strip() != "":
            return value.strip()
    return default


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class ProviderConfig:
    name: str
    host: str | None
    model: str | None
    api_key: str | None
    timeout: int = 180
    model_options: list[str] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.model)


@dataclass(slots=True)
class WechatConfig:
    appid: str | None
    appsecret: str | None
    token: str | None
    test_mode: bool = False


@dataclass(slots=True)
class ModelOption:
    id: str
    label: str
    provider: str
    model: str
    is_default: bool = False
    configured: bool = True


class Settings:
    def __init__(self) -> None:
        self.api_provider = _getenv("API", default="deepseek").lower()
        self.workflow_backend = _getenv("WORKFLOW_BACKEND", default="fastgpt").lower()
        self.batch_size = int(_getenv("BATCH_SIZE", default="5"))
        self.max_retries_default = int(_getenv("MAX_RETRIES_DEFAULT", default="10"))
        self.fastgpt_timeout = int(_getenv("FASTGPT_TIMEOUT", default="300"))
        self.fastgpt_http_retries = int(_getenv("FASTGPT_HTTP_RETRIES", default="2"))
        self.fastgpt_http_retry_delay = float(
            _getenv("FASTGPT_HTTP_RETRY_DELAY", default="1.5")
        )
        self.fastgpt_api_key = _getenv("FASTGPT_API_KEY")
        self.fastgpt_variable_mode = _getenv("FASTGPT_VARIABLE_MODE", default="legacy").lower()
        self.fastgpt_batch_mode = _getenv("FASTGPT_BATCH_MODE", default="auto").lower()

        self.ollama = ProviderConfig(
            name="ollama",
            host=_getenv("OLLAMA_HOST"),
            model=_getenv("OLLAMA_MODEL"),
            api_key=_getenv("OLLAMA_API_KEY", "API_KEY"),
            timeout=int(_getenv("OLLAMA_TIMEOUT", "LLM_TIMEOUT", default="180")),
            model_options=_split_csv(_getenv("OLLAMA_MODEL_OPTIONS")),
        )
        self.deepseek = ProviderConfig(
            name="deepseek",
            host=_getenv("DEEPSEEK_HOST"),
            model=_getenv("DEEPSEEK_MODEL"),
            api_key=_getenv("DEEPSEEK_API_KEY", "API_KEY"),
            timeout=int(_getenv("DEEPSEEK_TIMEOUT", "LLM_TIMEOUT", default="180")),
            model_options=_split_csv(_getenv("DEEPSEEK_MODEL_OPTIONS")),
        )
        self.gemini = ProviderConfig(
            name="gemini",
            host=_getenv("GEMINI_HOST"),
            model=_getenv("GEMINI_MODEL"),
            api_key=_getenv("GEMINI_API_KEY", "API_KEY"),
            timeout=int(_getenv("GEMINI_TIMEOUT", "LLM_TIMEOUT", default="180")),
            model_options=_split_csv(_getenv("GEMINI_MODEL_OPTIONS")),
        )
        self.claude = ProviderConfig(
            name="claude",
            host=_getenv("CLAUDE_HOST"),
            model=_getenv("CLAUDE_MODEL"),
            api_key=_getenv("CLAUDE_API_KEY", "API_KEY"),
            timeout=int(_getenv("CLAUDE_TIMEOUT", "LLM_TIMEOUT", default="180")),
            model_options=_split_csv(_getenv("CLAUDE_MODEL_OPTIONS")),
        )

        self.wechat = WechatConfig(
            appid=_getenv("WECHAT_APPID"),
            appsecret=_getenv("WECHAT_APPSECRET"),
            token=_getenv("WECHAT_TOKEN"),
            test_mode=_getenv("WECHAT_TEST_MODE", default="false").lower() == "true",
        )

    def provider_mapping(self) -> dict[str, ProviderConfig]:
        return {
            "ollama": self.ollama,
            "deepseek": self.deepseek,
            "gemini": self.gemini,
            "claude": self.claude,
        }

    def get_provider(self, name: str | None = None) -> ProviderConfig:
        provider_name = (name or self.api_provider).lower()
        mapping = self.provider_mapping()
        if provider_name not in mapping:
            raise ValueError(f"Unsupported provider: {provider_name}")

        provider = mapping[provider_name]
        if not provider.enabled:
            raise ValueError(
                f"Provider '{provider_name}' is not fully configured. "
                f"Need host and model in .env"
            )
        return provider

    def guess_provider_for_model(self, model_name: str) -> str | None:
        lowered = model_name.lower()
        if lowered.startswith("deepseek"):
            return "deepseek"
        if lowered.startswith("gemini"):
            return "gemini"
        if lowered.startswith("claude"):
            return "claude"
        for provider_name, provider in self.provider_mapping().items():
            if provider.model and provider.model.lower() == lowered:
                return provider_name
            if provider.model_options:
                for item in provider.model_options:
                    if item.lower() == lowered:
                        return provider_name
        return None

    def list_model_options(
        self,
        *,
        extra_models: Iterable[str] | None = None,
    ) -> list[ModelOption]:
        options: list[ModelOption] = []
        seen: set[str] = set()
        default_provider = self.api_provider

        def _add(
            provider_name: str,
            model_name: str,
            *,
            is_default: bool = False,
            configured: bool = True,
        ) -> None:
            key = f"{provider_name}::{model_name}"
            if not model_name or key in seen:
                return
            seen.add(key)
            suffix = "" if configured else " [未配置]"
            label = f"{model_name} ({provider_name}){suffix}"
            options.append(
                ModelOption(
                    id=key,
                    label=label,
                    provider=provider_name,
                    model=model_name,
                    is_default=is_default,
                    configured=configured,
                )
            )

        if self.workflow_backend in {"fastgpt", "hybrid", "fastgpt_hybrid"}:
            _add(
                "fastgpt",
                "workflow",
                is_default=True,
                configured=True,
            )

        for provider_name, provider in self.provider_mapping().items():
            if provider.enabled and provider.model:
                _add(
                    provider_name,
                    provider.model,
                    is_default=provider_name == default_provider,
                    configured=True,
                )
            elif provider.model:
                _add(
                    provider_name,
                    provider.model,
                    is_default=provider_name == default_provider,
                    configured=False,
                )
            for model_name in provider.model_options or []:
                _add(
                    provider_name,
                    model_name,
                    is_default=provider_name == default_provider
                    and provider.model == model_name,
                    configured=provider.enabled,
                )

        for model_name in extra_models or []:
            guessed_provider = self.guess_provider_for_model(model_name)
            if guessed_provider:
                provider = self.provider_mapping()[guessed_provider]
                _add(
                    guessed_provider,
                    model_name,
                    is_default=guessed_provider == default_provider
                    and self.provider_mapping()[guessed_provider].model == model_name,
                    configured=provider.enabled,
                )

        if not options:
            fallback_provider = self.provider_mapping().get(default_provider)
            if fallback_provider and fallback_provider.model:
                _add(default_provider, fallback_provider.model, is_default=True)

        return options

    def resolve_model_selection(self, selection_id: str | None) -> ModelOption | None:
        if self.workflow_backend in {"fastgpt", "hybrid", "fastgpt_hybrid"} and (
            not selection_id or selection_id == "fastgpt::workflow"
        ):
            return ModelOption(
                id="fastgpt::workflow",
                label="FastGPT 工作流",
                provider="fastgpt",
                model="workflow",
                is_default=True,
                configured=True,
            )

        if not selection_id:
            provider = self.get_provider()
            return ModelOption(
                id=f"{provider.name}::{provider.model}",
                label=f"{provider.model} ({provider.name})",
                provider=provider.name,
                model=provider.model or "",
                is_default=True,
                configured=provider.enabled,
            )

        if "::" in selection_id:
            provider_name, model_name = selection_id.split("::", 1)
            provider_name = provider_name.strip().lower()
            model_name = model_name.strip()
            if provider_name == "fastgpt":
                return ModelOption(
                    id=f"{provider_name}::{model_name or 'workflow'}",
                    label="FastGPT 工作流",
                    provider="fastgpt",
                    model=model_name or "workflow",
                    is_default=True,
                    configured=True,
                )
            if provider_name and model_name:
                self.get_provider(provider_name)
                return ModelOption(
                    id=f"{provider_name}::{model_name}",
                label=f"{model_name} ({provider_name})",
                provider=provider_name,
                model=model_name,
                is_default=provider_name == self.api_provider,
                configured=True,
            )

        guessed_provider = self.guess_provider_for_model(selection_id)
        if guessed_provider:
            self.get_provider(guessed_provider)
            model_name = selection_id.strip()
            return ModelOption(
                id=f"{guessed_provider}::{model_name}",
                label=f"{model_name} ({guessed_provider})",
                provider=guessed_provider,
                model=model_name,
                is_default=guessed_provider == self.api_provider,
                configured=self.provider_mapping()[guessed_provider].enabled,
            )
        raise ValueError(f"Unknown model selection: {selection_id}")


settings = Settings()

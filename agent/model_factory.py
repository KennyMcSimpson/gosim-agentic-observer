"""Environment-driven LangChain model construction for the minimal agent.

On the platform (cloud runs and the official local project runner) every run gets
OPENAI_BASE_URL and OPENAI_API_KEY: an OpenAI-compatible chat-completions proxy and a
temporary run credential. The proxy calls the model your team set on the Participate
page, so the model name sent from here is replaced. These two variables therefore take
precedence for every OpenAI-compatible provider; the provider-specific variables
(MODEL_BASE_URL, ZAI_API_KEY, ...) remain the fallback for your own local runs.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path


PROVIDER_ALIASES = {
    "chatgpt": "openai",
    "claude": "anthropic",
    "grok": "xai",
    "glm": "zai",
    "kimi": "moonshot",
    "qwen": "dashscope",
}

PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "zai": "ZAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}


# Sent when the platform proxy is used without a model name; the proxy replaces it with
# the model configured for the team on the Participate page.
PLATFORM_MODEL_PLACEHOLDER = "team-model"


class ModelConfigurationError(ValueError):
    """Raised when an optional model provider is only partially configured."""


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class ModelSettings:
    """Secret-safe provider settings loaded from process environment variables."""

    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    api_mode: str = "chat"
    # A model call is only made at a bounded night-start trigger. Keep each
    # stage short so a provider outage cannot consume a full survey wallclock.
    timeout_seconds: float = 4.0
    max_retries: int = 0
    top_k_candidates: int = 12
    model_refresh_nights: int = 7

    @classmethod
    def from_environment(cls, dotenv_path: Path | None = None) -> "ModelSettings":
        try:
            from dotenv import load_dotenv
        except ModuleNotFoundError:
            load_dotenv = None
        if load_dotenv is not None:
            load_dotenv(dotenv_path=dotenv_path, override=False)
        provider = os.environ.get("MODEL_PROVIDER", "deterministic").strip().lower()
        provider = PROVIDER_ALIASES.get(provider, provider)
        key_name = os.environ.get("MODEL_API_KEY_ENV", "").strip() or PROVIDER_KEY_ENV.get(
            provider, "MODEL_API_KEY"
        )
        # OPENAI_BASE_URL/OPENAI_API_KEY first (what the platform injects), then the
        # provider-specific settings. Anthropic's native API is not OpenAI-compatible.
        compatible_base = (
            os.environ.get("OPENAI_BASE_URL", "").strip() if provider != "anthropic" else ""
        )
        base_url = compatible_base or os.environ.get("MODEL_BASE_URL", "").strip()
        api_key = (
            os.environ.get("OPENAI_API_KEY", "").strip() if compatible_base else ""
        ) or os.environ.get(key_name, "").strip()
        model = (
            os.environ.get("OPENAI_MODEL", "").strip()
            or os.environ.get("MODEL_NAME", "").strip()
            or (PLATFORM_MODEL_PLACEHOLDER if compatible_base else "")
        )
        # The platform proxy speaks chat completions only.
        api_mode = os.environ.get(
            "MODEL_API_MODE",
            "responses" if provider == "openai" and not compatible_base else "chat",
        ).strip().lower()
        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            api_mode=api_mode,
            timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 4.0),
            max_retries=_env_int("LLM_MAX_RETRIES", 0),
            top_k_candidates=_env_int("LLM_TOP_K_CANDIDATES", 12, minimum=1),
            model_refresh_nights=_env_int("LLM_REFRESH_NIGHTS", 7, minimum=1),
        )

    @property
    def deterministic(self) -> bool:
        return self.provider in {"", "none", "deterministic"}


def build_chat_model(settings: ModelSettings):
    """Build one optional LangChain chat model without leaking its credential."""
    if settings.deterministic:
        return None
    if not settings.model or not settings.api_key:
        raise ModelConfigurationError(
            f"{settings.provider} requires a model name (OPENAI_MODEL or MODEL_NAME) "
            "and an API key (OPENAI_API_KEY or its provider key)"
        )
    if settings.timeout_seconds <= 0 or settings.max_retries < 0:
        raise ModelConfigurationError("timeout must be positive and retries non-negative")
    if settings.top_k_candidates < 1:
        raise ModelConfigurationError("LLM_TOP_K_CANDIDATES must be positive")
    if settings.provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ModuleNotFoundError as exc:
            raise ModelConfigurationError(
                "install langchain-anthropic to use Anthropic"
            ) from exc
        return ChatAnthropic(
            model=settings.model,
            api_key=settings.api_key,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )
    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise ModelConfigurationError(
            "install langchain-openai to use OpenAI or an OpenAI-compatible endpoint"
        ) from exc
    if settings.provider != "openai" and not settings.base_url:
        raise ModelConfigurationError(
            f"{settings.provider} requires OPENAI_BASE_URL or MODEL_BASE_URL for its compatible endpoint"
        )
    kwargs = {
        "model": settings.model,
        "api_key": settings.api_key,
        "timeout": settings.timeout_seconds,
        "max_retries": settings.max_retries,
    }
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.provider == "openai":
        if settings.api_mode not in {"chat", "responses"}:
            raise ModelConfigurationError("MODEL_API_MODE must be chat or responses")
        kwargs["use_responses_api"] = settings.api_mode == "responses"
    else:
        kwargs["use_responses_api"] = False
    return ChatOpenAI(**kwargs)

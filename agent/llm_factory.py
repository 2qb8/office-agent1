from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from agent.llm import LLM, OpenAICompatibleLLM


# config/.env wins; a project-root .env is the fallback.
load_dotenv("config/.env")
load_dotenv()


@dataclass(frozen=True)
class ProviderPreset:
    label: str
    base_url: str
    model: str
    requires_key: bool


PROVIDERS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset(
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        requires_key=True,
    ),
    "gemini": ProviderPreset(
        label="Google Gemini (OpenAI-compatible)",
        base_url=(
            "https://generativelanguage.googleapis.com/v1beta/openai"
        ),
        model="gemini-2.0-flash",
        requires_key=True,
    ),
    "openrouter": ProviderPreset(
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model="google/gemini-2.0-flash-001",
        requires_key=True,
    ),
    "ollama": ProviderPreset(
        label="Ollama (local)",
        base_url="http://localhost:11434/v1",
        model="qwen2.5:3b",
        requires_key=False,
    ),
    "custom": ProviderPreset(
        label="Any OpenAI-compatible endpoint",
        base_url="",
        model="",
        requires_key=False,
    ),
}

SETUP_HINT = (
    "Configure the AI planner once with:\n"
    "  python run.py ai setup\n"
    "or set LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL and LLM_API_KEY "
    "in config/.env."
)


def _get_float(
    name: str,
    default: float,
) -> float:

    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    return float(value)


def _get_int(
    name: str,
    default: int,
) -> int:

    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    return int(value)


def resolve_settings() -> dict[str, str]:
    """Provider name, endpoint, model and key from the environment."""

    provider = (
        os.getenv("LLM_PROVIDER") or ""
    ).strip().lower()

    preset = PROVIDERS.get(provider)

    base_url = (os.getenv("LLM_BASE_URL") or "").strip()

    if not base_url and preset:
        base_url = preset.base_url

    model = (os.getenv("LLM_MODEL") or "").strip()

    if not model and preset:
        model = preset.model

    api_key = (
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()

    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def create_llm() -> LLM:
    """Create the configured client, or explain how to configure one."""

    settings = resolve_settings()

    provider = settings["provider"]

    if not provider:
        raise RuntimeError(
            "No AI provider is configured.\n" + SETUP_HINT
        )

    preset = PROVIDERS.get(provider)

    if preset is None:
        raise RuntimeError(
            f"Unknown AI provider '{provider}'. Choose one of: "
            f"{', '.join(sorted(PROVIDERS))}."
        )

    if not settings["base_url"] or not settings["model"]:
        raise RuntimeError(
            f"Provider '{provider}' needs LLM_BASE_URL and "
            "LLM_MODEL.\n" + SETUP_HINT
        )

    if preset.requires_key and not settings["api_key"]:
        raise RuntimeError(
            f"{preset.label} needs an API key.\n" + SETUP_HINT
        )

    fallback_text = os.getenv("LLM_FALLBACK_MODELS", "")

    fallback_models = [
        name.strip()
        for name in fallback_text.split(",")
        if name.strip() and name.strip() != settings["model"]
    ]

    return OpenAICompatibleLLM(
        base_url=settings["base_url"],
        api_key=settings["api_key"],
        model=settings["model"],
        fallback_models=fallback_models,
        timeout=180,
        max_attempts=_get_int("LLM_MAX_ATTEMPTS", 5),
        retry_base_seconds=_get_float(
            "LLM_RETRY_BASE_SECONDS",
            2.0,
        ),
        retry_max_seconds=_get_float(
            "LLM_RETRY_MAX_SECONDS",
            30.0,
        ),
    )


def try_create_llm() -> LLM | None:
    """Return a client when one is configured, otherwise None."""

    if not (os.getenv("LLM_PROVIDER") or "").strip():
        return None

    try:
        return create_llm()
    except RuntimeError:
        return None

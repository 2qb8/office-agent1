from __future__ import annotations

import os

from dotenv import load_dotenv

from agent.llm import LLM, OpenAICompatibleLLM


load_dotenv("config/.env")


def _get_float(
    name: str,
    default: float,
) -> float:

    value = os.getenv(name)

    if value is None:
        return default

    return float(value)


def _get_int(
    name: str,
    default: int,
) -> int:

    value = os.getenv(name)

    if value is None:
        return default

    return int(value)


def create_llm() -> LLM:

    provider = os.getenv(
        "LLM_PROVIDER",
        "gemini",
    ).lower()

    if provider != "gemini":
        raise RuntimeError(
            f"Unknown LLM provider: {provider}"
        )

    api_key = os.getenv(
        "LLM_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "LLM_API_KEY is not configured."
        )

    base_url = os.getenv(
        "LLM_BASE_URL",
        "https://generativelanguage.googleapis.com/"
        "v1beta/openai",
    )

    model = os.getenv(
        "LLM_MODEL",
        "gemini-3.8-flash",
    )

    fallback_text = os.getenv(
        "LLM_FALLBACK_MODELS",
        "",
    )

    fallback_models = [
        model_name.strip()
        for model_name in fallback_text.split(",")
        if model_name.strip()
        and model_name.strip() != model
    ]

    return OpenAICompatibleLLM(
        base_url=base_url,
        api_key=api_key,
        model=model,
        fallback_models=fallback_models,
        timeout=180,
        max_attempts=_get_int(
            "LLM_MAX_ATTEMPTS",
            5,
        ),
        retry_base_seconds=_get_float(
            "LLM_RETRY_BASE_SECONDS",
            2.0,
        ),
        retry_max_seconds=_get_float(
            "LLM_RETRY_MAX_SECONDS",
            30.0,
        ),
    )
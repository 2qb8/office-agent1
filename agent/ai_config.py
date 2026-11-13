from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent.llm import LLMError, OpenAICompatibleLLM
from agent.llm_factory import PROVIDERS, resolve_settings


CONFIG_PATH = Path("config") / ".env"


@dataclass(frozen=True)
class AiConfig:
    provider: str
    base_url: str
    model: str
    api_key: str


def resolve() -> AiConfig:
    """Current AI settings from the environment (and config/.env)."""

    settings = resolve_settings()

    return AiConfig(
        provider=settings["provider"],
        base_url=settings["base_url"],
        model=settings["model"],
        api_key=settings["api_key"],
    )


def configured() -> bool:
    """True when a provider is set and its requirements are met."""

    provider = (os.getenv("LLM_PROVIDER") or "").strip().lower()

    if not provider:
        return False

    preset = PROVIDERS.get(provider)

    if preset is None:
        return False

    settings = resolve_settings()

    if not settings["base_url"] or not settings["model"]:
        return False

    if preset.requires_key and not settings["api_key"]:
        return False

    return True


def describe() -> str:
    """Human-readable status that never includes the key itself."""

    config = resolve()
    preset = PROVIDERS.get(config.provider)

    if not config.provider:
        label = " (not configured)"
    elif preset:
        label = f" ({preset.label})"
    else:
        label = " (unknown provider)"

    if preset and not preset.requires_key and not config.api_key:
        key_status = "not needed (local)"
    else:
        key_status = "set" if config.api_key else "not set"

    lines = [
        "AI planner",
        f"  provider : {config.provider or '(none)'}{label}",
        f"  endpoint : {config.base_url or '(not set)'}",
        f"  model    : {config.model or '(not set)'}",
        f"  api key  : {key_status}",
        (
            f"  config   : {CONFIG_PATH} "
            f"({'found' if CONFIG_PATH.exists() else 'not found'})"
        ),
        (
            "  status   : "
            + ("ready" if configured() else "not configured")
        ),
    ]

    if not configured():
        lines.extend(
            [
                "",
                "Next: python run.py ai setup",
                "  local, no key: python run.py ai setup "
                "--provider ollama",
            ]
        )

    return "\n".join(lines)


def write_config(
    values: dict[str, str],
    path: Path = CONFIG_PATH,
) -> Path:
    """
    Merge AI settings into an .env file, keeping unrelated lines.

    Newlines are rejected so a value can never break the file structure.
    """

    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise ValueError(
                f"{key} must not contain line breaks."
            )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []

    if path.exists():
        existing_lines = path.read_text(
            encoding="utf-8"
        ).splitlines()

    written: set[str] = set()
    lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()

        key = None

        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()

        if key in values:
            lines.append(f"{key}={values[key]}")
            written.add(key)
        else:
            lines.append(line)

    for key, value in values.items():
        if key not in written:
            lines.append(f"{key}={value}")

    path.write_text(
        "\n".join(lines).rstrip("\n") + "\n",
        encoding="utf-8",
    )

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return path


def test_connection(
    config: AiConfig,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Send one tiny request; returns (ok, detail)."""

    client = OpenAICompatibleLLM(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=timeout,
        max_attempts=1,
    )

    try:
        reply = client.generate(
            "Reply with the single word: OK",
            max_tokens=8,
        )
    except LLMError as exc:
        return False, str(exc)[:500]

    return True, " ".join(reply.split())[:80] or "(empty reply)"

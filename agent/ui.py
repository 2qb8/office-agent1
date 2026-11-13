"""Localisation, paths and settings shared by the desktop front end.

This module is deliberately free of GUI imports so it can be tested and
reused without a display.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.job import INSTRUCTION_SUFFIXES

APP_TITLE = "Office Agent"

LANGUAGES = {
    "en": "English",
    "ru": "Русский",
}

DEFAULT_LANGUAGE = "en"

SETTINGS_ENV = "OFFICE_AGENT_SETTINGS"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "instruction": "Instruction file",
        "output": "Output folder",
        "language": "Language",
        "browse": "Browse…",
        "run": "Run",
        "running": "Running…",
        "open_output": "Open output folder",
        "log": "Log",
        "ready": "Choose an instruction file, then press Run.",
        "no_instruction": "Choose an instruction file first.",
        "missing_instruction": "That file does not exist.",
        "unsupported_instruction": (
            "Choose a .docx, .txt or .md instruction file."
        ),
        "no_spec": (
            "This instruction has no job spec and the app does not use "
            "AI. Add a ```yaml block with a 'steps' list."
        ),
        "done": "Done: {count} file(s) created.",
        "failed": "Run failed: {error}",
        "select_instruction": "Select the instruction file",
        "instruction_filter": "Instructions",
        "all_files": "All files",
        "cannot_open": "Could not open the output folder: {error}",
        "no_output": "Run a job first.",
    },
    "ru": {
        "instruction": "Файл инструкции",
        "output": "Папка результатов",
        "language": "Язык",
        "browse": "Обзор…",
        "run": "Запустить",
        "running": "Выполняется…",
        "open_output": "Открыть папку результатов",
        "log": "Журнал",
        "ready": "Выберите файл инструкции и нажмите «Запустить».",
        "no_instruction": "Сначала выберите файл инструкции.",
        "missing_instruction": "Файл не найден.",
        "unsupported_instruction": (
            "Выберите файл инструкции .docx, .txt или .md."
        ),
        "no_spec": (
            "В инструкции нет задания, а ИИ в приложении не используется. "
            "Добавьте блок ```yaml со списком 'steps'."
        ),
        "done": "Готово: создано файлов — {count}.",
        "failed": "Ошибка: {error}",
        "select_instruction": "Выберите файл инструкции",
        "instruction_filter": "Инструкции",
        "all_files": "Все файлы",
        "cannot_open": "Не удалось открыть папку результатов: {error}",
        "no_output": "Сначала запустите задание.",
    },
}


def text(language: str, key: str, **values: Any) -> str:
    """A localised UI string; unknown keys and languages fall back to English."""

    table = STRINGS.get(language, STRINGS[DEFAULT_LANGUAGE])

    template = table.get(key) or STRINGS[DEFAULT_LANGUAGE].get(key, key)

    return template.format(**values) if values else template


def settings_path() -> Path:
    override = os.environ.get(SETTINGS_ENV, "").strip()

    if override:
        return Path(override).expanduser()

    return Path.home() / ".office-agent.json"


def load_settings() -> dict[str, Any]:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    return data if isinstance(data, dict) else {}


def save_settings(**values: Any) -> None:
    """Best-effort: a read-only home directory must not break the app."""

    settings = load_settings()

    settings.update(
        {
            key: value
            for key, value in values.items()
            if value is not None
        }
    )

    try:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def remembered_language() -> str:
    language = load_settings().get("language")

    if language in LANGUAGES:
        return str(language)

    return DEFAULT_LANGUAGE


def instruction_job_dir(instruction: Path) -> Path:
    """The job folder is the folder holding the instruction."""

    return Path(instruction).expanduser().resolve().parent


def default_output_dir(instruction: Path) -> Path:
    return instruction_job_dir(instruction) / "output"


def is_instruction_file(path: Path) -> bool:
    return Path(path).suffix.lower() in INSTRUCTION_SUFFIXES


def describe_state(state) -> list[str]:
    """One log line per executed step."""

    lines: list[str] = []

    for step_id, result in state.results.items():
        mark = "OK" if result.success else "FAILED"
        detail = result.message if result.success else (
            result.error or result.message
        )

        lines.append(f"[{mark}] {step_id}: {detail}")

    return lines

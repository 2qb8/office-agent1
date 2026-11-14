"""Localisation, paths and settings shared by the desktop front end.

This module is deliberately free of GUI imports so it can be tested and
reused without a display.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent import secrets
from agent.job import INSTRUCTION_SUFFIXES

APP_TITLE = "Office Agent"

LANGUAGES = {
    "en": "English",
    "ru": "Русский",
}

DEFAULT_LANGUAGE = "en"

SETTINGS_ENV = "OFFICE_AGENT_SETTINGS"

AI_FIELDS = ("provider", "base_url", "model", "api_key")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "subtitle": "An instruction document in, finished files out.",
        "document_section": "Document",
        "instruction": "Instruction file",
        "instruction_hint": "A .docx, .txt or .md document describing the job.",
        "output": "Output folder",
        "language": "Language",
        "browse": "Choose…",
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
            "This instruction has no 'steps' block, and no AI provider is "
            "configured. Add one, or fill in the AI planner section."
        ),
        "done": "Done — {count} file(s) created.",
        "failed": "Run failed: {error}",
        "select_instruction": "Select the instruction file",
        "instruction_filter": "Instructions",
        "all_files": "All files",
        "cannot_open": "Could not open the output folder: {error}",
        "no_output": "Run a job first.",
        "ai_section": "AI planner",
        "ai_hint": (
            "Optional. With a key the AI can plan instructions that are "
            "plain prose; instructions with a 'steps' block never call it."
        ),
        "provider": "Provider",
        "model": "Model",
        "endpoint": "Endpoint",
        "api_key": "API key",
        "test": "Test connection",
        "testing": "Contacting the model…",
        "ai_off": "Off — instructions must contain a 'steps' block.",
        "ai_ready": "Ready — {provider} · {model}",
        "ai_ok": "Connection OK — the model replied: {detail}",
        "ai_fail": "Connection failed: {detail}",
        "ai_needs_key": "{provider} needs an API key.",
        "ai_needs_endpoint": "Set an endpoint and a model first.",
        "planning_ai": "Planning with {provider} ({model})…",
        "spec_found": "Instruction contains a job spec; running it directly.",
        "settings_saved": "Settings are saved automatically.",
        "stop": "Stop",
        "stopping": "Stopping after this step…",
        "stopped": "Stopped — {count} file(s) created before stopping.",
        "review_plan": "Review the plan before running",
        "plan_title": "Plan for this instruction",
        "plan_goal": "Goal: {goal}",
        "plan_count": "Steps: {count}",
        "plan_start": "Run this plan",
        "plan_cancel": "Cancel",
        "copy_details": "Copy details",
        "copied": "Details copied to the clipboard.",
        "open_log": "Open run log",
        "no_log": "No run log yet.",
        "busy": "This folder is already running in another window.",
        "recent": "Recent",
        "recent_empty": "No recent instructions",
        "example": "Try an example",
        "example_copied": "Example copied to {path} — press Run.",
        "example_failed": "Could not copy the example: {error}",
    },
    "ru": {
        "subtitle": "Документ с инструкцией на входе — готовые файлы на выходе.",
        "document_section": "Документ",
        "instruction": "Файл инструкции",
        "instruction_hint": "Документ .docx, .txt или .md с описанием задачи.",
        "output": "Папка результатов",
        "language": "Язык",
        "browse": "Выбрать…",
        "run": "Запустить",
        "running": "Выполняется…",
        "open_output": "Открыть папку результатов",
        "log": "Журнал",
        "ready": "Выберите файл инструкции и нажмите «Запустить».",
        "no_instruction": "Сначала выберите файл инструкции.",
        "missing_instruction": "Файл не найден.",
        "unsupported_instruction": "Выберите файл инструкции .docx, .txt или .md.",
        "no_spec": (
            "В инструкции нет блока «steps», а ИИ не настроен. Добавьте "
            "блок в инструкцию или заполните раздел «ИИ-планировщик»."
        ),
        "done": "Готово — создано файлов: {count}.",
        "failed": "Ошибка: {error}",
        "select_instruction": "Выберите файл инструкции",
        "instruction_filter": "Инструкции",
        "all_files": "Все файлы",
        "cannot_open": "Не удалось открыть папку результатов: {error}",
        "no_output": "Сначала запустите задание.",
        "ai_section": "ИИ-планировщик",
        "ai_hint": (
            "Необязательно. С ключом ИИ планирует инструкции, написанные "
            "обычным текстом; если в инструкции есть блок «steps», ИИ не "
            "вызывается."
        ),
        "provider": "Провайдер",
        "model": "Модель",
        "endpoint": "Адрес API",
        "api_key": "Ключ API",
        "test": "Проверить связь",
        "testing": "Связываемся с моделью…",
        "ai_off": "Выключен — в инструкции нужен блок «steps».",
        "ai_ready": "Готово — {provider} · {model}",
        "ai_ok": "Связь есть — модель ответила: {detail}",
        "ai_fail": "Ошибка связи: {detail}",
        "ai_needs_key": "Для {provider} нужен ключ API.",
        "ai_needs_endpoint": "Сначала укажите адрес API и модель.",
        "planning_ai": "Планирование с {provider} ({model})…",
        "spec_found": "В инструкции есть задание — выполняем его напрямую.",
        "settings_saved": "Настройки сохраняются автоматически.",
        "stop": "Остановить",
        "stopping": "Останавливаемся после текущего шага…",
        "stopped": "Остановлено — создано файлов: {count}.",
        "review_plan": "Показывать план перед запуском",
        "plan_title": "План для этой инструкции",
        "plan_goal": "Цель: {goal}",
        "plan_count": "Шагов: {count}",
        "plan_start": "Выполнить план",
        "plan_cancel": "Отмена",
        "copy_details": "Копировать детали",
        "copied": "Детали скопированы в буфер обмена.",
        "open_log": "Открыть журнал выполнения",
        "no_log": "Журнала пока нет.",
        "busy": "Эта папка уже выполняется в другом окне.",
        "recent": "Недавние",
        "recent_empty": "Пока нет недавних инструкций",
        "example": "Попробовать пример",
        "example_copied": "Пример скопирован в {path} — нажмите «Запустить».",
        "example_failed": "Не удалось скопировать пример: {error}",
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
        return

    # The file may hold an API key, so keep it private to this user.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def remembered_language() -> str:
    language = load_settings().get("language")

    if language in LANGUAGES:
        return str(language)

    return DEFAULT_LANGUAGE


def remembered_ai() -> dict[str, str]:
    """Provider, endpoint, model and key saved by the window, if any."""

    stored = load_settings().get("ai")

    if not isinstance(stored, dict):
        return {}

    values = {
        field: str(stored.get(field) or "").strip()
        for field in AI_FIELDS
        if field != "api_key"
    }

    # Sealed with DPAPI on Windows, so copying the settings file to another
    # machine does not copy the key.
    values["api_key"] = secrets.unprotect(stored.get("api_key")).strip()

    return values


def save_ai(values: dict[str, str]) -> None:
    stored = {
        field: str(values.get(field) or "").strip()
        for field in AI_FIELDS
        if field != "api_key"
    }

    stored["api_key"] = secrets.protect(
        str(values.get("api_key") or "").strip()
    )

    save_settings(ai=stored)


RECENT_LIMIT = 5


def remembered_review() -> bool:
    """Whether the window shows the plan before running it."""

    value = load_settings().get("review_plan")

    return True if value is None else bool(value)


def save_review(enabled: bool) -> None:
    save_settings(review_plan=bool(enabled))


def remembered_recent() -> list[str]:
    stored = load_settings().get("recent")

    if not isinstance(stored, list):
        return []

    return [
        str(item)
        for item in stored
        if isinstance(item, str) and item.strip()
    ][:RECENT_LIMIT]


def remember_recent(instruction: Path) -> None:
    """Put this instruction at the top of the Recent list."""

    path = str(Path(instruction).expanduser().resolve())

    recent = [item for item in remembered_recent() if item != path]

    save_settings(recent=[path, *recent][:RECENT_LIMIT])


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

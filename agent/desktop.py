"""Run one chosen instruction: exactly what the window's Run button does.

Kept free of GUI imports so the desktop run path can be tested without
opening a window.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent import ai_config
from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from agent.ui import instruction_job_dir


FAILURE_WRAPPER = "All configured LLM models failed:"

# "gpt-4o-mini: HTTP 401: ...", "openrouter/model: HTTP 500: ..." and
# "gpt-4o-mini: gpt-4o-mini failed after 1 attempts: ..."
_MODEL_STATUS = re.compile(
    r"^[^:\s]+: (?=HTTP \d{3}|network error|[^:]*failed after \d+ attempts?: )"
)

# "gpt-4o-mini failed after 1 attempts: ..."
_MODEL_ATTEMPTS = re.compile(
    r"^[^:\s]+ failed after \d+ attempts?: "
)


def brief_error(detail: str) -> str:
    """One readable line, without the client's per-model wrapper.

    The client reports every attempted model, wrapped in a summary
    sentence and split over lines. The panel has one line, so the summary
    and the model-name prefixes are dropped while the HTTP status and the
    provider's own message are kept.
    """

    line = " ".join(str(detail).split())

    if line.startswith(FAILURE_WRAPPER):
        line = line[len(FAILURE_WRAPPER):].strip()

    line = _MODEL_STATUS.sub("", line)
    line = _MODEL_ATTEMPTS.sub("", line)

    return line.strip()


def test_ai_connection(
    values: dict[str, str],
) -> tuple[bool, str]:
    """Send one tiny request to the selected model; never raises.

    This is what the window's Test connection button runs, through the real
    HTTP client, so it reports what the planner would actually see.
    """

    try:
        ok, detail = ai_config.test_connection(
            ai_config.from_values(values)
        )

    except Exception as exc:  # reported in the window, never a crash
        return False, brief_error(str(exc))

    return ok, brief_error(detail)


def run_instruction(
    instruction: Path,
) -> tuple[str, Any, list[str]]:
    """Run one instruction file and report what happened.

    Returns ``(kind, payload, outputs)`` where kind is:

    * ``"done"``  — payload is the JobState, outputs are generated files
    * ``"nospec"`` — the instruction has no spec and no AI is configured
    * ``"error"`` — payload is the exception

    A job spec in the instruction always wins; when there is none, the
    runtime plans with the configured model, if any.
    """

    try:
        runtime = AgentRuntime(
            instruction_job_dir(instruction),
            build_registry(),
            instruction_path=instruction,
        )

        state = runtime.run()

        return "done", state, runtime.output_files(state)

    except SpecError:
        return "nospec", None, []

    except Exception as exc:  # surfaced in the window, not a crash
        return "error", exc, []

"""Run one chosen instruction: exactly what the window's Run button does.

Kept free of GUI imports so the desktop run path can be tested without
opening a window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent import ai_config
from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from agent.ui import describe_state, instruction_job_dir


def test_ai_connection(
    values: dict[str, str],
) -> ai_config.ConnectionCheck:
    """Send one tiny request to the selected model; never raises.

    This is what the window's Test connection button runs, through the real
    HTTP client, so it reports what the planner would actually see. The
    status and the provider's message arrive as fields; nothing here reads
    the client's wording.
    """

    try:
        return ai_config.test_connection(ai_config.from_values(values))

    except Exception as exc:  # reported in the window, never a crash
        return ai_config.ConnectionCheck(
            ok=False,
            detail=str(exc),
            kind="response",
        )


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


def self_test(instruction: Path) -> int:
    """Run one job with no window and report through the exit code.

    The windowed executable has no console, so this is how CI proves the
    frozen bundle can really run a job: bundled assets, the docx template,
    openpyxl's data files, Tk imports and the bootloader are all exercised.
    The details land in ``self-test.txt`` beside the instruction.
    """

    kind, payload, outputs = run_instruction(instruction)

    lines: list[str] = [f"result: {kind}"]

    if kind == "done":
        state = payload

        lines.append(f"status: {state.status.value}")
        lines.extend(describe_state(state))
        lines.extend(outputs)

        code = 0 if not state.failed_steps else 1

        if state.failed_steps:
            lines.append("failed: " + ", ".join(state.failed_steps))
    else:
        lines.append(f"detail: {payload}")
        code = 1

    try:
        report = instruction_job_dir(instruction) / "self-test.txt"
        report.write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    return code

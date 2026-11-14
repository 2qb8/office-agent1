"""Run one chosen instruction: exactly what the window's Run button does.

Kept free of GUI imports so the desktop run path can be tested without
opening a window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from agent.ui import instruction_job_dir


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

"""Run one chosen instruction: exactly what the window's Run button does.

Kept free of GUI imports so the desktop run path can be tested without
opening a window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent import ai_config
from agent.joblock import JobBusyError, JobLock
from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from agent.ui import describe_state, instruction_job_dir, is_instruction_file


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


def build_runtime(instruction: Path) -> AgentRuntime:
    """The runtime for the folder holding this instruction."""

    return AgentRuntime(
        instruction_job_dir(instruction),
        build_registry(),
        instruction_path=instruction,
    )


def plan_instruction(
    instruction: Path,
) -> tuple[AgentRuntime | None, str, Any]:
    """Build the plan without running it, for the window's preview.

    Returns ``(runtime, kind, payload)``; kind is ``"plan"`` and the payload
    is the JobPlan, or ``"nospec"`` / ``"error"`` exactly as
    :func:`run_instruction` reports them.
    """

    try:
        with JobLock(instruction_job_dir(instruction)):
            runtime = build_runtime(instruction)
            plan = runtime.plan()

        return runtime, "plan", plan

    except JobBusyError:
        return None, "busy", None

    except SpecError:
        return None, "nospec", None

    except Exception as exc:  # surfaced in the window, not a crash
        return None, "error", exc


def execute_plan(
    runtime: AgentRuntime,
    plan,
    progress=None,
    cancel=None,
) -> tuple[str, Any, list[str]]:
    """Run a plan built by :func:`plan_instruction`."""

    try:
        with JobLock(Path(runtime.job_path)):
            state = runtime.execute_plan(
                plan,
                progress=progress,
                cancel=cancel,
            )

        return "done", state, runtime.output_files(state)

    except JobBusyError:
        return "busy", None, []

    except Exception as exc:  # surfaced in the window, not a crash
        return "error", exc, []


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

    runtime, kind, payload = plan_instruction(instruction)

    if runtime is None or kind != "plan":
        return kind, payload, []

    return execute_plan(runtime, payload)


def _instruction_in(target: Path) -> Path | None:
    """The instruction file inside a job folder, if there is one."""

    if target.is_file():
        return target

    if not target.is_dir():
        return None

    for candidate in sorted(target.iterdir()):
        if candidate.is_file() and is_instruction_file(candidate):
            return candidate

    return None


def self_test(target: Path) -> int:
    """Run one job with no window and report through the exit code.

    The windowed executable has no console, so this is how CI proves the
    frozen bundle can really run a job: bundled assets, the docx template,
    openpyxl's data files, Tk imports and the bootloader are all exercised.

    ``target`` is an instruction file or the job folder holding one; the
    details land in ``self-test.txt`` in that job folder.
    """

    folder = Path(target).expanduser()

    instruction = _instruction_in(folder)

    if instruction is None:
        try:
            (folder / "self-test.txt").write_text(
                "result: no-instruction\n"
                f"looked in: {folder}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        return 1

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

"""Reading and writing plan.json: the plan a job actually runs.

A saved plan is reused only while the packet it was made from is unchanged.
The fingerprint covers the brief and the bytes of every packet file, so a
change anywhere in an attachment invalidates it — not just one the profile's
sample rows happen to show — and the job is planned again.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from agent.models import JobPlan
from agent.profile import fingerprint
from agent.spec import relativize_job_paths, resolve_job_paths

FILENAME = "plan.json"
FORMAT = 1

__all__ = ["FILENAME", "fingerprint", "load_plan", "save_plan"]


def save_plan(
    job_path: Path,
    plan: JobPlan,
    fingerprint_value: str,
    source: str = "manual",
    model: str | None = None,
    revisions: list[dict] | None = None,
) -> Path:
    """Write the plan beside the brief, with job-relative paths.

    Saving keeps the file portable: the same job folder can be copied to
    another machine and replayed without any of the absolute paths leaking
    into it.
    """

    job = Path(job_path)

    data = {
        "format": FORMAT,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "model": model,
        "fingerprint": fingerprint_value,
        "goal": plan.goal,
        "revisions": list(revisions or []),
        "steps": [
            {
                "id": step.id,
                "description": step.description,
                "tool": step.tool,
                "action": step.action,
                "arguments": relativize_job_paths(
                    step.arguments,
                    job,
                ),
                "depends_on": list(step.depends_on),
            }
            for step in plan.steps
        ],
    }

    path = job / FILENAME

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return path


def load_plan(
    job_path: Path,
    fingerprint_value: str,
) -> tuple[JobPlan | None, str, str]:
    """Return the saved plan when it still matches the packet.

    The other two values are the line for the log (so a run always says why
    it reused a plan or why it planned again) and the source recorded when
    the plan was saved, which decides whether a failure may be repaired.
    """

    path = Path(job_path) / FILENAME

    if not path.is_file():
        return None, "No saved plan", ""

    try:
        data = json.loads(
            path.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Saved plan is not readable: {exc}", ""

    if not isinstance(data, dict):
        return None, "Saved plan is not a JSON object", ""

    if str(data.get("fingerprint") or "") != fingerprint_value:
        return None, (
            "Saved plan is out of date: the brief or an input changed"
        ), ""

    steps = data.get("steps")

    if not isinstance(steps, list) or not steps:
        return None, "Saved plan has no steps", ""

    try:
        plan = JobPlan.model_validate(
            {
                "goal": str(data.get("goal") or "Saved plan"),
                "steps": steps,
            }
        )
    except Exception as exc:
        return None, f"Saved plan is not usable: {exc}", ""

    for step in plan.steps:
        step.arguments = resolve_job_paths(
            step.arguments,
            Path(job_path),
        )

    return plan, (
        "Using the saved plan from "
        f"{data.get('created') or 'an earlier run'}"
    ), str(data.get("source") or "saved")

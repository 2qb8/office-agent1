from __future__ import annotations

import json
from pathlib import Path

from agent.models import JobState


def save_state(
    state: JobState,
    path: Path,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(".tmp")

    temporary.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )

    temporary.replace(path)


def load_state(
    path: Path,
) -> JobState:
    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    return JobState.model_validate(data)
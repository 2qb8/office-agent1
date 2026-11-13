from __future__ import annotations

from datetime import datetime
from pathlib import Path


class JobLogger:
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        component: str,
        message: str,
    ) -> None:
        timestamp = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        line = (
            f"{timestamp}  "
            f"{component:<12}  "
            f"{message}"
        )

        print(line)

        with self.log_file.open(
            "a",
            encoding="utf-8",
        ) as file:
            file.write(line + "\n")
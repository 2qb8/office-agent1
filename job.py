from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


def create_job(
    job_path: Path,
) -> Path:
    """
    Prepare a job directory.

    Expected input:

        jobs/my-job/
            instruction.docx
            inputs/

    Creates:

        output/
        evidence/
    """

    job_path = job_path.resolve()

    if not job_path.exists():
        raise FileNotFoundError(
            f"Job directory does not exist: {job_path}"
        )

    instruction_files = [
        path
        for path in job_path.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".docx"
        and path.name.lower() != "instruction_template.docx"
    ]

    if not instruction_files:
        raise FileNotFoundError(
            "No instruction .docx found in the job directory."
        )

    if len(instruction_files) > 1:
        raise RuntimeError(
            "Multiple instruction DOCX files found: "
            + ", ".join(
                path.name
                for path in instruction_files
            )
        )

    (job_path / "output").mkdir(
        exist_ok=True
    )

    (job_path / "evidence").mkdir(
        exist_ok=True
    )

    (job_path / "inputs").mkdir(
        exist_ok=True
    )

    return job_path


def make_job_id(
    job_path: Path,
) -> str:

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    safe_name = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        job_path.name,
    ).strip("_")

    return f"{timestamp}_{safe_name}"
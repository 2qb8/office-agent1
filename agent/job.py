from __future__ import annotations

import re
from pathlib import Path


INSTRUCTION_SUFFIXES = {".docx", ".txt", ".md"}

IGNORED_INSTRUCTION_NAMES = {"instruction_template.docx"}


def find_instruction_file(
    job_path: Path,
    instruction_path: Path | None = None,
) -> Path:
    """
    Return the single instruction document in a job directory.

    A job holds exactly one instruction (.docx or .txt) plus an
    optional inputs/ directory. When instruction_path is given, that
    file is used instead of scanning the folder, which lets a UI run a
    chosen document from a folder that holds other documents too.
    """

    job_path = Path(job_path).resolve()

    if instruction_path is not None:
        candidate = Path(instruction_path).expanduser().resolve()

        if not candidate.is_file():
            raise FileNotFoundError(
                f"Instruction file not found: {candidate}"
            )

        if candidate.suffix.lower() not in INSTRUCTION_SUFFIXES:
            raise ValueError(
                "Instruction must be one of: "
                + ", ".join(sorted(INSTRUCTION_SUFFIXES))
            )

        return candidate

    if not job_path.exists():
        raise FileNotFoundError(
            f"Job directory does not exist: {job_path}"
        )

    if not job_path.is_dir():
        raise NotADirectoryError(
            f"Job path is not a directory: {job_path}"
        )

    files = [
        path
        for path in sorted(job_path.iterdir())
        if (
            path.is_file()
            and path.suffix.lower() in INSTRUCTION_SUFFIXES
            and path.name.lower()
            not in IGNORED_INSTRUCTION_NAMES
        )
    ]

    if not files:
        raise FileNotFoundError(
            "No instruction found in the job directory. "
            "Add one .docx (or .txt) describing the job, "
            "or create a job with: python run.py init <job-dir>"
        )

    if len(files) > 1:
        raise RuntimeError(
            "Multiple instruction files found: "
            + ", ".join(path.name for path in files)
            + ". Keep exactly one instruction in the job directory."
        )

    return files[0]


def create_job(
    job_path: Path,
    instruction_path: Path | None = None,
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

    job_path = Path(job_path).resolve()

    find_instruction_file(job_path, instruction_path)

    for name in ("output", "evidence", "inputs"):
        (job_path / name).mkdir(
            parents=True,
            exist_ok=True,
        )

    return job_path


def make_job_id(
    job_path: Path,
) -> str:
    from datetime import datetime

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    safe_name = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        Path(job_path).name,
    ).strip("_")

    return f"{timestamp}_{safe_name}"

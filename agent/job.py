from __future__ import annotations

import re
from pathlib import Path


INSTRUCTION_SUFFIXES = {".docx", ".txt", ".md"}

IGNORED_INSTRUCTION_NAMES = {"instruction_template.docx"}

# A file named like the task is the task. Everything else beside it is the
# material that came with it.
BRIEF_STEMS = {
    "instruction",
    "instructions",
    "brief",
    "task",
    "assignment",
}


def brief_candidates(job_path: Path) -> list[Path]:
    """Every document in the job folder that could be the brief."""

    job_path = Path(job_path).resolve()

    if not job_path.is_dir():
        return []

    return [
        path
        for path in sorted(job_path.iterdir())
        if (
            path.is_file()
            and path.suffix.lower() in INSTRUCTION_SUFFIXES
            and path.name.lower() not in IGNORED_INSTRUCTION_NAMES
        )
    ]


def find_instruction_file(
    job_path: Path,
    instruction_path: Path | None = None,
) -> Path:
    """
    Return the brief for a job: the chosen file, or the best candidate.

    A work packet is often just a folder somebody handed over — the task
    plus a couple of Word and Excel files beside it. So several documents
    are not an error: a file named instruction/brief/task wins, then the
    longest document does, and every other file is treated as packet
    content the planner may read. When instruction_path is given, that file
    is the brief, which is how the window runs a chosen document from a
    folder that holds others too.
    """

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

    job_path = Path(job_path).resolve()

    if not job_path.exists():
        raise FileNotFoundError(
            f"Job directory does not exist: {job_path}"
        )

    if not job_path.is_dir():
        raise NotADirectoryError(
            f"Job path is not a directory: {job_path}"
        )

    files = brief_candidates(job_path)

    if not files:
        raise FileNotFoundError(
            "No brief found in the job directory. Add one .docx (or .txt "
            "or .md) describing the job, or create a job with: "
            "python run.py init <job-dir>"
        )

    return choose_brief(files)


def choose_brief(files: list[Path]) -> Path:
    """The brief among several documents: by name, then by how much says it."""

    named = [
        path
        for path in files
        if path.stem.casefold() in BRIEF_STEMS
    ]

    pool = named or files

    return sorted(
        pool,
        key=lambda path: (-_brief_weight(path), path.name.casefold()),
    )[0]


def _brief_weight(path: Path) -> int:
    """How many characters of actual text a candidate holds."""

    from agent.instructions import read_document

    try:
        return len(read_document(path).strip())
    except Exception:
        return 0


def create_job(
    job_path: Path,
    instruction_path: Path | None = None,
) -> Path:
    """
    Prepare a job directory.

    Expected input:

        jobs/my-job/
            instruction.docx     the brief
            inputs/              the rest of the packet

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

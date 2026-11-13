from __future__ import annotations

from pathlib import Path

from agent.instructions import read_document
from agent.models import JobInstruction


def load_instruction(
    path: Path,
) -> JobInstruction:
    """Read an instruction DOCX/TXT into a JobInstruction."""

    path = Path(path)

    text = read_document(path)

    if not text.strip():
        raise ValueError(
            f"Instruction file is empty: {path}"
        )

    return JobInstruction(
        source_file=str(path.resolve()),
        text=text,
        character_count=len(text),
        word_count=len(text.split()),
    )

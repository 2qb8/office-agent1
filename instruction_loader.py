from __future__ import annotations

from pathlib import Path

from agent.instructions import read_docx
from agent.models import JobInstruction


def load_instruction(
    path: Path,
) -> JobInstruction:

    text = read_docx(path)

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
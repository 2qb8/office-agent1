from __future__ import annotations

from pathlib import Path

from docx import Document


def read_docx(path: Path) -> str:
    """
    Extract readable text from a DOCX file.

    Paragraphs and table cells are included.
    """

    path = path.resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Instruction file not found: {path}"
        )

    if path.suffix.lower() != ".docx":
        raise ValueError(
            f"Expected DOCX file, got: {path.suffix}"
        )

    document = Document(path)

    parts: list[str] = []

    # Normal paragraphs
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if text:
            parts.append(text)

    # Tables
    for table in document.tables:
        for row in table.rows:
            cells = [
                cell.text.strip()
                for cell in row.cells
            ]

            parts.append(
                " | ".join(cells)
            )

    return "\n".join(parts)
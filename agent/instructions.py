from __future__ import annotations

from pathlib import Path

from docx import Document


TEXT_SUFFIXES = {".txt", ".md", ".yaml", ".yml", ".json"}


def read_docx(path: Path) -> str:
    """
    Extract readable text from a DOCX file.

    Paragraphs are returned in document order. Table rows are appended
    as pipe-separated lines so their content stays visible.
    """

    path = Path(path).resolve()

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

    # Leading whitespace is significant: it carries the YAML/JSON
    # indentation of a spec block.
    for paragraph in document.paragraphs:
        text = paragraph.text.rstrip()

        if text.strip():
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [
                cell.text.strip()
                for cell in row.cells
            ]

            parts.append(" | ".join(cells))

    return "\n".join(parts)


def read_text_file(path: Path) -> str:
    """Read a plain-text instruction file (UTF-8, BOM tolerated)."""

    path = Path(path).resolve()

    if not path.exists():
        raise FileNotFoundError(
            f"Instruction file not found: {path}"
        )

    return path.read_text(encoding="utf-8-sig")


def read_document(path: Path) -> str:
    """Read an instruction document of any supported format."""

    path = Path(path)

    suffix = path.suffix.lower()

    if suffix == ".docx":
        return read_docx(path)

    if suffix in TEXT_SUFFIXES:
        return read_text_file(path)

    if suffix == ".doc":
        raise ValueError(
            "Legacy .doc files are not supported. "
            "Save the instruction as .docx."
        )

    raise ValueError(
        "Unsupported instruction format "
        f"'{suffix}'. Use .docx or .txt."
    )

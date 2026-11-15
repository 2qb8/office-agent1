"""A deterministic look at the work packet, for the planner.

The planner is given the brief and this profile instead of the raw files:
the profile caps how much text a large packet can spend on one model call,
and it keeps a planning request identical whether it goes to an API or is
copied into a web chatbot.

It is also what a saved plan is checked against, so it carries a SHA-256 of
every file's bytes next to the capped description: the caps keep one call
affordable, and the digests make sure a change the caps hide — a cell past
the sampled rows, text past the character limit — still invalidates a plan.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import load_workbook

from agent.instructions import read_document

# Enough to see the shape of a file without paying for all of it.
PER_FILE_CHARS = 4000
TOTAL_CHARS = 30000
SAMPLE_ROWS = 5
TABLE_SAMPLE_ROWS = 6
TEXT_LINES = 40
CELL_CHARS = 60
ROW_VALUES = 12
DIGEST_CHUNK = 1024 * 1024

EXCEL_SUFFIXES = {".xlsx", ".xlsm"}
WORD_SUFFIXES = {".docx"}
TABLE_SUFFIXES = {".csv", ".tsv"}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml", ".log", ".xml"}

SUPPORTED_SUFFIXES = (
    EXCEL_SUFFIXES
    | WORD_SUFFIXES
    | TABLE_SUFFIXES
    | TEXT_SUFFIXES
)

# Files a job writes beside itself; they are never packet content.
JOB_FILES = {
    "run.log",
    "report.json",
    "state.json",
    "plan.json",
    "plan-request.md",
    "self-test.txt",
    "instruction_template.docx",
}


def profile_packet(
    job_path: Path,
    brief_path: Path | None = None,
) -> dict[str, Any]:
    """Profile the brief and every file that travels with it.

    The brief is never repeated in ``files``, so the planner cannot mistake
    the task assignment for an input. Each entry carries what the planner
    needs to name sheets, columns, cells and paths: Word paragraphs and
    tables, Excel headers and sample rows, the head of a text or CSV file.
    """

    job = Path(job_path).resolve()

    brief = (
        Path(brief_path).expanduser().resolve()
        if brief_path is not None
        else None
    )

    files: list[dict[str, Any]] = []
    budget = TOTAL_CHARS
    truncated = False

    for path in packet_files(job, brief):
        entry = _file_entry(path, job)

        rendered = len(
            json.dumps(entry, ensure_ascii=False, default=str)
        )

        if rendered > budget:
            entry = {
                "path": _relative(path, job) or str(path),
                "name": path.name,
                "type": _kind(path),
                "bytes": _size(path),
                "digest": entry.get("digest"),
                "note": (
                    "not shown: the packet is already larger than the "
                    "planner budget"
                ),
            }
            truncated = True
        else:
            budget -= rendered

        files.append(entry)

    return {
        "brief": _brief_entry(job, brief),
        "files": files,
        "totals": {
            "files": len(files),
            "characters": TOTAL_CHARS - budget,
            "truncated": truncated,
        },
    }


def packet_files(
    job_path: Path,
    brief_path: Path | None = None,
) -> list[Path]:
    """Every file in the packet: everything under inputs/, plus loose
    files beside the brief.

    That is how a folder someone hands over usually looks: the assignment
    at the top and the material next to it, not filed away in a subfolder.
    """

    job = Path(job_path).resolve()

    brief = (
        Path(brief_path).resolve()
        if brief_path is not None
        else None
    )

    found: list[Path] = []

    inputs = job / "inputs"

    if inputs.is_dir():
        found.extend(
            path
            for path in sorted(inputs.rglob("*"))
            if path.is_file()
            and not path.name.startswith(".")
            and not path.name.startswith("~$")
        )

    if job.is_dir():
        for path in sorted(job.iterdir()):
            if not path.is_file():
                continue

            if path.name.startswith(".") or path.name in JOB_FILES:
                continue

            if brief is not None and path.resolve() == brief:
                continue

            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue

            found.append(path)

    return found


def fingerprint(profile: dict[str, Any]) -> str:
    """A stable hash of the brief, every packet file's bytes and the profile.

    The digests inside the profile are what make this honest: two packets
    whose capped descriptions look identical but whose files differ at the
    ninetieth row still hash differently.
    """

    payload = json.dumps(
        profile,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# One entry per file
# ----------------------------------------------------------------------


def _brief_entry(
    job: Path,
    brief: Path | None,
) -> dict[str, Any] | None:
    if brief is None or not brief.is_file():
        return None

    try:
        text = read_document(brief)
    except Exception as exc:  # reported in the profile, never fatal
        return {
            "name": brief.name,
            "path": _relative(brief, job) or str(brief),
            "error": f"could not read this brief: {exc}",
        }

    return {
        "name": brief.name,
        "path": _relative(brief, job) or str(brief),
        "characters": len(text),
        "words": len(text.split()),
        "digest": _digest(brief),
        "text": _cap(text.strip(), PER_FILE_CHARS),
    }


def _file_entry(path: Path, job: Path) -> dict[str, Any]:
    kind = _kind(path)

    entry: dict[str, Any] = {
        "path": _relative(path, job) or str(path),
        "name": path.name,
        "type": kind,
        "bytes": _size(path),
        "digest": _digest(path),
    }

    try:
        if kind == "word":
            entry.update(_word_details(path))
        elif kind == "excel":
            entry.update(_excel_details(path))
        elif kind == "table":
            entry.update(_table_details(path))
        else:
            entry.update(_text_details(path))
    except Exception as exc:  # one unreadable file must not stop a plan
        entry["error"] = f"could not read this file: {exc}"

    return entry


def _word_details(path: Path) -> dict[str, Any]:
    document = Document(path)

    paragraphs = [
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    ]

    tables: list[dict[str, Any]] = []

    for table in document.tables[:5]:
        rows = [
            [cell.text.strip() for cell in row.cells]
            for row in table.rows
        ]

        tables.append(
            {
                "rows": len(rows),
                "columns": len(rows[0]) if rows else 0,
                "header": _trim_values(rows[0]) if rows else [],
                "sample_rows": [
                    _trim_values(row)
                    for row in rows[1:TABLE_SAMPLE_ROWS + 1]
                ],
            }
        )

    return {
        "paragraphs": len(paragraphs),
        "text": _cap("\n".join(paragraphs), PER_FILE_CHARS),
        "tables": tables,
    }


def _excel_details(path: Path) -> dict[str, Any]:
    workbook = load_workbook(
        path,
        read_only=True,
        data_only=False,
    )

    sheets: list[dict[str, Any]] = []

    try:
        for worksheet in workbook.worksheets[:10]:
            headers: list[Any] = []

            if worksheet.max_row >= 1:
                first = next(
                    worksheet.iter_rows(min_row=1, max_row=1),
                    (),
                )
                headers = _trim_values(
                    [cell.value for cell in first]
                )

            sample_rows = [
                _trim_values(list(row))
                for row in worksheet.iter_rows(
                    min_row=2,
                    max_row=min(
                        worksheet.max_row,
                        SAMPLE_ROWS + 1,
                    ),
                    values_only=True,
                )
            ]

            sheets.append(
                {
                    "name": worksheet.title,
                    "rows": worksheet.max_row,
                    "columns": worksheet.max_column,
                    "headers": headers,
                    "sample_rows": sample_rows,
                    "has_formulas": _has_formulas(worksheet),
                }
            )
    finally:
        workbook.close()

    return {"sheets": sheets}


def _has_formulas(worksheet) -> bool:
    for row in worksheet.iter_rows(
        max_row=min(worksheet.max_row, 25),
        values_only=True,
    ):
        for value in row:
            if isinstance(value, str) and value.startswith("="):
                return True

    return False


def _table_details(path: Path) -> dict[str, Any]:
    text = _read_text(path)

    delimiter = _delimiter(text)

    rows = list(
        csv.reader(io.StringIO(text), delimiter=delimiter)
    )

    return {
        "delimiter": delimiter,
        "rows": len(rows),
        "columns": len(rows[0]) if rows else 0,
        "header": _trim_values(rows[0]) if rows else [],
        "sample_rows": [
            _trim_values(row)
            for row in rows[1:TABLE_SAMPLE_ROWS + 1]
        ],
    }


def _text_details(path: Path) -> dict[str, Any]:
    text = _read_text(path)

    lines = text.splitlines()

    return {
        "lines": len(lines),
        "text": _cap(
            "\n".join(lines[:TEXT_LINES]),
            PER_FILE_CHARS,
        ),
    }


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix in WORD_SUFFIXES:
        return "word"

    if suffix in EXCEL_SUFFIXES:
        return "excel"

    if suffix in TABLE_SUFFIXES:
        return "table"

    if suffix in TEXT_SUFFIXES:
        return "text"

    return "other"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(
            "\n".join(text.splitlines()[:5])
        ).delimiter
    except (csv.Error, IndexError):
        return ","


def _trim_values(values: list[Any]) -> list[Any]:
    trimmed: list[Any] = []

    for value in values[:ROW_VALUES]:
        if isinstance(value, str):
            trimmed.append(_cap(value.strip(), CELL_CHARS))
        else:
            trimmed.append(value)

    return trimmed


def _cap(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value

    return value[:limit].rstrip() + "\n… (truncated)"


def _relative(path: Path, job: Path) -> str | None:
    try:
        return Path(path).resolve().relative_to(job).as_posix()
    except ValueError:
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _digest(path: Path) -> str:
    """SHA-256 of the whole file, in chunks so a big workbook is fine."""

    digest = hashlib.sha256()

    try:
        with path.open("rb") as handle:
            for block in iter(
                lambda: handle.read(DIGEST_CHUNK),
                b"",
            ):
                digest.update(block)
    except OSError:
        return ""

    return digest.hexdigest()

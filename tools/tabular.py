from __future__ import annotations

import csv
import io
from typing import Any


class TableError(ValueError):
    """Raised when tabular arguments are malformed."""


def normalize_table(
    headers: Any,
    rows: Any,
) -> tuple[list[str], list[list[Any]]]:
    """
    Validate a headers/rows pair and return it in canonical form.

    Rows may be lists (positional) or objects (looked up by header name).
    """

    if not isinstance(headers, list) or not headers:
        raise TableError("'headers' must be a non-empty list.")

    header_names = [str(header) for header in headers]

    if not isinstance(rows, list):
        raise TableError("'rows' must be a list.")

    normalized: list[list[Any]] = []

    for index, row in enumerate(rows, start=1):
        if isinstance(row, dict):
            values = [
                row.get(header)
                for header in header_names
            ]
        elif isinstance(row, (list, tuple)):
            values = list(row)

            if len(values) != len(header_names):
                raise TableError(
                    f"Row {index} has {len(values)} values but "
                    f"there are {len(header_names)} headers."
                )
        else:
            raise TableError(
                f"Row {index} must be a list or an object."
            )

        normalized.append(values)

    return header_names, normalized


def is_blank(value: Any) -> bool:
    """True for empty cells, including whitespace-only strings."""

    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    return False


def shape_table(
    matrix: list[list[Any]],
    header_row: int = 1,
    max_rows: int | None = None,
) -> tuple[list[str], list[list[Any]]]:
    """
    Turn a raw cell matrix into headers plus data rows.

    Shared by excel.read_table and word.read_table so DOCX and XLSX
    tables behave identically: blank trailing rows and cells are dropped,
    short rows are padded, headers are strings, and the header row is
    validated.
    """

    header_row = int(header_row)

    if header_row < 1:
        raise TableError("'header_row' must be 1 or more.")

    rows_matrix = [list(row) for row in matrix]

    while rows_matrix and all(
        is_blank(value) for value in rows_matrix[-1]
    ):
        rows_matrix.pop()

    if len(rows_matrix) < header_row:
        raise TableError(
            f"the table has no row {header_row}."
        )

    headers = [
        "" if is_blank(value) else str(value)
        for value in rows_matrix[header_row - 1]
    ]

    while headers and not headers[-1]:
        headers.pop()

    if not headers:
        raise TableError(
            f"row {header_row} is empty; cannot determine headers."
        )

    rows: list[list[Any]] = []

    for raw_row in rows_matrix[header_row:]:
        values = list(raw_row)

        while values and is_blank(values[-1]):
            values.pop()

        if not values:
            continue

        if len(values) < len(headers):
            values = values + [None] * (
                len(headers) - len(values)
            )

        rows.append(values[: len(headers)])

    if max_rows is not None:
        max_rows = int(max_rows)

        if max_rows < 1:
            raise TableError("'max_rows' must be 1 or more.")

        rows = rows[:max_rows]

    return headers, rows


def format_cell(value: Any) -> str:
    """Render a cell value for text output without float noise."""

    if value is None:
        return ""

    if isinstance(value, bool):
        return str(value)

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value)


def to_number(value: Any) -> float | None:
    """Best-effort numeric conversion used for comparisons and maths."""

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if value is None:
        return None

    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def render_markdown_table(
    headers: list[str],
    rows: list[list[Any]],
) -> str:
    def cell(value: Any) -> str:
        return format_cell(value).replace("|", "\\|")

    lines = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for row in rows:
        lines.append(
            "| " + " | ".join(cell(value) for value in row) + " |"
        )

    return "\n".join(lines)


def render_csv(
    headers: list[str],
    rows: list[list[Any]],
    delimiter: str = ",",
) -> str:
    buffer = io.StringIO()

    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")

    writer.writerow(headers)

    for row in rows:
        writer.writerow(
            [format_cell(value) for value in row]
        )

    return buffer.getvalue()


def render_tsv(
    headers: list[str],
    rows: list[list[Any]],
) -> str:
    return render_csv(headers, rows, delimiter="\t")


def render_records(
    headers: list[str],
    rows: list[list[Any]],
) -> list[dict[str, Any]]:
    return [
        {
            header: value
            for header, value in zip(headers, row)
        }
        for row in rows
    ]

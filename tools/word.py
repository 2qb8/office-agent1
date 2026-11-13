from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches

from agent.metadata import (
    apply_to_document,
    read_document_metadata,
    resolve as resolve_metadata,
)
from agent.models import ToolResult
from tools.base import Tool
from tools.tabular import (
    TableError,
    format_cell,
    shape_table,
)


class WordTool(Tool):
    name = "word"

    actions = (
        "create_document",
        "append_elements",
        "replace_text",
        "set_metadata",
        "append_image",
        "read_table",
        "inspect",
        "export_text",
        "verify_document",
    )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "create_document":
            return self._create_document(arguments)

        if action == "append_elements":
            return self._append_elements(arguments)

        if action == "replace_text":
            return self._replace_text(arguments)

        if action == "set_metadata":
            return self._set_metadata(arguments)

        if action == "append_image":
            return self._append_image(arguments)

        if action == "read_table":
            return self._read_table(arguments)

        if action == "inspect":
            return self._inspect(arguments)

        if action == "export_text":
            return self._export_text(arguments)

        if action == "verify_document":
            return self._verify_document(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown word action: {action}",
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def _create_document(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_output_path = arguments.get("output_path")

        if not raw_output_path:
            return ToolResult(
                success=False,
                error="create_document requires 'output_path'.",
            )

        output_path = Path(str(raw_output_path)).resolve()

        if output_path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error=f"Output must be DOCX: {output_path}",
            )

        elements = arguments.get("elements", [])

        if not isinstance(elements, list):
            return ToolResult(
                success=False,
                error="'elements' must be a list.",
            )

        document = Document()

        try:
            for element in elements:
                self._add_element(document, element)

            apply_to_document(
                document,
                resolve_metadata(arguments.get("metadata")),
            )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            document.save(output_path)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to create Word document: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Created Word document: {output_path.name}",
            data={
                "path": str(output_path),
                "size_bytes": output_path.stat().st_size,
                "element_count": len(elements),
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def _append_elements(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path")

        if not raw_path:
            return ToolResult(
                success=False,
                error="append_elements requires 'path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document not found: {path}",
            )

        if path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error=f"Expected DOCX file: {path}",
            )

        elements = arguments.get("elements", [])

        if not isinstance(elements, list) or not elements:
            return ToolResult(
                success=False,
                error="'elements' must be a non-empty list.",
            )

        raw_output = arguments.get("output_path")

        output_path = (
            Path(str(raw_output)).resolve()
            if raw_output
            else path
        )

        try:
            document = Document(path)

            for element in elements:
                self._add_element(document, element)

            if "metadata" in arguments:
                apply_to_document(
                    document,
                    resolve_metadata(arguments.get("metadata")),
                )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            document.save(output_path)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to append to Word document: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Appended {len(elements)} elements to "
                f"{output_path.name}"
            ),
            data={
                "path": str(output_path),
                "source": str(path),
                "size_bytes": output_path.stat().st_size,
                "element_count": len(elements),
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Read table
    # ------------------------------------------------------------------

    def _read_table(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """
        Read one DOCX table as headers plus rows.

        The result has the same shape as excel.read_table, so a DOCX
        table can feed an XLSX, CSV, Markdown or Word output directly.
        Merged cells repeat the merged text in every covered column.
        """

        raw_path = arguments.get("path")

        if not raw_path:
            return ToolResult(
                success=False,
                error="read_table requires 'path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document does not exist: {path}",
            )

        if path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error=f"Expected DOCX file: {path}",
            )

        try:
            table_index = int(arguments.get("table", 0))

            document = Document(path)

            table_count = len(document.tables)

            if not table_count:
                raise ValueError(
                    f"Document has no tables: {path.name}"
                )

            if not 0 <= table_index < table_count:
                raise ValueError(
                    f"Table index {table_index} is out of range; "
                    f"{path.name} has {table_count} table(s)."
                )

            matrix = [
                [cell.text.strip() for cell in row.cells]
                for row in document.tables[table_index].rows
            ]

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read Word table: {exc}",
            )

        try:
            headers, rows = shape_table(
                matrix,
                header_row=arguments.get("header_row", 1),
                max_rows=arguments.get("max_rows"),
            )
        except TableError as exc:
            return ToolResult(
                success=False,
                error=(
                    f"Failed to read table {table_index} of "
                    f"{path.name}: {exc}"
                ),
            )

        return ToolResult(
            success=True,
            message=(
                f"Read {len(rows)} rows from {path.name} "
                f"table {table_index}"
            ),
            data={
                "path": str(path),
                "table": table_index,
                "table_count": table_count,
                "headers": headers,
                "rows": rows,
                "row_count": len(rows),
                "column_count": len(headers),
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Inspect
    # ------------------------------------------------------------------

    def _inspect(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = (
            arguments.get("path")
            or arguments.get("output_path")
        )

        if not raw_path:
            return ToolResult(
                success=False,
                error="inspect requires 'path' or 'output_path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document does not exist: {path}",
            )

        if path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error=f"Expected DOCX file: {path}",
            )

        try:
            document = Document(path)

            paragraphs = [
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]

            tables = [
                [
                    [cell.text for cell in row.cells]
                    for row in table.rows
                ]
                for table in document.tables
            ]

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to inspect Word document: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Inspected Word document: {path.name}",
            data={
                "path": str(path),
                "paragraphs": paragraphs,
                "tables": tables,
                "paragraph_count": len(paragraphs),
                "table_count": len(tables),
                "metadata": read_document_metadata(document),
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Export text
    # ------------------------------------------------------------------

    def _export_text(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path")

        if not raw_path:
            return ToolResult(
                success=False,
                error="export_text requires 'path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document does not exist: {path}",
            )

        raw_output = arguments.get("output_path")

        output_path = (
            Path(str(raw_output)).resolve()
            if raw_output
            else path.with_suffix(".txt")
        )

        include_tables = bool(
            arguments.get("include_tables", True)
        )

        try:
            document = Document(path)

            lines = [
                paragraph.text.rstrip()
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]

            if include_tables:
                for table in document.tables:
                    lines.append("")

                    for row in table.rows:
                        cells = [
                            cell.text.strip()
                            for cell in row.cells
                        ]

                        lines.append("| " + " | ".join(cells) + " |")

            content = "\n".join(lines)

            if not content.endswith("\n"):
                content += "\n"

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            output_path.write_text(
                content,
                encoding="utf-8",
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to export Word text: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Exported {path.name} to {output_path.name}"
            ),
            data={
                "path": str(output_path),
                "source": str(path),
                "size_bytes": output_path.stat().st_size,
                "line_count": len(content.splitlines()),
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def _verify_document(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = (
            arguments.get("path")
            or arguments.get("output_path")
        )

        if not raw_path:
            return ToolResult(
                success=False,
                error="verify_document requires 'path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document does not exist: {path}",
            )

        expected = arguments.get("expected", {})

        if not isinstance(expected, dict):
            return ToolResult(
                success=False,
                error="'expected' must be an object.",
            )

        try:
            document = Document(path)

            actual_paragraphs = [
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            ]

            actual_tables = [
                [
                    [cell.text for cell in row.cells]
                    for row in table.rows
                ]
                for table in document.tables
            ]

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read Word document: {exc}",
            )

        expected_paragraphs = expected.get("paragraphs", [])
        expected_tables = expected.get("tables", [])

        mismatches: list[dict[str, Any]] = []

        if expected_paragraphs and (
            actual_paragraphs
            != [str(text) for text in expected_paragraphs]
        ):
            mismatches.append(
                {
                    "type": "paragraphs",
                    "expected": expected_paragraphs,
                    "actual": actual_paragraphs,
                }
            )

        for index, expected_table in enumerate(
            expected_tables
        ):
            expected_headers = expected_table.get(
                "headers",
                [],
            )

            expected_rows = expected_table.get(
                "rows",
                [],
            )

            expected_matrix = [
                [str(value) for value in expected_headers],
                *[
                    [str(value) for value in row]
                    for row in expected_rows
                ],
            ]

            if index >= len(actual_tables):
                mismatches.append(
                    {
                        "type": "missing_table",
                        "table_index": index,
                        "expected": expected_matrix,
                    }
                )
                continue

            if actual_tables[index] != expected_matrix:
                mismatches.append(
                    {
                        "type": "table",
                        "table_index": index,
                        "expected": expected_matrix,
                        "actual": actual_tables[index],
                    }
                )

        success = not mismatches

        return ToolResult(
            success=success,
            message=(
                f"Verified Word document content: {path.name}"
                if success
                else f"Word document verification failed: {path.name}"
            ),
            data={
                "path": str(path),
                "verified": success,
                "actual_paragraphs": actual_paragraphs,
                "actual_tables": actual_tables,
                "mismatches": mismatches,
            },
            evidence=[str(path)],
            error=None if success else "Content mismatch.",
        )

    # ------------------------------------------------------------------
    # Replace text (template placeholders)
    # ------------------------------------------------------------------

    def _replace_text(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path")
        replacements = arguments.get("replacements")

        if not raw_path:
            return ToolResult(
                success=False,
                error="replace_text requires 'path'.",
            )

        if not isinstance(replacements, dict) or not replacements:
            return ToolResult(
                success=False,
                error=(
                    "replace_text requires a non-empty 'replacements' "
                    "object mapping placeholders to values."
                ),
            )

        mapping = {
            str(key): str(value)
            for key, value in replacements.items()
        }

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document not found: {path}",
            )

        if path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error=f"Expected DOCX file: {path}",
            )

        raw_output = arguments.get("output_path")

        output_path = (
            Path(str(raw_output)).resolve()
            if raw_output
            else path
        )

        counts = {key: 0 for key in mapping}

        try:
            document = Document(path)

            for paragraph in iter_paragraphs(document):
                replace_in_paragraph(
                    paragraph,
                    mapping,
                    counts,
                )

            if "metadata" in arguments:
                apply_to_document(
                    document,
                    resolve_metadata(arguments.get("metadata")),
                )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            document.save(output_path)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to replace text: {exc}",
            )

        total = sum(counts.values())

        return ToolResult(
            success=True,
            message=(
                f"Replaced {total} occurrence(s) in "
                f"{output_path.name}"
            ),
            data={
                "path": str(output_path),
                "source": str(path),
                "replacements": counts,
                "total": total,
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _set_metadata(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path")
        raw_metadata = arguments.get("metadata")

        if not raw_path:
            return ToolResult(
                success=False,
                error="set_metadata requires 'path'.",
            )

        if not isinstance(raw_metadata, dict) or not raw_metadata:
            return ToolResult(
                success=False,
                error=(
                    "set_metadata requires a non-empty 'metadata' "
                    "object."
                ),
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document not found: {path}",
            )

        raw_output = arguments.get("output_path")

        output_path = (
            Path(str(raw_output)).resolve()
            if raw_output
            else path
        )

        try:
            values = resolve_metadata(
                raw_metadata,
                use_defaults=False,
            )

            document = Document(path)

            apply_to_document(document, values)

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            document.save(output_path)

            updated = read_document_metadata(document)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to set metadata: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Updated metadata of {output_path.name}",
            data={
                "path": str(output_path),
                "metadata": updated,
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def _append_image(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path")
        raw_image = arguments.get("image_path")

        if not raw_path or not raw_image:
            return ToolResult(
                success=False,
                error=(
                    "append_image requires 'path' and 'image_path'."
                ),
            )

        path = Path(str(raw_path)).resolve()
        image_path = Path(str(raw_image)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Word document not found: {path}",
            )

        if not image_path.is_file():
            return ToolResult(
                success=False,
                error=f"Image not found: {image_path}",
            )

        raw_output = arguments.get("output_path")

        output_path = (
            Path(str(raw_output)).resolve()
            if raw_output
            else path
        )

        caption = arguments.get("caption")

        try:
            document = Document(path)

            width = arguments.get("width_inches")

            if width is not None:
                document.add_picture(
                    str(image_path),
                    width=Inches(float(width)),
                )
            else:
                document.add_picture(str(image_path))

            if caption:
                paragraph = document.add_paragraph(str(caption))
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

            if "metadata" in arguments:
                apply_to_document(
                    document,
                    resolve_metadata(arguments.get("metadata")),
                )

            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            document.save(output_path)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to append image: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Added {image_path.name} to {output_path.name}"
            ),
            data={
                "path": str(output_path),
                "source": str(path),
                "image": str(image_path),
                "caption": str(caption) if caption else "",
                "size_bytes": output_path.stat().st_size,
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Element rendering
    # ------------------------------------------------------------------

    def _add_element(
        self,
        document: Document,
        element: dict[str, Any],
    ) -> None:

        if not isinstance(element, dict):
            raise ValueError(
                "Each Word element must be an object."
            )

        element_type = element.get("type")

        if element_type == "heading":
            document.add_heading(
                str(element.get("text", "")),
                level=int(element.get("level", 1)),
            )
            return

        if element_type == "paragraph":
            document.add_paragraph(
                str(element.get("text", ""))
            )
            return

        if element_type == "page_break":
            document.add_page_break()
            return

        if element_type in {"bullet_list", "numbered_list"}:
            items = element.get("items", [])

            if not isinstance(items, list):
                raise ValueError(
                    f"'{element_type}' requires an 'items' list."
                )

            style = (
                "List Bullet"
                if element_type == "bullet_list"
                else "List Number"
            )

            for item in items:
                document.add_paragraph(str(item), style=style)

            return

        if element_type == "table":
            self._add_table(document, element)
            return

        raise ValueError(
            f"Unknown Word element type: {element_type}"
        )

    @staticmethod
    def _add_table(
        document: Document,
        element: dict[str, Any],
    ) -> None:

        headers = element.get("headers", [])
        rows = element.get("rows", [])

        if not headers:
            raise ValueError(
                "Table requires a non-empty 'headers' list."
            )

        header_cells = [format_cell(header) for header in headers]

        table = document.add_table(
            rows=1,
            cols=len(header_cells),
        )

        table.style = "Table Grid"

        for index, header in enumerate(header_cells):
            table.rows[0].cells[index].text = header

        for row in rows:

            if not isinstance(row, (list, tuple)):
                raise ValueError(
                    "Each table row must be a list."
                )

            if len(row) != len(header_cells):
                raise ValueError(
                    "Table row length does not match header count: "
                    f"{len(row)} values for {len(header_cells)} headers."
                )

            cells = table.add_row().cells

            for index, value in enumerate(row):
                cells[index].text = format_cell(value)


def iter_paragraphs(container):
    """Yield every paragraph of a document, table cells included."""

    for paragraph in container.paragraphs:
        yield paragraph

    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from iter_paragraphs(cell)


def replace_in_paragraph(
    paragraph,
    replacements: dict[str, str],
    counts: dict[str, int],
) -> None:
    """
    Replace text across a paragraph's runs.

    The new text lands in the first run, so its formatting survives; the
    remaining runs are cleared. Mixed formatting inside a replaced phrase
    is lost by design, because Word splits runs unpredictably.
    """

    runs = paragraph.runs

    if not runs:
        return

    text = "".join(run.text for run in runs)

    if not text:
        return

    updated = text

    for old, new in replacements.items():
        occurrences = updated.count(old)

        if not occurrences:
            continue

        counts[old] = counts.get(old, 0) + occurrences
        updated = updated.replace(old, new)

    if updated == text:
        return

    runs[0].text = updated

    for run in runs[1:]:
        run.text = ""

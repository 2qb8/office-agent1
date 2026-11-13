from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document

from agent.models import ToolResult
from tools.base import Tool


class WordTool(Tool):
    name = "word"

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "create_document":
            return self._create_document(arguments)

        if action == "inspect":
            return self._inspect(arguments)

        if action == "verify_document":
            return self._verify_document(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown word action: {action}",
        )

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

        output_path = Path(raw_output_path).resolve()

        if output_path.suffix.lower() != ".docx":
            return ToolResult(
                success=False,
                error=f"Output must be DOCX: {output_path}",
            )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        document = Document()

        elements = arguments.get("elements", [])

        if not isinstance(elements, list):
            return ToolResult(
                success=False,
                error="'elements' must be a list.",
            )

        try:
            for element in elements:
                self._add_element(document, element)

            document.save(output_path)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to create Word document: {exc}",
            )

        if not output_path.exists():
            return ToolResult(
                success=False,
                error=f"Word document was not created: {output_path}",
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
                error=(
                    "verify_document requires "
                    "'path' or 'output_path'."
                ),
            )

        path = Path(raw_path).resolve()

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

            actual_tables = []

            for table in document.tables:
                rows = []

                for row in table.rows:
                    rows.append(
                        [cell.text for cell in row.cells]
                    )

                actual_tables.append(rows)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read Word document: {exc}",
            )

        expected_paragraphs = expected.get(
            "paragraphs",
            [],
        )

        expected_tables = expected.get(
            "tables",
            [],
        )

        mismatches = []

        if expected_paragraphs:
            if actual_paragraphs != expected_paragraphs:
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
                expected_headers,
                *expected_rows,
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

            actual_matrix = actual_tables[index]

            if actual_matrix != expected_matrix:
                mismatches.append(
                    {
                        "type": "table",
                        "table_index": index,
                        "expected": expected_matrix,
                        "actual": actual_matrix,
                    }
                )

        success = not mismatches

        if success:
            message = (
                f"Verified Word document content: "
                f"{path.name}"
            )
        else:
            message = (
                f"Word document verification failed: "
                f"{path.name}"
            )

        return ToolResult(
            success=success,
            message=message,
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

    def _add_element(
        self,
        document: Document,
        element: dict[str, Any],
    ) -> None:

        element_type = element.get("type")

        if element_type == "heading":
            level = int(element.get("level", 1))
            text = str(element.get("text", ""))

            document.add_heading(
                text,
                level=level,
            )
            return

        if element_type == "paragraph":
            text = str(element.get("text", ""))

            document.add_paragraph(text)
            return

        if element_type == "table":
            headers = element.get("headers", [])
            rows = element.get("rows", [])

            if not headers:
                raise ValueError(
                    "Table requires a non-empty 'headers' list."
                )

            table = document.add_table(
                rows=1,
                cols=len(headers),
            )

            table.style = "Table Grid"

            for index, header in enumerate(headers):
                table.rows[0].cells[index].text = str(header)

            for row in rows:
                if not isinstance(row, list):
                    raise ValueError(
                        "Each table row must be a list."
                    )

                if len(row) != len(headers):
                    raise ValueError(
                        "Table row length does not match "
                        "header count."
                    )

                cells = table.add_row().cells

                for index, value in enumerate(row):
                    cells[index].text = str(value)

            return

        raise ValueError(
            f"Unknown Word element type: {element_type}"
        )

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
                error=(
                    "inspect requires 'path' "
                    "or 'output_path'."
                ),
            )

        path = Path(raw_path).resolve()

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

            tables = []

            for table in document.tables:
                rows = []

                for row in table.rows:
                    rows.append(
                        [cell.text for cell in row.cells]
                    )

                tables.append(rows)

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
            },
            evidence=[str(path)],
        )
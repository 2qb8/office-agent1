from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import load_workbook

from agent.models import ToolResult
from tools.base import Tool
from tools.render import render_document, render_worksheet


class ScreenshotTool(Tool):
    """
    Render a DOCX or XLSX file to a PNG image.

    This is a deterministic content preview drawn from the parsed file, so
    it works everywhere (including the frozen executable) without Word,
    Excel or LibreOffice. Fonts and pagination are approximated.
    """

    name = "screenshot"

    actions = (
        "document",
        "workbook",
    )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "document":
            return self._document(arguments)

        if action == "workbook":
            return self._workbook(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown screenshot action: {action}",
        )

    def _document(self, arguments: dict[str, Any]) -> ToolResult:
        source, output_path, scale = self._targets(
            arguments,
            ".docx",
        )

        if not isinstance(source, Path):
            return source

        try:
            image = render_document(
                Document(source),
                scale=scale,
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to render document: {exc}",
            )

        return self._save(
            image,
            output_path,
            {
                "source": str(source),
                "engine": "preview",
            },
        )

    def _workbook(self, arguments: dict[str, Any]) -> ToolResult:
        source, output_path, scale = self._targets(
            arguments,
            ".xlsx",
        )

        if not isinstance(source, Path):
            return source

        sheet = arguments.get("sheet")

        try:
            workbook = load_workbook(
                source,
                read_only=True,
                data_only=True,
            )

            if sheet:
                if sheet not in workbook.sheetnames:
                    workbook.close()

                    return ToolResult(
                        success=False,
                        error=(
                            f"Worksheet not found: {sheet}. "
                            f"Available: {workbook.sheetnames}"
                        ),
                    )

                worksheet = workbook[sheet]
            else:
                worksheet = workbook.worksheets[0]

            image = render_worksheet(
                worksheet,
                scale=scale,
                max_rows=int(arguments.get("max_rows", 40)),
                max_columns=int(arguments.get("max_columns", 12)),
            )

            sheet_name = worksheet.title

            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to render workbook: {exc}",
            )

        return self._save(
            image,
            output_path,
            {
                "source": str(source),
                "sheet": sheet_name,
                "engine": "preview",
            },
        )

    @staticmethod
    def _targets(
        arguments: dict[str, Any],
        suffix: str,
    ) -> tuple[Path, Path, float] | tuple[ToolResult, None, None]:

        raw_source = arguments.get("path")
        raw_output = arguments.get("output_path")

        if not raw_source or not raw_output:
            return (
                ToolResult(
                    success=False,
                    error=(
                        "screenshot requires 'path' and 'output_path'."
                    ),
                ),
                None,
                None,
            )

        source = Path(str(raw_source)).resolve()
        output_path = Path(str(raw_output)).resolve()

        if not source.is_file():
            return (
                ToolResult(
                    success=False,
                    error=f"Source file not found: {source}",
                ),
                None,
                None,
            )

        if source.suffix.lower() != suffix:
            return (
                ToolResult(
                    success=False,
                    error=f"Expected {suffix} source, got: {source.suffix}",
                ),
                None,
                None,
            )

        if output_path.suffix.lower() != ".png":
            return (
                ToolResult(
                    success=False,
                    error=f"Screenshot output must be a .png: {output_path}",
                ),
                None,
                None,
            )

        try:
            scale = float(arguments.get("scale", 1.0))
        except (TypeError, ValueError):
            return (
                ToolResult(
                    success=False,
                    error="'scale' must be a number.",
                ),
                None,
                None,
            )

        if not 0.2 <= scale <= 4:
            return (
                ToolResult(
                    success=False,
                    error="'scale' must be between 0.2 and 4.",
                ),
                None,
                None,
            )

        return source, output_path, scale

    @staticmethod
    def _save(
        image,
        output_path: Path,
        details: dict[str, Any],
    ) -> ToolResult:

        try:
            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            image.save(output_path, format="PNG")

        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"Failed to save screenshot: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Rendered {output_path.name}",
            data={
                "path": str(output_path),
                **details,
                "width": image.width,
                "height": image.height,
                "size_bytes": output_path.stat().st_size,
            },
            evidence=[str(output_path)],
        )

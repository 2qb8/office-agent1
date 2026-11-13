from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from agent.metadata import (
    apply_to_workbook,
    read_workbook_metadata,
    resolve as resolve_metadata,
)
from agent.models import ToolResult
from tools.base import Tool
from tools.tabular import shape_table


EXCEL_SUFFIXES = {".xlsx", ".xlsm"}

HEADER_FILL = PatternFill(
    fill_type="solid",
    fgColor="D9EAF7",
)


class ExcelTool(Tool):
    name = "excel"

    actions = (
        "inspect",
        "read_table",
        "create_workbook",
        "append_rows",
        "set_cell",
        "set_range_values",
        "merge_cells",
        "format_header",
        "autofit",
        "add_image",
        "set_metadata",
        "verify_cell",
        "verify_workbook",
        "verify_exists",
    )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        actions = {
            "inspect": self._inspect,
            "read_table": self._read_table,
            "create_workbook": self._create_workbook,
            "append_rows": self._append_rows,
            "set_cell": self._set_cell,
            "set_range_values": self._set_range_values,
            "merge_cells": self._merge_cells,
            "format_header": self._format_header,
            "autofit": self._autofit,
            "add_image": self._add_image,
            "set_metadata": self._set_metadata,
            "verify_cell": self._verify_cell,
            "verify_workbook": self._verify_workbook,
            "verify_exists": self._verify_exists,
        }

        handler = actions.get(action)

        if handler is None:
            return ToolResult(
                success=False,
                error=f"Unknown Excel action: {action}",
            )

        return handler(arguments)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_path(
        self,
        arguments: dict[str, Any],
        key: str = "path",
    ) -> Path:
        value = arguments.get(key)

        if not value:
            raise ValueError(f"Missing required argument: {key}")

        path = Path(str(value)).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")

        if path.suffix.lower() not in EXCEL_SUFFIXES:
            raise ValueError(
                f"Expected .xlsx or .xlsm file, got: {path.suffix}"
            )

        return path

    def _validate_output_path(
        self,
        arguments: dict[str, Any],
    ) -> Path:
        value = arguments.get("output_path")

        if not value:
            raise ValueError("Missing required argument: output_path")

        path = Path(str(value)).resolve()

        if path.suffix.lower() not in EXCEL_SUFFIXES:
            raise ValueError(
                f"Expected .xlsx or .xlsm output, got: {path.suffix}"
            )

        path.parent.mkdir(parents=True, exist_ok=True)

        return path

    def _open_worksheet(
        self,
        workbook,
        arguments: dict[str, Any],
    ):
        sheet = arguments.get("sheet")

        if sheet:
            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}. "
                    f"Available: {workbook.sheetnames}"
                )

            return workbook[sheet]

        return workbook.worksheets[0]

    # ------------------------------------------------------------------
    # Inspect
    # ------------------------------------------------------------------

    def _inspect(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)

            workbook = load_workbook(
                path,
                read_only=True,
                data_only=False,
            )

            sheets: list[dict[str, Any]] = []

            for worksheet in workbook.worksheets:
                headers: list[Any] = []

                if worksheet.max_row >= 1:
                    headers = self._trim_row(
                        [cell.value for cell in worksheet[1]]
                    )

                sample_rows: list[list[Any]] = []

                end_row = min(worksheet.max_row, 6)

                for row in worksheet.iter_rows(
                    min_row=2,
                    max_row=end_row,
                    values_only=True,
                ):
                    sample_rows.append(
                        self._trim_row(list(row))
                    )

                sheets.append(
                    {
                        "name": worksheet.title,
                        "rows": worksheet.max_row,
                        "columns": worksheet.max_column,
                        "headers": headers,
                        "sample_rows": sample_rows,
                    }
                )

            metadata_values = read_workbook_metadata(workbook)

            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to inspect Excel workbook: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Inspected Excel workbook: {path.name}",
            data={
                "path": str(path),
                "sheets": sheets,
                "metadata": metadata_values,
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Read table
    # ------------------------------------------------------------------

    def _read_table(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)

            workbook = load_workbook(
                path,
                read_only=True,
                data_only=bool(arguments.get("data_only", False)),
            )

            worksheet = self._open_worksheet(workbook, arguments)

            matrix: list[list[Any]] = [
                list(row)
                for row in worksheet.iter_rows(values_only=True)
            ]

            sheet_name = worksheet.title
            sheet_names = list(workbook.sheetnames)

            workbook.close()

            headers, rows = shape_table(
                matrix,
                header_row=arguments.get("header_row", 1),
                max_rows=arguments.get("max_rows"),
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read Excel table: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Read {len(rows)} rows from "
                f"{path.name} [{sheet_name}]"
            ),
            data={
                "path": str(path),
                "sheet": sheet_name,
                "sheet_names": sheet_names,
                "headers": headers,
                "rows": rows,
                "row_count": len(rows),
                "column_count": len(headers),
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Create workbook
    # ------------------------------------------------------------------

    def _create_workbook(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            output_path = self._validate_output_path(arguments)

            sheets = arguments.get("sheets")

            if not isinstance(sheets, list) or not sheets:
                raise ValueError(
                    "create_workbook requires a non-empty 'sheets' list"
                )

            workbook = Workbook()
            workbook.remove(workbook.active)

            created_sheets: list[dict[str, Any]] = []

            for definition in sheets:

                if not isinstance(definition, dict):
                    raise ValueError(
                        "Each sheet definition must be an object"
                    )

                name = definition.get("name")

                if not name:
                    raise ValueError("Each sheet requires a 'name'")

                name = str(name)

                if len(name) > 31:
                    raise ValueError(
                        f"Excel worksheet name is too long: {name}"
                    )

                if name in workbook.sheetnames:
                    raise ValueError(
                        f"Duplicate worksheet name: {name}"
                    )

                headers = definition.get("headers", [])
                rows = definition.get("rows", [])

                if not isinstance(headers, list):
                    raise ValueError(
                        f"Headers for sheet '{name}' must be a list"
                    )

                if not isinstance(rows, list):
                    raise ValueError(
                        f"Rows for sheet '{name}' must be a list"
                    )

                worksheet = workbook.create_sheet(title=name)

                if headers:
                    worksheet.append(
                        [header for header in headers]
                    )

                    for cell in worksheet[1]:
                        cell.font = Font(bold=True)
                        cell.fill = HEADER_FILL

                for row in rows:

                    if not isinstance(row, (list, tuple)):
                        raise ValueError(
                            f"Every row in sheet '{name}' must be a list"
                        )

                    worksheet.append(list(row))

                self._autosize(worksheet)

                created_sheets.append(
                    {
                        "name": name,
                        "rows": worksheet.max_row,
                        "columns": worksheet.max_column,
                    }
                )

            apply_to_workbook(
                workbook,
                resolve_metadata(arguments.get("metadata")),
            )

            workbook.save(output_path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to create Excel workbook: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Created Excel workbook: {output_path.name}",
            data={
                "path": str(output_path),
                "sheets": created_sheets,
                "size_bytes": output_path.stat().st_size,
            },
            evidence=[str(output_path)],
        )

    @staticmethod
    def _autosize(worksheet) -> None:
        for column_cells in worksheet.columns:
            max_length = 0

            for cell in column_cells:
                if cell.value is not None:
                    max_length = max(
                        max_length,
                        len(str(cell.value)),
                    )

            worksheet.column_dimensions[
                column_cells[0].column_letter
            ].width = min(max(max_length + 2, 10), 60)

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def _verify_exists(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to verify Excel workbook: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Excel workbook exists: {path.name}",
            data={
                "path": str(path),
                "size_bytes": path.stat().st_size,
            },
            evidence=[str(path)],
        )

    def _verify_workbook(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            expected = arguments.get("expected")

            if not isinstance(expected, dict):
                raise ValueError(
                    "verify_workbook requires an 'expected' object"
                )

            expected_sheets = expected.get("sheets")

            if not isinstance(expected_sheets, list):
                raise ValueError("expected.sheets must be a list")

            workbook = load_workbook(
                path,
                read_only=True,
                data_only=False,
            )

            actual_sheet_names = workbook.sheetnames
            mismatches: list[str] = []
            actual_data: list[dict[str, Any]] = []

            for expected_sheet in expected_sheets:
                sheet_name = expected_sheet.get("name")

                if sheet_name not in actual_sheet_names:
                    mismatches.append(
                        f"Missing worksheet: {sheet_name}"
                    )
                    continue

                worksheet = workbook[sheet_name]

                expected_matrix = [
                    [str(value) for value in expected_sheet.get(
                        "headers",
                        [],
                    )],
                    *[
                        [str(value) for value in row]
                        for row in expected_sheet.get("rows", [])
                    ],
                ]

                actual_matrix = [
                    [
                        str(value)
                        for value in self._trim_row(list(row))
                    ]
                    for row in worksheet.iter_rows(
                        min_row=1,
                        max_row=worksheet.max_row,
                        min_col=1,
                        max_col=worksheet.max_column,
                        values_only=True,
                    )
                ]

                while actual_matrix and not actual_matrix[-1]:
                    actual_matrix.pop()

                if actual_matrix != expected_matrix:
                    mismatches.append(
                        f"Content mismatch in worksheet: {sheet_name}"
                    )

                actual_data.append(
                    {
                        "name": sheet_name,
                        "rows": worksheet.max_row,
                        "columns": worksheet.max_column,
                        "values": actual_matrix,
                    }
                )

            expected_names = {
                sheet.get("name")
                for sheet in expected_sheets
            }

            for name in actual_sheet_names:
                if name not in expected_names:
                    mismatches.append(
                        f"Unexpected worksheet: {name}"
                    )

            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to verify Excel workbook: {exc}",
            )

        if mismatches:
            return ToolResult(
                success=False,
                message=(
                    f"Excel workbook verification failed: {path.name}"
                ),
                data={
                    "path": str(path),
                    "actual_sheets": actual_data,
                    "mismatches": mismatches,
                },
                evidence=[str(path)],
                error="; ".join(mismatches),
            )

        return ToolResult(
            success=True,
            message=f"Verified Excel workbook: {path.name}",
            data={
                "path": str(path),
                "sheets": actual_data,
                "mismatches": [],
            },
            evidence=[str(path)],
        )

    def _verify_cell(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            cell = arguments.get("cell")
            expected = arguments.get("expected")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not cell:
                raise ValueError("Missing required argument: cell")

            workbook = load_workbook(
                path,
                read_only=True,
                data_only=False,
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            actual = workbook[sheet][cell].value

            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to verify Excel cell: {exc}",
            )

        success = actual == expected

        return ToolResult(
            success=success,
            message=(
                f"Verified {sheet}!{cell}: actual={actual!r}, "
                f"expected={expected!r}"
            ),
            data={
                "path": str(path),
                "sheet": sheet,
                "cell": cell,
                "actual": actual,
                "expected": expected,
            },
            evidence=[str(path)],
            error=(
                None
                if success
                else f"Expected {expected!r}, got {actual!r}"
            ),
        )

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------

    def _set_cell(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            cell = arguments.get("cell")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not cell:
                raise ValueError("Missing required argument: cell")

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            workbook[sheet][cell] = arguments.get("value")

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to set Excel cell: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Set {sheet}!{cell} in {path.name}",
            data={
                "path": str(path),
                "sheet": sheet,
                "cell": cell,
                "value": arguments.get("value"),
            },
            evidence=[str(path)],
        )

    def _set_range_values(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            start_cell = arguments.get("start_cell")
            values = arguments.get("values")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not start_cell:
                raise ValueError(
                    "Missing required argument: start_cell"
                )

            if not isinstance(values, list) or not values:
                raise ValueError(
                    "values must be a non-empty list"
                )

            from openpyxl.utils.cell import (
                column_index_from_string,
                coordinate_from_string,
            )

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            worksheet = workbook[sheet]

            column_letter, row_number = coordinate_from_string(
                start_cell
            )
            start_column = column_index_from_string(column_letter)

            for row_offset, row_values in enumerate(values):

                if not isinstance(row_values, (list, tuple)):
                    raise ValueError(
                        "Each values row must be a list"
                    )

                for column_offset, value in enumerate(row_values):
                    worksheet.cell(
                        row=row_number + row_offset,
                        column=start_column + column_offset,
                        value=value,
                    )

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to write Excel range: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Wrote range starting at {sheet}!{start_cell} "
                f"in {path.name}"
            ),
            data={
                "path": str(path),
                "sheet": sheet,
                "start_cell": start_cell,
                "rows_written": len(values),
            },
            evidence=[str(path)],
        )

    def _format_header(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            row = int(arguments.get("row", 1))

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            for cell in workbook[sheet][row]:
                if cell.value is not None:
                    cell.font = Font(bold=True)
                    cell.fill = HEADER_FILL

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to format Excel header: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Formatted header row {row} in {sheet}",
            data={
                "path": str(path),
                "sheet": sheet,
                "row": row,
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Append rows
    # ------------------------------------------------------------------

    def _append_rows(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            rows = arguments.get("rows")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not isinstance(rows, list) or not rows:
                raise ValueError("'rows' must be a non-empty list")

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}. "
                    f"Available: {workbook.sheetnames}"
                )

            worksheet = workbook[sheet]

            start_row = (
                1 if sheet_is_empty(worksheet)
                else worksheet.max_row + 1
            )

            for offset, row in enumerate(rows):
                if not isinstance(row, (list, tuple)):
                    raise ValueError(
                        "Each row must be a list"
                    )

                for column, value in enumerate(row, start=1):
                    worksheet.cell(
                        row=start_row + offset,
                        column=column,
                        value=value,
                    )

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to append rows: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Appended {len(rows)} row(s) to {sheet}"
            ),
            data={
                "path": str(path),
                "sheet": sheet,
                "start_row": start_row,
                "rows_added": len(rows),
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Merge cells
    # ------------------------------------------------------------------

    def _merge_cells(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            cell_range = arguments.get("range")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not cell_range:
                raise ValueError("Missing required argument: range")

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            worksheet = workbook[sheet]

            cell_range = str(cell_range)

            worksheet.merge_cells(range_string=cell_range)

            if "value" in arguments:
                top_left = cell_range.split(":")[0]
                worksheet[top_left] = arguments.get("value")

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to merge cells: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Merged {cell_range} in {sheet}",
            data={
                "path": str(path),
                "sheet": sheet,
                "range": cell_range,
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Autofit
    # ------------------------------------------------------------------

    def _autofit(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet:
                if sheet not in workbook.sheetnames:
                    raise ValueError(
                        f"Worksheet not found: {sheet}"
                    )

                targets = [workbook[sheet]]
            else:
                targets = list(workbook.worksheets)

            for worksheet in targets:
                self._autosize(worksheet)

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to autofit columns: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Fitted columns in {len(targets)} worksheet(s)"
            ),
            data={
                "path": str(path),
                "sheets": [sheet.title for sheet in targets],
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def _add_image(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            raw_image = arguments.get("image_path")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not raw_image:
                raise ValueError(
                    "Missing required argument: image_path"
                )

            image_path = Path(str(raw_image)).resolve()

            if not image_path.is_file():
                raise FileNotFoundError(
                    f"Image not found: {image_path}"
                )

            from openpyxl.drawing.image import Image as WorksheetImage

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            worksheet = workbook[sheet]

            drawing = WorksheetImage(str(image_path))

            for key, attribute in (
                ("width", "width"),
                ("height", "height"),
            ):
                value = arguments.get(key)

                if value is not None:
                    setattr(drawing, attribute, int(value))

            cell = str(arguments.get("cell", "A1"))

            worksheet.add_image(drawing, cell)

            workbook.save(path)
            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to add image: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Added {image_path.name} to {sheet}!{cell}"
            ),
            data={
                "path": str(path),
                "sheet": sheet,
                "cell": cell,
                "image": str(image_path),
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _set_metadata(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            raw_metadata = arguments.get("metadata")

            if not isinstance(raw_metadata, dict) or not raw_metadata:
                raise ValueError(
                    "set_metadata requires a non-empty "
                    "'metadata' object"
                )

            values = resolve_metadata(
                raw_metadata,
                use_defaults=False,
            )

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            apply_to_workbook(workbook, values)

            workbook.save(path)

            updated = read_workbook_metadata(workbook)

            workbook.close()

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to set metadata: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Updated metadata of {path.name}",
            data={
                "path": str(path),
                "metadata": updated,
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _trim_row(row: list[Any]) -> list[Any]:
        values = list(row)

        while values and values[-1] is None:
            values.pop()

        return values


def sheet_is_empty(worksheet) -> bool:
    """True when a worksheet has no cell values."""

    for row in worksheet.iter_rows(values_only=True):
        if any(value is not None for value in row):
            return False

    return True

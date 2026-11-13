from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from agent.models import ToolResult
from tools.base import Tool


class ExcelTool(Tool):
    name = "excel"

    def run(self, action: str, arguments: dict[str, Any]) -> ToolResult:
        if action == "inspect":
            return self._inspect(arguments)

        if action == "verify_exists":
            return self._verify_exists(arguments)

        if action == "create_workbook":
            return self._create_workbook(arguments)

        if action == "verify_workbook":
            return self._verify_workbook(arguments)

        if action == "set_cell":
            return self._set_cell(arguments)

        if action == "set_range_values":
            return self._set_range_values(arguments)

        if action == "format_header":
            return self._format_header(arguments)

        if action == "verify_cell":
            return self._verify_cell(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown Excel action: {action}",
        )

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

        path = Path(value).resolve()

        if not path.exists():
            raise FileNotFoundError(f"Excel file not found: {path}")

        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError(
                f"Expected .xlsx or .xlsm file, got: {path.suffix}"
            )

        return path

    def _validate_output_path(self, arguments: dict[str, Any]) -> Path:
        value = arguments.get("output_path")

        if not value:
            raise ValueError("Missing required argument: output_path")

        path = Path(value).resolve()

        if path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError(
                f"Expected .xlsx or .xlsm output, got: {path.suffix}"
            )

        path.parent.mkdir(parents=True, exist_ok=True)

        return path

    # ------------------------------------------------------------------
    # Inspect
    # ------------------------------------------------------------------

    def _inspect(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._get_path(arguments)

        try:
            workbook = load_workbook(
                path,
                read_only=True,
                data_only=False,
            )

            sheets: list[dict[str, Any]] = []

            for worksheet in workbook.worksheets:
                headers: list[Any] = []

                if worksheet.max_row >= 1:
                    for cell in worksheet[1]:
                        if cell.value is not None:
                            headers.append(cell.value)

                sample_rows: list[list[Any]] = []

                start_row = 2
                end_row = min(worksheet.max_row, 6)

                for row in worksheet.iter_rows(
                    min_row=start_row,
                    max_row=end_row,
                    values_only=True,
                ):
                    sample_rows.append(list(row))

                sheets.append(
                    {
                        "name": worksheet.title,
                        "rows": worksheet.max_row,
                        "columns": worksheet.max_column,
                        "headers": headers,
                        "sample_rows": sample_rows,
                    }
                )

            workbook.close()

            return ToolResult(
                success=True,
                message=f"Inspected Excel workbook: {path.name}",
                data={
                    "path": str(path),
                    "sheets": sheets,
                },
                evidence=[str(path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to inspect Excel workbook: {exc}",
            )

    # ------------------------------------------------------------------
    # Verify file exists
    # ------------------------------------------------------------------

    def _verify_exists(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._get_path(arguments)

        try:
            size = path.stat().st_size

            return ToolResult(
                success=True,
                message=f"Excel workbook exists: {path.name}",
                data={
                    "path": str(path),
                    "size_bytes": size,
                },
                evidence=[str(path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to verify Excel workbook: {exc}",
            )

    # ------------------------------------------------------------------
    # Create workbook
    # ------------------------------------------------------------------

    def _create_workbook(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            output_path = self._validate_output_path(arguments)

            sheets = arguments.get("sheets")

            if not isinstance(sheets, list) or not sheets:
                raise ValueError(
                    "create_workbook requires a non-empty 'sheets' list"
                )

            workbook = Workbook()

            # Remove the automatically-created worksheet.
            default_sheet = workbook.active
            workbook.remove(default_sheet)

            created_sheets: list[dict[str, Any]] = []

            for sheet_definition in sheets:
                if not isinstance(sheet_definition, dict):
                    raise ValueError(
                        "Each sheet definition must be an object"
                    )

                name = sheet_definition.get("name")

                if not name:
                    raise ValueError(
                        "Each sheet requires a 'name'"
                    )

                name = str(name)

                if len(name) > 31:
                    raise ValueError(
                        f"Excel worksheet name is too long: {name}"
                    )

                if name in workbook.sheetnames:
                    raise ValueError(
                        f"Duplicate worksheet name: {name}"
                    )

                headers = sheet_definition.get("headers", [])
                rows = sheet_definition.get("rows", [])

                if not isinstance(headers, list):
                    raise ValueError(
                        f"Headers for sheet '{name}' must be a list"
                    )

                if not isinstance(rows, list):
                    raise ValueError(
                        f"Rows for sheet '{name}' must be a list"
                    )

                worksheet = workbook.create_sheet(title=name)

                # Write headers.
                if headers:
                    worksheet.append(headers)

                    for cell in worksheet[1]:
                        cell.font = Font(bold=True)
                        cell.fill = PatternFill(
                            fill_type="solid",
                            fgColor="D9EAF7",
                        )

                # Write data rows.
                for row in rows:
                    if not isinstance(row, list):
                        raise ValueError(
                            f"Every row in sheet '{name}' must be a list"
                        )

                    worksheet.append(row)

                # Basic readable column widths.
                for column_cells in worksheet.columns:
                    max_length = 0

                    for cell in column_cells:
                        if cell.value is not None:
                            max_length = max(
                                max_length,
                                len(str(cell.value)),
                            )

                    column_letter = column_cells[0].column_letter
                    worksheet.column_dimensions[column_letter].width = min(
                        max(max_length + 2, 10),
                        60,
                    )

                created_sheets.append(
                    {
                        "name": name,
                        "rows": worksheet.max_row,
                        "columns": worksheet.max_column,
                    }
                )

            workbook.save(output_path)
            workbook.close()

            return ToolResult(
                success=True,
                message=f"Created Excel workbook: {output_path.name}",
                data={
                    "path": str(output_path),
                    "sheets": created_sheets,
                },
                evidence=[str(output_path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to create Excel workbook: {exc}",
            )

    # ------------------------------------------------------------------
    # Verify workbook contents
    # ------------------------------------------------------------------

    def _verify_workbook(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)

            expected = arguments.get("expected")

            if not isinstance(expected, dict):
                raise ValueError(
                    "verify_workbook requires an 'expected' object"
                )

            expected_sheets = expected.get("sheets")

            if not isinstance(expected_sheets, list):
                raise ValueError(
                    "expected.sheets must be a list"
                )

            workbook = load_workbook(
                path,
                read_only=True,
                data_only=False,
            )

            actual_sheet_names = workbook.sheetnames
            mismatches: list[str] = []

            actual_data: list[dict[str, Any]] = []

            for expected_sheet in expected_sheets:
                if not isinstance(expected_sheet, dict):
                    mismatches.append(
                        "Invalid expected sheet definition"
                    )
                    continue

                sheet_name = expected_sheet.get("name")

                if not sheet_name:
                    mismatches.append(
                        "Expected sheet is missing its name"
                    )
                    continue

                if sheet_name not in actual_sheet_names:
                    mismatches.append(
                        f"Missing worksheet: {sheet_name}"
                    )
                    continue

                worksheet = workbook[sheet_name]

                expected_headers = expected_sheet.get("headers", [])
                expected_rows = expected_sheet.get("rows", [])

                expected_matrix = [
                    expected_headers,
                    *expected_rows,
                ]

                actual_matrix: list[list[Any]] = []

                if worksheet.max_row > 0 and worksheet.max_column > 0:
                    for row in worksheet.iter_rows(
                        min_row=1,
                        max_row=worksheet.max_row,
                        min_col=1,
                        max_col=worksheet.max_column,
                        values_only=True,
                    ):
                        actual_matrix.append(list(row))

                # Trim trailing completely-empty rows.
                while actual_matrix and all(
                    value is None for value in actual_matrix[-1]
                ):
                    actual_matrix.pop()

                # Trim trailing completely-empty cells in each row.
                actual_matrix = [
                    self._trim_row(row)
                    for row in actual_matrix
                ]

                expected_matrix = [
                    self._trim_row(row)
                    for row in expected_matrix
                ]

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

            # Also detect unexpected worksheets.
            expected_names = {
                sheet.get("name")
                for sheet in expected_sheets
                if isinstance(sheet, dict)
            }

            unexpected_sheets = [
                name
                for name in actual_sheet_names
                if name not in expected_names
            ]

            for name in unexpected_sheets:
                mismatches.append(
                    f"Unexpected worksheet: {name}"
                )

            workbook.close()

            if mismatches:
                return ToolResult(
                    success=False,
                    message=(
                        f"Excel workbook verification failed: "
                        f"{path.name}"
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

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to verify Excel workbook: {exc}",
            )

    @staticmethod
    def _trim_row(row: list[Any]) -> list[Any]:
        row = list(row)

        while row and row[-1] is None:
            row.pop()

        return row

    # ------------------------------------------------------------------
    # Set single cell
    # ------------------------------------------------------------------

    def _set_cell(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            cell = arguments.get("cell")
            value = arguments.get("value")

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            if not cell:
                raise ValueError("Missing required argument: cell")

            keep_vba = path.suffix.lower() == ".xlsm"

            workbook = load_workbook(
                path,
                keep_vba=keep_vba,
            )

            if sheet not in workbook.sheetnames:
                workbook.close()
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            worksheet = workbook[sheet]
            worksheet[cell] = value

            workbook.save(path)
            workbook.close()

            return ToolResult(
                success=True,
                message=(
                    f"Set {sheet}!{cell} in {path.name}"
                ),
                data={
                    "path": str(path),
                    "sheet": sheet,
                    "cell": cell,
                    "value": value,
                },
                evidence=[str(path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to set Excel cell: {exc}",
            )

    # ------------------------------------------------------------------
    # Set range
    # ------------------------------------------------------------------

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

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                workbook.close()
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            worksheet = workbook[sheet]

            from openpyxl.utils.cell import (
                coordinate_from_string,
                column_index_from_string,
            )

            column_letter, row_number = coordinate_from_string(
                start_cell
            )
            start_column = column_index_from_string(column_letter)

            for row_offset, row_values in enumerate(values):
                if not isinstance(row_values, list):
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

            return ToolResult(
                success=True,
                message=(
                    f"Wrote range starting at "
                    f"{sheet}!{start_cell} in {path.name}"
                ),
                data={
                    "path": str(path),
                    "sheet": sheet,
                    "start_cell": start_cell,
                    "rows_written": len(values),
                },
                evidence=[str(path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to write Excel range: {exc}",
            )

    # ------------------------------------------------------------------
    # Format header
    # ------------------------------------------------------------------

    def _format_header(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
        try:
            path = self._get_path(arguments)

            sheet = arguments.get("sheet")
            row = arguments.get("row", 1)

            if not sheet:
                raise ValueError("Missing required argument: sheet")

            workbook = load_workbook(
                path,
                keep_vba=path.suffix.lower() == ".xlsm",
            )

            if sheet not in workbook.sheetnames:
                workbook.close()
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            worksheet = workbook[sheet]

            for cell in worksheet[row]:
                if cell.value is not None:
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill(
                        fill_type="solid",
                        fgColor="D9EAF7",
                    )

            workbook.save(path)
            workbook.close()

            return ToolResult(
                success=True,
                message=(
                    f"Formatted header row {row} "
                    f"in {sheet}"
                ),
                data={
                    "path": str(path),
                    "sheet": sheet,
                    "row": row,
                },
                evidence=[str(path)],
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to format Excel header: {exc}",
            )

    # ------------------------------------------------------------------
    # Verify single cell
    # ------------------------------------------------------------------

    def _verify_cell(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:
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
                workbook.close()
                raise ValueError(
                    f"Worksheet not found: {sheet}"
                )

            actual = workbook[sheet][cell].value

            workbook.close()

            success = actual == expected

            return ToolResult(
                success=success,
                message=(
                    f"Verified {sheet}!{cell}: "
                    f"actual={actual!r}, "
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
                error=None if success else (
                    f"Expected {expected!r}, got {actual!r}"
                ),
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to verify Excel cell: {exc}",
            )
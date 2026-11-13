from __future__ import annotations

from typing import Any

from agent.models import ToolResult
from tools.base import Tool
from tools.tabular import (
    TableError,
    normalize_table,
    to_number,
)


COMPARISONS = {
    "=": "eq",
    "==": "eq",
    "eq": "eq",
    "!=": "ne",
    "<>": "ne",
    "ne": "ne",
    ">": "gt",
    "gt": "gt",
    ">=": "gte",
    "gte": "gte",
    ">=": "gte",
    "<": "lt",
    "lt": "lt",
    "<=": "lte",
    "lte": "lte",
    "contains": "contains",
    "starts_with": "starts_with",
    "startswith": "starts_with",
    "ends_with": "ends_with",
    "endswith": "ends_with",
    "in": "in",
    "not_in": "not_in",
    "is_empty": "is_empty",
    "not_empty": "not_empty",
}

AGGREGATIONS = {"sum", "count", "mean", "min", "max"}


class TableTool(Tool):
    """In-memory table transforms chained through "$step" references."""

    name = "table"

    actions = (
        "filter",
        "sort",
        "select",
        "aggregate",
        "limit",
    )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "filter":
            return self._filter(arguments)

        if action == "sort":
            return self._sort(arguments)

        if action == "select":
            return self._select(arguments)

        if action == "aggregate":
            return self._aggregate(arguments)

        if action == "limit":
            return self._limit(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown table action: {action}",
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _filter(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            headers, rows = normalize_table(
                arguments.get("headers"),
                arguments.get("rows"),
            )

            column = self._column_index(
                headers,
                arguments.get("column"),
            )

            comparison = self._comparison(
                arguments.get("op", "==")
            )

            expected = arguments.get("value")

            selected = [
                row
                for row in rows
                if _matches(
                    row[column],
                    comparison,
                    expected,
                )
            ]

        except (TableError, ValueError) as exc:
            return ToolResult(
                success=False,
                error=f"Failed to filter rows: {exc}",
            )

        return _table_result(
            headers,
            selected,
            f"Filtered to {len(selected)} of {len(rows)} rows",
        )

    def _sort(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            headers, rows = normalize_table(
                arguments.get("headers"),
                arguments.get("rows"),
            )

            column = self._column_index(
                headers,
                arguments.get("column"),
            )

            descending = bool(arguments.get("descending", False))

        except (TableError, ValueError) as exc:
            return ToolResult(
                success=False,
                error=f"Failed to sort rows: {exc}",
            )

        numbers = [
            to_number(row[column])
            for row in rows
        ]

        if rows and all(number is not None for number in numbers):
            key = lambda index: numbers[index]  # noqa: E731
        else:
            key = lambda index: str(
                rows[index][column] or ""
            ).lower()  # noqa: E731

        order = sorted(
            range(len(rows)),
            key=key,
            reverse=descending,
        )

        sorted_rows = [rows[index] for index in order]

        return _table_result(
            headers,
            sorted_rows,
            f"Sorted {len(sorted_rows)} rows",
        )

    def _select(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            headers, rows = normalize_table(
                arguments.get("headers"),
                arguments.get("rows"),
            )

            requested = arguments.get("columns")

            if isinstance(requested, (str, int)):
                requested = [requested]

            if not isinstance(requested, list) or not requested:
                raise TableError(
                    "'columns' must be a non-empty list."
                )

            indexes = [
                self._column_index(headers, column)
                for column in requested
            ]

            selected_headers = [
                headers[index]
                for index in indexes
            ]

            selected_rows = [
                [row[index] for index in indexes]
                for row in rows
            ]

        except (TableError, ValueError) as exc:
            return ToolResult(
                success=False,
                error=f"Failed to select columns: {exc}",
            )

        return _table_result(
            selected_headers,
            selected_rows,
            f"Selected {len(selected_headers)} columns",
        )

    def _aggregate(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            headers, rows = normalize_table(
                arguments.get("headers"),
                arguments.get("rows"),
            )

            operation = str(
                arguments.get("op", "sum")
            ).lower()

            if operation not in AGGREGATIONS:
                raise TableError(
                    f"Unknown aggregation '{operation}'. "
                    f"Use one of: {sorted(AGGREGATIONS)}"
                )

            value_column = arguments.get("column")

            value_index = None

            if value_column is not None:
                value_index = self._column_index(
                    headers,
                    value_column,
                )
            elif operation != "count":
                raise TableError(
                    f"Aggregation '{operation}' requires 'column'."
                )

            group_column = arguments.get("group_by")
            group_index = None

            if group_column is not None:
                group_index = self._column_index(
                    headers,
                    group_column,
                )

        except (TableError, ValueError) as exc:
            return ToolResult(
                success=False,
                error=f"Failed to aggregate rows: {exc}",
            )

        column_label = (
            headers[value_index]
            if value_index is not None
            else "Rows"
        )

        value_label = f"{operation}({column_label})"

        if group_index is None:
            groups: dict[Any, list[list[Any]]] = {
                None: rows
            }
            output_headers = [value_label]
        else:
            groups = {}

            for row in rows:
                key = row[group_index]
                groups.setdefault(key, []).append(row)

            output_headers = [
                headers[group_index],
                value_label,
            ]

        output_rows: list[list[Any]] = []

        for group_key, group_rows in groups.items():
            values = (
                [
                    row[value_index]
                    for row in group_rows
                ]
                if value_index is not None
                else []
            )

            result = _aggregate(
                operation,
                values,
                len(group_rows),
            )

            if group_index is None:
                output_rows.append([result])
            else:
                output_rows.append([group_key, result])

        return _table_result(
            output_headers,
            output_rows,
            f"Aggregated {len(rows)} rows into "
            f"{len(output_rows)} groups",
        )

    def _limit(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            headers, rows = normalize_table(
                arguments.get("headers"),
                arguments.get("rows"),
            )

            limit = int(arguments.get("limit", 10))
            offset = int(arguments.get("offset", 0))

            if limit < 1:
                raise TableError("'limit' must be at least 1.")

            if offset < 0:
                raise TableError("'offset' must be zero or more.")

        except (TableError, ValueError, TypeError) as exc:
            return ToolResult(
                success=False,
                error=f"Failed to limit rows: {exc}",
            )

        selected = rows[offset : offset + limit]

        return _table_result(
            headers,
            selected,
            f"Kept {len(selected)} of {len(rows)} rows",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _column_index(
        headers: list[str],
        column: Any,
    ) -> int:
        if column is None:
            raise TableError("'column' is required.")

        if isinstance(column, bool):
            raise TableError("'column' must be a name or index.")

        if isinstance(column, int):
            if not 0 <= column < len(headers):
                raise TableError(
                    f"Column index {column} is out of range."
                )

            return column

        name = str(column)

        if name in headers:
            return headers.index(name)

        if name.isdigit() and int(name) < len(headers):
            return int(name)

        raise TableError(
            f"Column '{name}' not found. "
            f"Available columns: {headers}"
        )

    @staticmethod
    def _comparison(op: Any) -> str:
        key = str(op).strip().lower()

        if key not in COMPARISONS:
            raise ValueError(
                f"Unknown comparison '{op}'. "
                f"Use one of: {sorted(set(COMPARISONS))}"
            )

        return COMPARISONS[key]


def _matches(
    actual: Any,
    comparison: str,
    expected: Any,
) -> bool:
    if comparison == "is_empty":
        return actual in (None, "")

    if comparison == "not_empty":
        return actual not in (None, "")

    if comparison == "contains":
        return str(expected).lower() in str(actual or "").lower()

    if comparison == "starts_with":
        return str(actual or "").lower().startswith(
            str(expected).lower()
        )

    if comparison == "ends_with":
        return str(actual or "").lower().endswith(
            str(expected).lower()
        )

    if comparison in {"in", "not_in"}:
        candidates = (
            expected
            if isinstance(expected, (list, tuple, set))
            else [expected]
        )

        found = any(
            _equals(actual, candidate)
            for candidate in candidates
        )

        return found if comparison == "in" else not found

    actual_number = to_number(actual)
    expected_number = to_number(expected)

    if actual_number is not None and expected_number is not None:
        left: Any = actual_number
        right: Any = expected_number
    else:
        left = "" if actual is None else str(actual).lower()
        right = "" if expected is None else str(expected).lower()

    if comparison == "eq":
        return left == right

    if comparison == "ne":
        return left != right

    if comparison == "gt":
        return left > right

    if comparison == "gte":
        return left >= right

    if comparison == "lt":
        return left < right

    if comparison == "lte":
        return left <= right

    return False


def _equals(actual: Any, expected: Any) -> bool:
    if to_number(actual) is not None and to_number(expected) is not None:
        return to_number(actual) == to_number(expected)

    return str(actual) == str(expected)


def _aggregate(
    operation: str,
    values: list[Any],
    row_count: int,
) -> Any:
    if operation == "count":
        return row_count

    numbers = [
        number
        for number in (to_number(value) for value in values)
        if number is not None
    ]

    if operation == "sum":
        return round(sum(numbers), 6)

    if operation == "mean":
        if not numbers:
            return None

        return round(sum(numbers) / len(numbers), 6)

    if operation == "min":
        if numbers:
            return round(min(numbers), 6)

        candidates = [
            value
            for value in values
            if value is not None
        ]

        return min(candidates) if candidates else None

    if operation == "max":
        if numbers:
            return round(max(numbers), 6)

        candidates = [
            value
            for value in values
            if value is not None
        ]

        return max(candidates) if candidates else None

    return None


def _table_result(
    headers: list[str],
    rows: list[list[Any]],
    message: str,
) -> ToolResult:
    return ToolResult(
        success=True,
        message=message,
        data={
            "headers": headers,
            "rows": rows,
            "row_count": len(rows),
            "column_count": len(headers),
        },
    )

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.models import ToolResult
from tools.base import Tool
from tools.tabular import (
    TableError,
    normalize_table,
    render_csv,
    render_markdown_table,
    render_records,
    render_tsv,
)


TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".log",
}


class TextTool(Tool):
    """Write and verify plain-text outputs (txt, md, csv, tsv, json)."""

    name = "text"

    actions = (
        "write",
        "read",
        "verify",
    )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "write":
            return self._write(arguments)

        if action == "read":
            return self._read(arguments)

        if action == "verify":
            return self._verify(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown text action: {action}",
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _write(self, arguments: dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("output_path")

        if not raw_path:
            return ToolResult(
                success=False,
                error="write requires 'output_path'.",
            )

        output_path = Path(str(raw_path)).resolve()

        try:
            content = _render_content(arguments, output_path)
        except (TableError, ValueError, TypeError) as exc:
            return ToolResult(
                success=False,
                error=f"Failed to build text content: {exc}",
            )

        mode = str(arguments.get("mode", "write")).lower()

        if mode not in {"write", "append"}:
            return ToolResult(
                success=False,
                error=f"Unknown write mode: {mode}",
            )

        try:
            output_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with output_path.open(
                "a" if mode == "append" else "w",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write(content)

        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"Failed to write {output_path}: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"{'Appended to' if mode == 'append' else 'Wrote'} "
                f"{output_path.name}"
            ),
            data={
                "path": str(output_path),
                "size_bytes": output_path.stat().st_size,
                "line_count": content.count("\n"),
            },
            evidence=[str(output_path)],
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def _read(self, arguments: dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("path")

        if not raw_path:
            return ToolResult(
                success=False,
                error="read requires 'path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Text file not found: {path}",
            )

        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read {path}: {exc}",
            )

        return ToolResult(
            success=True,
            message=f"Read {path.name}",
            data={
                "path": str(path),
                "text": text,
                "line_count": len(text.splitlines()),
                "character_count": len(text),
            },
            evidence=[str(path)],
        )

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def _verify(self, arguments: dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("path") or arguments.get(
            "output_path"
        )

        if not raw_path:
            return ToolResult(
                success=False,
                error="verify requires 'path'.",
            )

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Text file not found: {path}",
            )

        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"Failed to read {path}: {exc}",
            )

        problems: list[str] = []

        expected_text = arguments.get("expected_text")

        if expected_text is not None and text.strip() != str(
            expected_text
        ).strip():
            problems.append("File content does not match expected_text.")

        expected_contains = arguments.get(
            "expected_contains",
            [],
        )

        if isinstance(expected_contains, str):
            expected_contains = [expected_contains]

        for fragment in expected_contains or []:
            if str(fragment) not in text:
                problems.append(
                    f"Missing expected fragment: {fragment!r}"
                )

        success = not problems

        return ToolResult(
            success=success,
            message=(
                f"Verified {path.name}"
                if success
                else f"Verification failed: {path.name}"
            ),
            data={
                "path": str(path),
                "verified": success,
                "mismatches": problems,
            },
            evidence=[str(path)],
            error=None if success else "; ".join(problems),
        )


def _render_content(
    arguments: dict[str, Any],
    output_path: Path,
) -> str:
    suffix = output_path.suffix.lower()

    if suffix and suffix not in TEXT_SUFFIXES:
        raise ValueError(
            f"Unsupported text output '{suffix}'. "
            f"Use one of: {sorted(TEXT_SUFFIXES)}"
        )

    if "rows" in arguments:
        headers, rows = normalize_table(
            arguments.get("headers"),
            arguments.get("rows"),
        )

        if suffix in {".json"}:
            return _json_dump(render_records(headers, rows))

        if suffix in {".md", ".markdown"}:
            return render_markdown_table(headers, rows) + "\n"

        if suffix in {".tsv", ".txt", ".log"}:
            return render_tsv(headers, rows)

        return render_csv(
            headers,
            rows,
            delimiter=str(arguments.get("delimiter", ",")),
        )

    if "data" in arguments:
        return _json_dump(arguments["data"])

    if "lines" in arguments:
        lines = arguments["lines"]

        if not isinstance(lines, list):
            raise ValueError("'lines' must be a list.")

        text = "\n".join(str(line) for line in lines)

        return text if text.endswith("\n") else text + "\n"

    if "content" in arguments:
        return str(arguments["content"])

    raise ValueError(
        "write requires one of 'rows' + 'headers', 'data', "
        "'lines', or 'content'."
    )


def _json_dump(value: Any) -> str:
    return (
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
        + "\n"
    )

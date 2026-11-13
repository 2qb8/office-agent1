from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.models import ToolResult
from tools.base import Tool


class FilesystemTool(Tool):
    name = "filesystem"

    def _check_file_exists(
    self,
    arguments: dict[str, Any],
) -> ToolResult:

        raw_path = arguments.get("path")

        if not raw_path:
            return ToolResult(
                success=False,
                error="check_file_exists requires 'path'.",
            )

        path = Path(raw_path).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                message=f"File does not exist: {path}",
                data={
                    "path": str(path),
                    "exists": False,
                },
                error=f"File not found: {path}",
            )

        if not path.is_file():
            return ToolResult(
                success=False,
                message=f"Path exists but is not a file: {path}",
                data={
                    "path": str(path),
                    "exists": True,
                    "is_file": False,
                },
                error=f"Not a file: {path}",
            )

        return ToolResult(
            success=True,
            message=f"Verified file exists: {path.name}",
            data={
                "path": str(path),
                "exists": True,
                "is_file": True,
                "size_bytes": path.stat().st_size,
            },
            evidence=[str(path)],
        )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "list_files":
            return self._list_files(arguments)

        if action == "check_file_exists":
            return self._check_file_exists(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown filesystem action: {action}",
        )

    def _list_files(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path", ".")

        path = Path(raw_path).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Path does not exist: {path}",
            )

        files = []

        for item in path.rglob("*"):
            if not item.is_file():
                continue

            suffix = item.suffix.lower()

            if suffix in {".xlsx", ".xlsm", ".xls"}:
                file_type = "excel"
            elif suffix == ".docx":
                file_type = "word"
            elif suffix == ".pdf":
                file_type = "pdf"
            elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                file_type = "image"
            elif suffix in {".csv", ".txt"}:
                file_type = "text"
            else:
                file_type = "other"

            files.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "type": file_type,
                    "extension": suffix,
                    "size_bytes": item.stat().st_size,
                }
            )

        return ToolResult(
            success=True,
            message=f"Found {len(files)} files",
            data={
                "root": str(path),
                "files": files,
            },
            evidence=[str(path)],
        )
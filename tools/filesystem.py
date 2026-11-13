from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.models import ToolResult
from tools.base import Tool


class FilesystemTool(Tool):
    name = "filesystem"

    actions = (
        "list_files",
        "copy_file",
    )

    def run(
        self,
        action: str,
        arguments: dict[str, Any],
    ) -> ToolResult:

        if action == "list_files":
            return self._list_files(arguments)

        if action == "copy_file":
            return self._copy_file(arguments)

        return ToolResult(
            success=False,
            error=f"Unknown filesystem action: {action}",
        )

    def _copy_file(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_source = arguments.get("path")
        raw_destination = arguments.get("destination_path")

        if not raw_source or not raw_destination:
            return ToolResult(
                success=False,
                error=(
                    "copy_file requires 'path' and "
                    "'destination_path'."
                ),
            )

        source = Path(str(raw_source)).resolve()
        destination = Path(str(raw_destination)).resolve()

        if not source.is_file():
            return ToolResult(
                success=False,
                error=f"Source file not found: {source}",
            )

        overwrite = bool(arguments.get("overwrite", True))

        if destination.exists() and not overwrite:
            return ToolResult(
                success=False,
                error=f"Destination already exists: {destination}",
            )

        try:
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            import shutil

            shutil.copy2(source, destination)

        except OSError as exc:
            return ToolResult(
                success=False,
                error=f"Failed to copy file: {exc}",
            )

        return ToolResult(
            success=True,
            message=(
                f"Copied {source.name} to {destination.name}"
            ),
            data={
                "path": str(destination),
                "source": str(source),
                "size_bytes": destination.stat().st_size,
            },
            evidence=[str(destination)],
        )

    def _list_files(
        self,
        arguments: dict[str, Any],
    ) -> ToolResult:

        raw_path = arguments.get("path", ".")

        path = Path(str(raw_path)).resolve()

        if not path.exists():
            return ToolResult(
                success=False,
                error=f"Path does not exist: {path}",
            )

        files = []

        for item in sorted(path.rglob("*")):
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
            elif suffix in {".csv", ".txt", ".md", ".json"}:
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

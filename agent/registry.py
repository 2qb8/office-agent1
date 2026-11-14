from __future__ import annotations

from tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name}")

        return self._tools[name]

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())


def build_registry() -> ToolRegistry:
    """The registry every entry point uses: the command line and the window."""

    from tools.excel import ExcelTool
    from tools.filesystem import FilesystemTool
    from tools.screenshot import ScreenshotTool
    from tools.table import TableTool
    from tools.text import TextTool
    from tools.word import WordTool

    registry = ToolRegistry()

    for tool in (
        ExcelTool(),
        WordTool(),
        TextTool(),
        TableTool(),
        FilesystemTool(),
        ScreenshotTool(),
    ):
        registry.register(tool)

    return registry
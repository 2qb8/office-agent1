from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.models import ToolResult


class Tool(ABC):
    name: str

    @abstractmethod
    def run(self, action: str, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError
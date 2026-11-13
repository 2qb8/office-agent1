from __future__ import annotations

import sys
from pathlib import Path

from agent.registry import ToolRegistry
from agent.runtime import AgentRuntime
from tools.filesystem import FilesystemTool
from tools.excel import ExcelTool
from tools.word import WordTool

def build_registry() -> ToolRegistry:

    registry = ToolRegistry()

    registry.register(
    ExcelTool()
    )

    registry.register(
        FilesystemTool()
    )

    registry.register(WordTool())

    return registry


def main() -> int:

    if len(sys.argv) != 2:
        print(
            "Usage:\n"
            "  python run.py <job-directory>"
        )
        return 1

    job_path = Path(
        sys.argv[1]
    )

    try:

        registry = build_registry()

        runtime = AgentRuntime(
            job_path,
            registry,
        )


        state = runtime.run()

        print()
        print(
            f"Job status: {state.status.value}"
        )

        if state.failed_steps:
            print(
                "Failed steps:",
                ", ".join(
                    state.failed_steps
                ),
            )

            return 1

        return 0

    except Exception as exc:

        print()
        print(
            f"FATAL ERROR: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from agent import __version__
from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import SPEC_TEMPLATE

__all__ = ["build_registry", "main"]


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def command_run(
    job_directory: str,
    use_ai: bool | None = None,
) -> int:
    job_path = Path(job_directory)

    try:
        runtime = AgentRuntime(
            job_path,
            build_registry(),
        )

        state = runtime.run(use_ai=use_ai)

    except Exception as exc:
        print()
        print(f"FATAL ERROR: {exc}")
        return 1

    outputs = runtime.output_files(state)

    print()

    if outputs:
        print("Generated files:")

        for path in outputs:
            print(f"  {path}")

        print()

    print(f"Job status: {state.status.value}")

    if state.failed_steps:
        failed = state.failed_steps[-1]

        print(f"Failed steps: {', '.join(state.failed_steps)}")
        print(f"Log: {runtime.job_path / 'run.log'}")

        result = state.results.get(failed)

        if result and result.error:
            print(f"Reason: {result.error}")

        return 1

    return 0


def command_init(
    job_directory: str,
    title: str | None = None,
) -> int:
    from docx import Document

    job_path = Path(job_directory).resolve()

    instruction_path = job_path / "instruction.docx"

    if instruction_path.exists():
        print(f"Instruction already exists: {instruction_path}")
        print("Delete it first if you want to start over.")
        return 1

    for name in ("inputs", "output", "evidence"):
        (job_path / name).mkdir(parents=True, exist_ok=True)

    document = Document()

    document.add_heading(
        title or f"Job: {job_path.name}",
        level=1,
    )

    document.add_paragraph(
        "Edit the YAML block below to describe what this job should do, "
        "then save the file."
    )

    document.add_paragraph(
        f"Run it with: python run.py {job_path.name}"
    )

    document.add_paragraph("```yaml")

    for line in SPEC_TEMPLATE.strip().splitlines():
        document.add_paragraph(line)

    document.add_paragraph("```")

    document.save(instruction_path)

    print(f"Created job: {job_path}")
    print(f"  instruction: {instruction_path}")
    print("  inputs:      inputs/  (put source docx/xlsx/txt here)")
    print("  outputs:     output/")
    print()
    print("Next: edit the instruction, then run:")
    print(f"  python run.py {job_directory}")

    return 0


def command_tools() -> int:
    registry = build_registry()

    for name in registry.list_tools():
        tool = registry.get(name)

        print(f"{name}")

        for action in getattr(tool, "actions", ()):
            print(f"  {action}")

    return 0


def command_ai(arguments: argparse.Namespace) -> int:
    from agent import ai_config

    if arguments.action == "setup":
        return ai_setup(arguments)

    if arguments.action == "test":
        return ai_test()

    print(ai_config.describe())

    return 0


def ai_setup(arguments: argparse.Namespace) -> int:
    from agent import ai_config
    from agent.llm_factory import PROVIDERS

    interactive = sys.stdin.isatty()

    provider = arguments.provider

    if provider is None:
        if not interactive:
            print(
                "Interactive setup needs a terminal.\n"
                "Use flags instead, for example:\n"
                "  python run.py ai setup --provider ollama\n"
                "  LLM_API_KEY=... python run.py ai setup "
                "--provider openai"
            )
            return 1

        provider = choose_provider()

    if provider not in PROVIDERS:
        print(
            f"Unknown provider '{provider}'. Choose one of: "
            f"{', '.join(sorted(PROVIDERS))}"
        )
        return 1

    preset = PROVIDERS[provider]

    base_url = arguments.base_url or (
        prompt("Endpoint", preset.base_url) if interactive else ""
    )
    model = arguments.model or (
        prompt("Model", preset.model) if interactive else ""
    )

    base_url = base_url.strip() or preset.base_url
    model = model.strip() or preset.model

    if not base_url or not model:
        print(
            "Provider 'custom' needs --base-url and --model, "
            "for example:\n"
            "  python run.py ai setup --provider custom "
            "--base-url http://localhost:8080/v1 --model my-model"
        )
        return 1

    api_key = os.environ.get("LLM_API_KEY", "").strip()

    if preset.requires_key:
        if not api_key:
            if not interactive:
                print(
                    "Set LLM_API_KEY in the environment and rerun, or "
                    "run this command in a terminal."
                )
                return 1

            api_key = getpass.getpass(
                f"{preset.label} API key (not echoed): "
            ).strip()

            if not api_key:
                print("No API key entered; nothing written.")
                return 1
        else:
            print("Using LLM_API_KEY from the environment.")
    else:
        # Local endpoints need no credentials; never copy an ambient
        # cloud key into a configuration that does not use it.
        api_key = ""

        print(f"{preset.label} needs no API key.")

    values = {
        "LLM_PROVIDER": provider,
        "LLM_BASE_URL": base_url,
        "LLM_MODEL": model,
        "LLM_API_KEY": api_key,
    }

    path = ai_config.write_config(values)

    # Make the status output below reflect what was just written.
    os.environ.update(values)

    print(f"Saved AI configuration to {path}")
    print()
    print(ai_config.describe())

    if arguments.no_test:
        return 0

    config = ai_config.AiConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
    )

    ok, detail = ai_config.test_connection(config)

    print()

    if ok:
        print(f"Connection OK (model replied: {detail})")
        return 0

    print(f"Connection failed: {detail}")
    return 1


def ai_test() -> int:
    from agent import ai_config

    if not ai_config.configured():
        print("The AI planner is not configured.")
        print()
        print(ai_config.describe())
        return 1

    print("Contacting the AI endpoint...")

    ok, detail = ai_config.test_connection(ai_config.resolve())

    if ok:
        print(f"Connection OK (model replied: {detail})")
        return 0

    print(f"Connection failed: {detail}")
    return 1


def choose_provider() -> str:
    from agent.llm_factory import PROVIDERS

    names = sorted(PROVIDERS)

    print("Choose an AI provider:")

    for index, name in enumerate(names, start=1):
        preset = PROVIDERS[name]

        suffix = "" if preset.requires_key else "  (no key needed)"

        print(f"  {index}. {name:<10} {preset.label}{suffix}")

    while True:
        answer = input("Provider [1]: ").strip() or "1"

        if answer in PROVIDERS:
            return answer

        if answer.isdigit() and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]

        print("Enter a number from the list, or a provider name.")


def prompt(label: str, default: str) -> str:
    answer = input(f"{label} [{default}]: ").strip()

    return answer or default


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="office-agent",
        description=(
            "Office automation agent: a DOCX instruction in, "
            "DOCX/TXT/XLSX files out."
        ),
    )

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Run a job directory",
    )
    run_parser.add_argument("job_directory")

    ai_group = run_parser.add_mutually_exclusive_group()
    ai_group.add_argument(
        "--ai",
        dest="use_ai",
        action="store_true",
        help="Always plan with the configured AI model",
    )
    ai_group.add_argument(
        "--no-ai",
        dest="use_ai",
        action="store_false",
        help="Never use AI; the instruction must contain a job spec",
    )
    run_parser.set_defaults(use_ai=None)

    init_parser = subparsers.add_parser(
        "init",
        help="Create a new job directory with an instruction template",
    )
    init_parser.add_argument("job_directory")
    init_parser.add_argument("--title", default=None)

    ai_parser = subparsers.add_parser(
        "ai",
        help="Configure or check the AI planner",
    )
    ai_parser.add_argument(
        "action",
        nargs="?",
        choices=["setup", "test"],
        default=None,
    )
    ai_parser.add_argument("--provider", default=None)
    ai_parser.add_argument("--base-url", dest="base_url", default=None)
    ai_parser.add_argument("--model", default=None)
    ai_parser.add_argument(
        "--no-test",
        dest="no_test",
        action="store_true",
        help="Save the configuration without testing the connection",
    )

    subparsers.add_parser(
        "tools",
        help="List tools and their actions",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"office-agent {__version__}",
    )

    return parser


def launch_gui() -> int:
    """Open the desktop window (what a double-clicked executable does)."""

    try:
        from gui import main as gui_main
    except Exception as exc:
        print(
            "The desktop window is unavailable "
            f"({exc}).\nUse: office-agent run <job-folder>"
        )
        return 1

    return gui_main()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        return launch_gui()

    # Backwards compatible: "python run.py <job-directory>".
    # Options such as --version or --help stay on the main parser.
    if (
        argv
        and not argv[0].startswith("-")
        and argv[0] not in {"run", "init", "tools", "ai"}
    ):
        argv.insert(0, "run")

    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "run":
        return command_run(
            arguments.job_directory,
            arguments.use_ai,
        )

    if arguments.command == "init":
        return command_init(
            arguments.job_directory,
            arguments.title,
        )

    if arguments.command == "ai":
        return command_ai(arguments)

    if arguments.command == "tools":
        return command_tools()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

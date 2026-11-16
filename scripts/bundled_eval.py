"""
How well does the bundled offline model plan, on the first try?

Runs the shipped example (with its plan.json removed, so the model has to
plan it) plus a handful of ordinary briefs through the bundled provider and
counts the plans that pass validation without any repair.

    OFFICE_AGENT_BUNDLED_MODEL=1 \\
    OFFICE_AGENT_LLAMA_SERVER=/path/to/llama-server \\
    python scripts/bundled_eval.py --out docs/bundled-eval.md

One model call per case, so it is slow on a CPU-only machine: expect a
couple of minutes per brief.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from agent import bundled  # noqa: E402
from agent.registry import build_registry  # noqa: E402
from agent.runtime import AgentRuntime  # noqa: E402


INVOICES = [
    ("Client", "Date", "Amount"),
    ("Acme Ltd", "2026-01-04", 1200.0),
    ("Northwind", "2026-01-09", 340.5),
    ("Acme Ltd", "2026-02-01", 800.0),
    ("Blue Ridge", "2026-02-11", 2250.75),
    ("Northwind", "2026-03-02", 90.0),
]

PRODUCTS = [
    ("Product", "Category", "Units", "Price"),
    ("Kettle", "Kitchen", 140, 29.99),
    ("Toaster", "Kitchen", 80, 39.5),
    ("Lamp", "Home", 210, 18.0),
    ("Chair", "Home", 35, 89.0),
    ("Mug", "Kitchen", 320, 6.5),
]

CONTACTS = [
    ("Name", "Email", "Company"),
    ("Ana Silva", "ana@acme.example", "Acme Ltd"),
    ("Ben Okafor", "", "Northwind"),
    ("Cara Diaz", "cara@blueridge.example", "Blue Ridge"),
    ("Dan Wu", "", "Acme Ltd"),
]

STOCK = [
    ("Item", "OnHand", "ReorderLevel"),
    ("Widget", 12, 25),
    ("Bolt", 400, 100),
    ("Nut", 8, 30),
    ("Washer", 55, 40),
]


def workbook(path: Path, sheet: str, rows: list[tuple]) -> None:
    book = Workbook()
    page = book.active
    page.title = sheet

    for row in rows:
        page.append(list(row))

    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


def brief(path: Path, paragraphs: list[str]) -> None:
    document = Document()

    for text in paragraphs:
        document.add_paragraph(text)

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)


def case_example(folder: Path) -> list[str]:
    """The shipped example, exactly as a user would get it — minus the plan."""

    source = ROOT / "examples" / "sales-pack"

    shutil.copy2(source / "instruction.docx", folder / "instruction.docx")
    shutil.copytree(source / "inputs", folder / "inputs")

    return []


def case_invoices(folder: Path) -> list[str]:
    workbook(folder / "inputs" / "invoices.xlsx", "Invoices", INVOICES)

    brief(
        folder / "instruction.docx",
        [
            "Please summarise the invoices for the finance meeting.",
            "I need a workbook with one sheet that shows the total amount "
            "per client, sorted from the largest total down.",
            "Keep it to a clean table of client and total.",
        ],
    )

    return []


def case_products(folder: Path) -> list[str]:
    workbook(folder / "inputs" / "products.xlsx", "Products", PRODUCTS)

    brief(
        folder / "instruction.docx",
        [
            "We only care about the products that actually move.",
            "Keep the rows where Units is 100 or more, and put the remaining "
            "product names and their units into a Word document I can send "
            "to the buyer.",
        ],
    )

    return []


def case_contacts(folder: Path) -> list[str]:
    path = folder / "inputs" / "contacts.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        "\n".join(",".join(row) for row in CONTACTS) + "\n",
        encoding="utf-8",
    )

    brief(
        folder / "instruction.docx",
        [
            "Clean up the contact list before the newsletter goes out.",
            "Remove anyone whose email is empty, then save the cleaned "
            "list as a CSV file.",
        ],
    )

    return []


def case_stock(folder: Path) -> list[str]:
    workbook(folder / "inputs" / "stock.xlsx", "Stock", STOCK)

    brief(
        folder / "instruction.docx",
        [
            "I need a short reorder note for the workshop.",
            "Take the items with an OnHand figure below 25 and list the item "
            "name and how many we have in a markdown file.",
        ],
    )

    return []


CASES = [
    ("sales-pack (shipped example)", case_example),
    ("invoice totals by client", case_invoices),
    ("filter products by units", case_products),
    ("clean the contact list", case_contacts),
    ("reorder note from stock", case_stock),
]


def unknown_actions(registry, plan) -> list[str]:
    """Actions the plan names that the tool does not have.

    ``validate_plan`` checks the tool name and the write targets, not the
    action, so a plan can pass validation and still be unrunnable. Counting
    only validation would flatter the model.
    """

    missing = []

    for step in plan.steps:
        supported = getattr(registry.get(step.tool), "actions", ())

        if supported and step.action not in supported:
            missing.append(f"{step.tool}.{step.action}")

    return missing


def outputs(folder: Path) -> list[str]:
    """Files the run actually produced, ignoring empty ones."""

    directory = folder / "output"

    if not directory.is_dir():
        return []

    return sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.stat().st_size > 0
    )


def run_case(name: str, build, root: Path, repair: bool = False) -> dict:
    folder = root / name.split(" ")[0]

    folder.mkdir(parents=True, exist_ok=True)
    build(folder)

    registry = build_registry()
    runtime = AgentRuntime(folder, registry)

    # Monotonic: this machine's wall clock has jumped by hours mid-run.
    started = time.monotonic()

    try:
        plan = runtime.plan(use_ai=True)
    except Exception as error:  # noqa: BLE001 - the failure is the result
        detail = " ".join(str(error).split())[:140]

        return {
            "name": name,
            "valid": False,
            "correct": False,
            "repairs": 0,
            "plan_seconds": time.monotonic() - started,
            "seconds": time.monotonic() - started,
            "steps": [],
            "outputs": [],
            "note": f"{type(error).__name__}: {detail}",
        }

    plan_seconds = time.monotonic() - started
    steps = [f"{step.tool}.{step.action}" for step in plan.steps]
    missing = unknown_actions(registry, plan)

    try:
        state = runtime.execute_plan(plan, repair=repair)
        status = getattr(state.status, "value", str(state.status))
        written = outputs(folder)
        correct = not state.failed_steps and status == "success" and bool(written)

        if correct:
            note = f"{len(plan.steps)} steps, wrote {', '.join(written)}"
        else:
            note = f"{status}: failed steps {', '.join(state.failed_steps) or 'none'}"
    except Exception as error:  # noqa: BLE001 - the failure is the result
        note = f"{type(error).__name__}: {' '.join(str(error).split())[:120]}"
        correct = False
        written = outputs(folder)

    if missing:
        note += " (planned with " + ", ".join(missing) + ")"

    return {
        "name": name,
        "valid": True,
        "correct": correct,
        "repairs": len(runtime.revisions),
        "plan_seconds": plan_seconds,
        "seconds": time.monotonic() - started,
        "steps": steps,
        "outputs": written,
        "note": note,
    }


def report(results: list[dict], out: Path | None, repair: bool) -> str:
    valid = sum(1 for item in results if item["valid"])
    correct = sum(1 for item in results if item["correct"])
    total = len(results)
    extra = sum(max(0.0, item["seconds"] - item["plan_seconds"]) for item in results)

    lines = [
        f"Bundled model eval — {bundled.MODEL_FILE}",
        f"Repair loop: {'on' if repair else 'off'}",
        f"Cases: {total}",
        f"Validated first try:  {valid} of {total} ({valid * 100 // total}%)",
        f"Correct output:       {correct} of {total} ({correct * 100 // total}%)",
        f"Time after planning:  {extra:.0f}s in total, "
        f"{extra / total:.0f}s per job",
        "",
        f"{'case':30} {'valid':6} {'ok':4} {'fix':4} {'plan':>6} {'total':>6}  note",
    ]

    for item in results:
        lines.append(
            f"{item['name']:30} "
            f"{'yes' if item['valid'] else 'no':6} "
            f"{'yes' if item['correct'] else 'no':4} "
            f"{item['repairs']:4} "
            f"{item['plan_seconds']:5.0f}s {item['seconds']:5.0f}s  {item['note']}"
        )

        if item["steps"]:
            lines.append(
                f"{'':30} {'':6} {'':4} {'':4} {'':6} {'':6}  "
                + " → ".join(item["steps"])
            )

    text = "\n".join(lines) + "\n"

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--only",
        default="",
        help="Run only cases whose name contains this text.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Let the planner correct a failed plan, as the app does.",
    )

    arguments = parser.parse_args()

    if not bundled.enabled():
        print(f"Set {bundled.FLAG_ENV}=1 to run this.", file=sys.stderr)

        return 2

    # config/.env may point at a hosted provider; this run is the bundled
    # one, and an empty base URL means the preset's own loopback address.
    os.environ["LLM_PROVIDER"] = bundled.PROVIDER
    os.environ["LLM_BASE_URL"] = ""
    os.environ["LLM_MODEL"] = ""
    os.environ.pop("LLM_FALLBACK_MODELS", None)

    print(bundled.describe(), flush=True)

    started = time.time()
    bundled.serve()

    print(f"server ready in {time.time() - started:.0f}s", flush=True)

    chosen = [
        (name, build)
        for name, build in CASES
        if arguments.only.lower() in name.lower()
    ]

    with tempfile.TemporaryDirectory(prefix="bundled-eval-") as temporary:
        results = []

        for name, build in chosen:
            print(f"… {name}", flush=True)
            result = run_case(
                name,
                build,
                Path(temporary),
                repair=arguments.repair,
            )
            results.append(result)
            print(
                f"  {result['note']} "
                f"({result['seconds']:.0f}s, {result['repairs']} fixes)",
                flush=True,
            )

    text = report(results, arguments.out, arguments.repair)

    print()
    print(text, end="")

    return 0 if all(item["correct"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

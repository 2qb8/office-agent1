"""
How well does the bundled offline model plan, on the first try?

Runs the shipped example (with its plan.json removed, so the model has to
plan it) plus a handful of ordinary briefs through the bundled provider, and
reports two separate things: whether the plan passed validation, and whether
the run left a non-empty file behind. A file is not an answer, so a case
with a content check — the invoice totals — is verified by reading its
output back, and the rest are reported as unchecked.

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


# The same quantisation at two sizes, so the comparison is the model and
# nothing else. Each hash was taken from the Hugging Face file listing.
MODELS = {
    "1.5b": {
        "file": bundled.MODEL_FILE,
        "url": bundled.MODEL_URL,
        "sha256": bundled.MODEL_SHA256,
    },
    "3b": {
        "file": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF"
            "/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf"
        ),
        "sha256": (
            "9c9f56a391a3abbd5b89d0245bf6106081bcc3173"
            "119d4229235dd9d23253f94"
        ),
    },
}


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


# What the invoice brief asks for, worked out by hand from the input rows.
INVOICE_TOTALS = {
    "Acme Ltd": 2000.0,
    "Northwind": 430.5,
    "Blue Ridge": 2250.75,
}


def check_invoice(folder: Path) -> tuple[bool, str]:
    """Read the summary back and compare it with the totals we expect.

    A non-empty file proves nothing: this checks the per-client totals and
    that they are sorted the way the brief asked, largest first.
    """

    from openpyxl import load_workbook

    produced = [
        path
        for path in (folder / "output").glob("*.xlsx")
        if path.is_file() and path.stat().st_size > 0
    ]

    if not produced:
        return False, "no workbook to check"

    page = load_workbook(produced[0]).worksheets[0]
    rows = [row for row in page.iter_rows(values_only=True) if any(row)]

    if len(rows) < 2:
        return False, "the summary has no data rows"

    found: dict[str, float] = {}

    for row in rows[1:]:
        client = str(row[0]).strip()
        try:
            found[client] = float(row[1])
        except (IndexError, TypeError, ValueError):
            return False, f"a row is not client and number: {row!r}"

    missing = sorted(set(INVOICE_TOTALS) - set(found))
    wrong = sorted(
        client
        for client, total in INVOICE_TOTALS.items()
        if client in found and abs(found[client] - total) > 0.001
    )

    if missing:
        return False, f"missing clients: {', '.join(missing)}"

    if wrong:
        detail = "; ".join(
            f"{client} {found[client]:g} instead of {INVOICE_TOTALS[client]:g}"
            for client in wrong
        )
        return False, f"wrong totals: {detail}"

    order = [found[str(row[0]).strip()] for row in rows[1:]]

    if order != sorted(order, reverse=True):
        return False, "totals are not sorted largest first"

    return True, "totals match and are sorted largest first"


def harvest(path: Path) -> str:
    """Every word and number a produced file contains, as plain text.

    The model picks its own file formats, so a check reads whatever came out
    rather than requiring one shape: workbook cells, Word paragraphs and
    tables, and the raw text of csv, markdown and txt alike.
    """

    suffix = path.suffix.lower()

    try:
        if suffix in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook

            book = load_workbook(path, data_only=True)

            return "\n".join(
                " ".join("" if cell is None else str(cell) for cell in row)
                for page in book.worksheets
                for row in page.iter_rows(values_only=True)
            )

        if suffix == ".docx":
            from docx import Document

            document = Document(path)
            parts = [paragraph.text for paragraph in document.paragraphs]

            for table in document.tables:
                for row in table.rows:
                    parts.append(" ".join(cell.text for cell in row.cells))

            return "\n".join(parts)

        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - an unreadable file is a failed check
        return ""


def check_expected(
    folder: Path,
    required: tuple[str, ...],
    forbidden: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """One produced file must hold everything asked for and nothing else.

    Per file rather than all files together: a worksheet that keeps every row
    beside a correct filtered document is not the answer the brief asked for.
    """

    produced = outputs(folder)

    if not produced:
        return False, "no file to check"

    rejected = []

    for name in produced:
        text = harvest(folder / "output" / name)

        missing = [item for item in required if item.lower() not in text.lower()]
        extra = [item for item in forbidden if item.lower() in text.lower()]

        if not missing and not extra:
            return True, f"{name} matches the brief"

        reasons = []

        if missing:
            reasons.append(f"missing {', '.join(missing)}")

        if extra:
            reasons.append(f"still has {', '.join(extra)}")

        rejected.append(f"{name} " + " and ".join(reasons))

    return False, "; ".join(rejected)


def check_products(folder: Path) -> tuple[bool, str]:
    """Units >= 100: Kettle 140, Lamp 210, Mug 320 stay; Toaster 80, Chair 35 go."""

    return check_expected(
        folder,
        required=("Kettle", "Lamp", "Mug"),
        forbidden=("Toaster", "Chair"),
    )


def check_stock(folder: Path) -> tuple[bool, str]:
    """OnHand below 25: Widget 12 and Nut 8 stay; Bolt 400 and Washer 55 go."""

    ok, note = check_expected(
        folder,
        required=("Widget", "Nut"),
        forbidden=("Bolt", "Washer"),
    )

    if not ok:
        return ok, note

    for name in outputs(folder):
        text = harvest(folder / "output" / name)
        numbers = {token.strip(".,:;()") for token in text.replace("|", " ").split()}

        if {"12", "8"} <= numbers:
            return True, f"{name} lists the two items and their quantities"

    return False, "the items are right but the quantities are not shown"


def check_contacts(folder: Path) -> tuple[bool, str]:
    """Blank emails are dropped: Ana and Cara stay, Ben and Dan go."""

    return check_expected(
        folder,
        required=("Ana Silva", "Cara Diaz"),
        forbidden=("Ben Okafor", "Dan Wu"),
    )


def check_sales(folder: Path) -> tuple[bool, str]:
    """Revenue per region from deals of 20+ units: 3530, 2740, 2240, 930."""

    produced = outputs(folder)

    if not produced:
        return False, "no file to check"

    totals = {"3530", "2740", "2240", "930"}
    rejected = []

    for name in produced:
        text = harvest(folder / "output" / name)
        numbers = {
            token.strip(".,:;()$|")
            for token in text.replace("|", " ").split()
        }

        regions = all(
            region.lower() in text.lower()
            for region in ("LatAm", "Europe", "Asia", "Africa")
        )

        if regions and totals <= numbers:
            return True, f"{name} has the four regional totals"

        rejected.append(f"{name} lacks the regional totals")

    return False, "; ".join(rejected)


CHECKS = {
    "invoice totals by client": check_invoice,
    "filter products by units": check_products,
    "reorder note from stock": check_stock,
    "clean the contact list": check_contacts,
    "sales-pack (shipped example)": check_sales,
}

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
            "produced": False,
            "verified": None,
            "check_note": "",
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
        produced = not state.failed_steps and status == "success" and bool(written)

        if produced:
            note = f"{len(plan.steps)} steps, wrote {', '.join(written)}"
        else:
            note = f"{status}: failed steps {', '.join(state.failed_steps) or 'none'}"
    except Exception as error:  # noqa: BLE001 - the failure is the result
        note = f"{type(error).__name__}: {' '.join(str(error).split())[:120]}"
        produced = False
        written = outputs(folder)

    if missing:
        note += " (planned with " + ", ".join(missing) + ")"

    # A file is not an answer. Only a case with a checker can say whether
    # the contents are right, and the rest are reported as unchecked.
    checker = CHECKS.get(name)
    verified: bool | None = None
    check_note = ""

    if checker is not None and produced:
        verified, check_note = checker(folder)

    return {
        "name": name,
        "valid": True,
        "produced": produced,
        "verified": verified,
        "check_note": check_note,
        "repairs": len(runtime.revisions),
        "plan_seconds": plan_seconds,
        "seconds": time.monotonic() - started,
        "steps": steps,
        "outputs": written,
        "note": note,
    }


def verdict(item: dict) -> str:
    if item["verified"] is True:
        return "right"

    if item["verified"] is False:
        return "wrong"

    return "-" if not item["produced"] else "unchecked"


def report(results: list[dict], out: Path | None, repair: bool) -> str:
    valid = sum(1 for item in results if item["valid"])
    produced = sum(1 for item in results if item["produced"])
    checked = sum(1 for item in results if item["verified"] is not None)
    right = sum(1 for item in results if item["verified"] is True)
    total = len(results)
    extra = sum(max(0.0, item["seconds"] - item["plan_seconds"]) for item in results)

    lines = [
        f"Bundled model eval — {bundled.MODEL_FILE}",
        f"Repair loop: {'on' if repair else 'off'}",
        f"Cases: {total}",
        f"Validated first try:  {valid} of {total} ({valid * 100 // total}%)",
        f"Produced output:      {produced} of {total} "
        f"({produced * 100 // total}%) — a non-empty file, contents not implied",
        f"Contents right:       {right} of {checked} checked "
        f"({total - checked} not checked)",
        f"Time after planning:  {extra:.0f}s in total, "
        f"{extra / total:.0f}s per job",
        "",
        f"{'case':30} {'valid':6} {'out':4} {'content':10} {'fix':4} "
        f"{'plan':>6} {'total':>6}  note",
    ]

    for item in results:
        lines.append(
            f"{item['name']:30} "
            f"{'yes' if item['valid'] else 'no':6} "
            f"{'yes' if item['produced'] else 'no':4} "
            f"{verdict(item):10} "
            f"{item['repairs']:4} "
            f"{item['plan_seconds']:5.0f}s {item['seconds']:5.0f}s  {item['note']}"
        )

        if item["check_note"]:
            lines.append(
                f"{'':30} {'':6} {'':4} {'':10} {'':4} {'':6} {'':6}  "
                f"check: {item['check_note']}"
            )

        if item["steps"]:
            lines.append(
                f"{'':30} {'':6} {'':4} {'':10} {'':4} {'':6} {'':6}  "
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
    parser.add_argument(
        "--model",
        choices=sorted(MODELS),
        default="1.5b",
        help="Which bundled model to test. Default: 1.5b.",
    )

    arguments = parser.parse_args()

    if not bundled.enabled():
        print(f"Set {bundled.FLAG_ENV}=1 to run this.", file=sys.stderr)

        return 2

    chosen_model = MODELS[arguments.model]

    bundled.MODEL_FILE = chosen_model["file"]
    bundled.MODEL_URL = chosen_model["url"]
    bundled.MODEL_SHA256 = chosen_model["sha256"]

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

    return 0 if all(item["verified"] is True for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

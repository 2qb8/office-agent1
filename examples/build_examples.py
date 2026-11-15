"""
Build the ready-to-run example job in examples/sales-pack/.

Run it once after cloning:

    python examples/build_examples.py

It creates the instruction.docx, the source workbook and a note file.
Generated files are committed so the example also works without this
script.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font


ROOT = Path(__file__).resolve().parent
JOB = ROOT / "sales-pack"

if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from agent.planfile import fingerprint, save_plan  # noqa: E402
from agent.profile import profile_packet  # noqa: E402
from agent.spec import build_plan_from_text  # noqa: E402


# The example ships two ways to plan the same job: the prose brief a person
# would write (instruction.docx) and this spec, which produces the committed
# plan.json so the example also runs with no model and no key.
EXAMPLE_SPEC = """\
title: Monthly sales pack

metadata:
  author: Sales Operations
  keywords: sales, report, monthly

steps:
  - id: sales
    tool: excel
    action: read_table
    arguments:
      path: inputs/sales.xlsx
      sheet: Sales

  - id: big_deals
    tool: table
    action: filter
    arguments:
      headers: $sales.headers
      rows: $sales.rows
      column: Units
      op: ">="
      value: 20

  - id: by_region
    tool: table
    action: aggregate
    arguments:
      headers: $big_deals.headers
      rows: $big_deals.rows
      group_by: Region
      column: Revenue
      op: sum

  - id: notes
    tool: word
    action: read_table
    arguments:
      path: inputs/summary.docx
      table: 0

  - id: notes_xlsx
    tool: excel
    action: create_workbook
    arguments:
      output_path: output/docx-table.xlsx
      sheets:
        - name: Summary
          headers: $notes.headers
          rows: $notes.rows

  - id: notes_csv
    tool: text
    action: write
    arguments:
      output_path: output/docx-table.csv
      headers: $notes.headers
      rows: $notes.rows

  - id: summary
    tool: excel
    action: create_workbook
    arguments:
      output_path: output/region-summary.xlsx
      sheets:
        - name: Region totals
          headers: $by_region.headers
          rows: $by_region.rows

  - id: report
    tool: word
    action: create_document
    arguments:
      output_path: output/sales-report.docx
      elements:
        - type: heading
          text: Monthly Sales Pack
          level: 1
        - type: paragraph
          text: Deals of 20 units or more, grouped by region.
        - type: heading
          text: Region totals
          level: 2
        - type: table
          headers: $by_region.headers
          rows: $by_region.rows
        - type: heading
          text: Large deals
          level: 2
        - type: table
          headers: $big_deals.headers
          rows: $big_deals.rows

  - id: report_text
    tool: word
    action: export_text
    arguments:
      path: output/sales-report.docx
      output_path: output/sales-report.txt

  - id: deals_csv
    tool: text
    action: write
    arguments:
      output_path: output/big-deals.csv
      headers: $big_deals.headers
      rows: $big_deals.rows

  - id: report_preview
    tool: screenshot
    action: document
    arguments:
      path: output/sales-report.docx
      output_path: evidence/sales-report.png

  - id: notes_copy
    tool: filesystem
    action: copy_file
    arguments:
      path: inputs/notes.txt
      destination_path: output/notes.txt
"""

SALES_ROWS = [
    ["Region", "Product", "Units", "Revenue"],
    ["LatAm", "Widget A", 32, 1280.0],
    ["LatAm", "Widget B", 18, 540.0],
    ["LatAm", "Widget C", 45, 2250.0],
    ["Europe", "Widget A", 21, 840.0],
    ["Europe", "Widget B", 12, 360.0],
    ["Europe", "Widget C", 38, 1900.0],
    ["Asia", "Widget A", 26, 1040.0],
    ["Asia", "Widget B", 9, 270.0],
    ["Asia", "Widget C", 24, 1200.0],
    ["Africa", "Widget A", 11, 440.0],
    ["Africa", "Widget B", 31, 930.0],
    ["Africa", "Widget C", 6, 300.0],
]

SUMMARY_TABLE_ROWS = [
    ["Metric", "Value"],
    ["Open deals", "7"],
    ["Pipeline", "12500"],
]

NOTES = """\
Monthly sales pack

Sources:
- inputs/sales.xlsx, worksheet "Sales".
- Deals are counted when Units >= 20.
- Revenue is already net of discounts.
"""

# The brief, in the order it reads: prose paragraphs and a bullet list.
BRIEF = [
    (
        "normal",
        "Please build this month's regional sales pack for Thursday's "
        "management meeting. The numbers are in inputs/sales.xlsx, "
        "worksheet \"Sales\".",
    ),
    (
        "normal",
        "A deal counts as large when it has 20 units or more. Revenue "
        "there is already net of discounts, so leave it as it is.",
    ),
    ("normal", "What I need in output/:"),
    (
        "bullet",
        "region-summary.xlsx \u2014 revenue per region from the large deals, "
        "one clean sheet with the region table.",
    ),
    (
        "bullet",
        "sales-report.docx \u2014 a short report: the title, one line "
        "explaining what the reader is looking at, the region table, and a "
        "section listing the large deals.",
    ),
    ("bullet", "sales-report.txt \u2014 the same report as plain text."),
    (
        "bullet",
        "big-deals.csv \u2014 the large deals, for the team that lives in "
        "spreadsheets.",
    ),
    (
        "bullet",
        "docx-table.xlsx and docx-table.csv \u2014 the small table inside "
        "inputs/summary.docx, written out both ways.",
    ),
    ("bullet", "notes.txt \u2014 the notes file copied across untouched."),
    (
        "normal",
        "Also drop a PNG preview of the finished report into evidence/ for "
        "the deck, and set the author to \"Sales Operations\" with the "
        "keywords sales, report, monthly.",
    ),
]


def build_instruction() -> None:
    """Write the brief the way somebody would actually hand the job over."""

    document = Document()

    document.add_heading("Monthly sales pack", level=1)

    for kind, line in BRIEF:
        document.add_paragraph(
            line,
            style="List Bullet" if kind == "bullet" else None,
        )

    document.save(JOB / "instruction.docx")


def build_plan() -> None:
    """Write plan.json for the committed brief.

    The plan is generated from the spec stored in this file, so the prose
    brief people read and the plan the job runs cannot drift apart while
    both stay in one place. A saved plan only runs while the packet it was
    made from is unchanged, so this is regenerated whenever the example
    changes.
    """

    plan = build_plan_from_text(EXAMPLE_SPEC, JOB)

    profile = profile_packet(
        JOB,
        JOB / "instruction.docx",
    )

    path = save_plan(
        JOB,
        plan,
        fingerprint(profile),
        source="spec",
    )

    print(f"Example plan: {path}")


def build_inputs() -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Sales"

    for row in SALES_ROWS:
        worksheet.append(row)

    for cell in worksheet[1]:
        cell.font = Font(bold=True)

    workbook.save(JOB / "inputs" / "sales.xlsx")

    (JOB / "inputs" / "notes.txt").write_text(
        NOTES,
        encoding="utf-8",
    )

    document = Document()
    document.add_paragraph("Pipeline summary")

    table = document.add_table(
        rows=len(SUMMARY_TABLE_ROWS),
        cols=len(SUMMARY_TABLE_ROWS[0]),
    )

    for row_index, row in enumerate(SUMMARY_TABLE_ROWS):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value

    document.save(JOB / "inputs" / "summary.docx")


def main() -> None:
    for name in ("inputs", "output", "evidence"):
        (JOB / name).mkdir(parents=True, exist_ok=True)

    build_inputs()
    build_instruction()
    build_plan()

    print(f"Example job ready: {JOB}")


if __name__ == "__main__":
    main()

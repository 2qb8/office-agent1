"""
Build the ready-to-run example job in examples/sales-pack/.

Run it once after cloning:

    python examples/build_examples.py

It creates the instruction.docx, the source workbook and a note file.
Generated files are committed so the example also works without this
script.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font


ROOT = Path(__file__).resolve().parent
JOB = ROOT / "sales-pack"

INSTRUCTION_YAML = """\
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


def build_instruction() -> None:
    document = Document()

    document.add_heading("Monthly sales pack", level=1)

    document.add_paragraph(
        "Build the regional sales pack from inputs/sales.xlsx."
    )

    document.add_paragraph(
        "The YAML block below is the job spec. Edit it and re-run "
        "the job to change the output."
    )

    document.add_paragraph("```yaml")

    for line in INSTRUCTION_YAML.strip().splitlines():
        document.add_paragraph(line)

    document.add_paragraph("```")

    document.save(JOB / "instruction.docx")


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

    print(f"Example job ready: {JOB}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook

from agent.runtime import AgentRuntime
from run import build_registry


INSTRUCTION = """\
Quarterly pack

Build the quarterly pack from inputs/sales.xlsx and the summary table
in inputs/summary.docx.

```yaml
title: Quarterly pack

steps:
  - id: sales
    tool: excel
    action: read_table
    arguments:
      path: inputs/sales.xlsx
      sheet: Sales

  - id: notes
    tool: word
    action: read_table
    arguments:
      path: inputs/summary.docx
      table: 0

  - id: totals
    tool: table
    action: aggregate
    arguments:
      headers: $sales.headers
      rows: $sales.rows
      group_by: Region
      column: Revenue
      op: sum

  - id: report
    tool: word
    action: create_document
    arguments:
      output_path: output/quarterly-report.docx
      elements:
        - type: heading
          text: Quarterly pack
          level: 1
        - type: table
          headers: $totals.headers
          rows: $totals.rows
        - type: table
          headers: $notes.headers
          rows: $notes.rows

  - id: report_text
    tool: word
    action: export_text
    arguments:
      path: output/quarterly-report.docx
      output_path: output/quarterly-report.txt

  - id: docx_table_xlsx
    tool: excel
    action: create_workbook
    arguments:
      output_path: output/summary-table.xlsx
      sheets:
        - name: Summary
          headers: $notes.headers
          rows: $notes.rows

  - id: docx_table_csv
    tool: text
    action: write
    arguments:
      output_path: output/summary-table.csv
      headers: $notes.headers
      rows: $notes.rows
```
"""


class FullJobTests(unittest.TestCase):
    def test_docx_instruction_job_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "quarterly-pack"

            self._build_inputs(job)
            self._build_instruction(job)

            runtime = AgentRuntime(job, build_registry())

            with redirect_stdout(io.StringIO()):
                state = runtime.run()

            self.assertEqual(state.status.value, "success")
            self.assertEqual(state.failed_steps, [])
            self.assertEqual(
                state.completed_steps,
                [
                    "sales",
                    "notes",
                    "totals",
                    "report",
                    "report_text",
                    "docx_table_xlsx",
                    "docx_table_csv",
                ],
            )

            output = job / "output"

            for name in (
                "quarterly-report.docx",
                "quarterly-report.txt",
                "summary-table.xlsx",
                "summary-table.csv",
            ):
                self.assertTrue((output / name).is_file(), name)

            # The DOCX table drove the XLSX output.
            workbook = load_workbook(output / "summary-table.xlsx")

            self.assertEqual(workbook.sheetnames, ["Summary"])

            values = [
                list(row)
                for row in workbook["Summary"].iter_rows(
                    values_only=True
                )
            ]

            self.assertEqual(
                values,
                [
                    ["Region", "Note"],
                    ["North", "on track"],
                    ["South", "late"],
                ],
            )

            workbook.close()

            # ... and the CSV output.
            csv_text = (output / "summary-table.csv").read_text(
                encoding="utf-8"
            )

            self.assertIn("Region,Note", csv_text)
            self.assertIn("South,late", csv_text)

            # The report contains the aggregated region totals.
            report = Document(output / "quarterly-report.docx")

            self.assertEqual(
                [cell.text for cell in report.tables[0].rows[0].cells],
                ["Region", "sum(Revenue)"],
            )

            totals = [
                [cell.text for cell in row.cells]
                for row in report.tables[0].rows[1:]
            ]

            self.assertIn(["North", "125"], totals)
            self.assertIn(["South", "50"], totals)

            # Run artefacts.
            self.assertTrue((job / "state.json").is_file())
            self.assertTrue((job / "run.log").is_file())

            report_json = json.loads(
                (job / "report.json").read_text(encoding="utf-8")
            )

            self.assertEqual(report_json["status"], "success")
            self.assertEqual(report_json["goal"], "Quarterly pack")
            self.assertEqual(len(report_json["steps"]), 7)
            self.assertEqual(len(report_json["outputs"]), 4)
            self.assertTrue(
                all(
                    step["status"] == "success"
                    for step in report_json["steps"]
                )
            )

    @staticmethod
    def _build_inputs(job: Path) -> None:
        for name in ("inputs", "output", "evidence"):
            (job / name).mkdir(parents=True)

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sales"
        sheet.append(["Region", "Revenue"])
        sheet.append(["North", 100])
        sheet.append(["South", 50])
        sheet.append(["North", 25])
        workbook.save(job / "inputs" / "sales.xlsx")

        document = Document()
        document.add_paragraph("Summary table")

        table = document.add_table(rows=3, cols=2)

        rows = [
            ["Region", "Note"],
            ["North", "on track"],
            ["South", "late"],
        ]

        for row_index, values in enumerate(rows):
            for column_index, value in enumerate(values):
                table.cell(row_index, column_index).text = value

        document.save(job / "inputs" / "summary.docx")

    @staticmethod
    def _build_instruction(job: Path) -> None:
        document = Document()

        for line in INSTRUCTION.strip().splitlines():
            document.add_paragraph(line)

        document.save(job / "instruction.docx")

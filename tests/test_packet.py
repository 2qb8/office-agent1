"""A folder of loose files is one packet, and inputs are edited by copy."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook

from agent.job import choose_brief, find_instruction_file
from agent.models import JobPlan, PlanStep
from agent.registry import build_registry
from agent.runtime import AgentRuntime, PlanValidationError
from tools.filesystem import FilesystemTool


SPEC = """\
title: Update the pack
steps:
  - id: copy
    tool: filesystem
    action: work_on_copy
    arguments:
      path: inputs/sales.xlsx
      output_path: output/sales-updated.xlsx

  - id: fix
    tool: excel
    action: set_cell
    arguments:
      path: $copy.path
      sheet: Sales
      cell: D2
      value: 9999
"""

LOOSE_SPEC = """\
title: Copy the loose workbook
steps:
  - id: copy
    tool: filesystem
    action: work_on_copy
    arguments:
      path: budget.xlsx
      output_path: output/budget-updated.xlsx
"""

SALES_ROWS = [
    ["Region", "Units", "Revenue", "Note"],
    ["LatAm", 32, 1280, "ok"],
    ["Asia", 26, 1040, "ok"],
]


def write_docx(path: Path, paragraphs) -> None:
    document = Document()

    for text in paragraphs:
        document.add_paragraph(text)

    document.save(path)


def write_xlsx(path: Path, rows) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"

    for row in rows:
        sheet.append(row)

    workbook.save(path)


def make_job(root: Path) -> Path:
    job = root / "packet"
    job.mkdir()

    write_docx(job / "instruction.docx", SPEC.strip().splitlines())

    (job / "inputs").mkdir()
    write_xlsx(job / "inputs" / "sales.xlsx", SALES_ROWS)

    return job


class BriefChoiceTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.job = Path(self._temp.name) / "loose"
        self.job.mkdir()

    def test_a_folder_of_loose_files_is_one_packet(self):
        write_docx(self.job / "instruction.docx", ["Please update the pack."])
        write_docx(self.job / "notes.docx", ["Some notes about the pack."])
        write_xlsx(self.job / "budget.xlsx", SALES_ROWS)

        self.assertEqual(
            find_instruction_file(self.job).name,
            "instruction.docx",
        )

    def test_the_file_named_like_a_task_wins(self):
        write_docx(
            self.job / "appendix.docx",
            ["Appendix. " * 200],
        )
        write_docx(self.job / "brief.docx", ["Do the thing."])

        self.assertEqual(
            find_instruction_file(self.job).name,
            "brief.docx",
        )

    def test_without_a_conventional_name_the_longest_document_wins(self):
        write_docx(self.job / "notes.docx", ["A short note."])
        write_docx(
            self.job / "quarterly.docx",
            ["What I need: the summary, the totals, the charts. " * 20],
        )

        self.assertEqual(
            find_instruction_file(self.job).name,
            "quarterly.docx",
        )

    def test_the_choice_is_stable(self):
        paths = [
            self.job / "b.docx",
            self.job / "a.docx",
            self.job / "c.docx",
        ]

        for path in paths:
            write_docx(path, ["Same length text."])

        self.assertEqual(
            choose_brief(paths).name,
            "a.docx",
        )

    def test_a_single_document_is_the_brief(self):
        write_docx(self.job / "handover.docx", ["Only one file."])

        self.assertEqual(
            find_instruction_file(self.job).name,
            "handover.docx",
        )

    def test_a_folder_with_no_document_still_explains_itself(self):
        write_xlsx(self.job / "budget.xlsx", SALES_ROWS)

        with self.assertRaises(FileNotFoundError) as caught:
            find_instruction_file(self.job)

        self.assertIn("No brief found", str(caught.exception))

    def test_the_rest_of_the_loose_files_are_packet_content(self):
        write_docx(
            self.job / "instruction.docx",
            LOOSE_SPEC.strip().splitlines(),
        )
        write_docx(self.job / "notes.docx", ["Revenue is net of discounts."])
        write_xlsx(self.job / "budget.xlsx", SALES_ROWS)

        runtime = AgentRuntime(self.job, build_registry())

        self.assertEqual(runtime.find_instruction().name, "instruction.docx")

        names = [file["name"] for file in runtime.profile()["files"]]

        self.assertEqual(sorted(names), ["budget.xlsx", "notes.docx"])

        with redirect_stdout(io.StringIO()):
            state = runtime.run()

        self.assertEqual(state.status.value, "success")

        self.assertTrue(
            (self.job / "output" / "budget-updated.xlsx").is_file()
        )

        log = (self.job / "run.log").read_text(encoding="utf-8")

        self.assertIn("Using instruction.docx as the brief", log)


class WorkOnCopyTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.root = Path(self._temp.name)
        self.job = make_job(self.root)
        self.source = self.job / "inputs" / "sales.xlsx"

    def test_the_tool_copies_and_leaves_the_source_alone(self):
        before = self.source.read_bytes()
        target = self.job / "output" / "sales-updated.xlsx"

        result = FilesystemTool().run(
            "work_on_copy",
            {"path": str(self.source), "output_path": str(target)},
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.data["path"],
            str(target.resolve()),
        )
        self.assertTrue(target.is_file())
        self.assertEqual(self.source.read_bytes(), before)

    def test_a_copy_cannot_overwrite_the_original(self):
        result = FilesystemTool().run(
            "work_on_copy",
            {
                "path": str(self.source),
                "output_path": str(self.source),
            },
        )

        self.assertFalse(result.success)
        self.assertIn("never edits the original", result.error)

    def test_a_copy_needs_an_output_path(self):
        result = FilesystemTool().run(
            "work_on_copy",
            {"path": str(self.source)},
        )

        self.assertFalse(result.success)
        self.assertIn("output_path", result.error)

    def test_a_plan_edits_the_supplied_file_without_touching_the_input(self):
        before = self.source.read_bytes()

        runtime = AgentRuntime(self.job, build_registry())

        with redirect_stdout(io.StringIO()):
            state = runtime.run()

        self.assertEqual(state.status.value, "success")

        updated = self.job / "output" / "sales-updated.xlsx"

        self.assertEqual(
            load_workbook(updated)["Sales"]["D2"].value,
            9999,
        )

        # The file that was handed over is byte-for-byte what it was.
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(
            load_workbook(self.source)["Sales"]["D2"].value,
            "ok",
        )

    def test_a_copy_outside_output_is_rejected(self):
        runtime = AgentRuntime(self.job, build_registry())

        plan = JobPlan(
            goal="Copy elsewhere",
            steps=[
                PlanStep(
                    id="copy",
                    description="copy",
                    tool="filesystem",
                    action="work_on_copy",
                    arguments={
                        "path": str(self.source),
                        "output_path": str(
                            self.job / "outside.xlsx"
                        ),
                    },
                )
            ],
        )

        with self.assertRaises(PlanValidationError) as caught:
            runtime.validate_plan(plan)

        self.assertIn(
            "must write inside output/",
            str(caught.exception),
        )


if __name__ == "__main__":
    unittest.main()

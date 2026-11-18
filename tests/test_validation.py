from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent.runtime import AgentRuntime, PlanValidationError
from agent.spec import SpecError
from run import build_registry


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.job = Path(self._temp.name)

        for name in ("inputs", "output", "evidence"):
            (self.job / name).mkdir()

        (self.job / "inputs" / "source.docx").write_bytes(
            b"not a real document"
        )

    def tearDown(self):
        self._temp.cleanup()

    def rejection(self, spec_text: str) -> str:
        instruction = self.job / "instruction.txt"
        instruction.write_text(spec_text, encoding="utf-8")

        runtime = AgentRuntime(self.job, build_registry())

        with redirect_stdout(io.StringIO()):
            with self.assertRaises(
                (PlanValidationError, SpecError)
            ) as caught:
                plan = runtime.create_plan(
                    runtime.read_instruction()
                )
                runtime.validate_plan(plan)

        return str(caught.exception)

    def test_output_must_stay_in_output_dir(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: word\n"
            "    action: create_document\n"
            "    arguments:\n"
            "      output_path: output/../../escaped.docx\n"
            "      elements: []\n"
        )

        self.assertIn("must write inside output/", message)

    def test_write_action_requires_output_path(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments: {content: hi}\n"
        )

        self.assertIn("no 'output_path'", message)

    def test_inputs_cannot_be_modified(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: word\n"
            "    action: append_elements\n"
            "    arguments:\n"
            "      path: inputs/source.docx\n"
            "      elements: [{type: paragraph, text: hi}]\n"
        )

        self.assertIn(
            "would modify a file inside inputs/",
            message,
        )

    def test_forward_reference_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments:\n"
            "      output_path: output/a.txt\n"
            "      content: $b.message\n"
            "  - id: b\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments: {output_path: output/b.txt, content: hi}\n"
        )

        self.assertIn("not an earlier step", message)

    def test_unknown_tool_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: pdf\n"
            "    action: merge\n"
            "    arguments: {}\n"
        )

        self.assertIn("unregistered tool", message)

    def test_unknown_action_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: word\n"
            "    action: send_document\n"
            "    arguments: {output_path: output/a.docx}\n"
        )

        self.assertIn("unknown action", message)
        self.assertIn("word.send_document", message)
        self.assertIn("create_document", message)

    def test_a_markdown_path_for_the_word_tool_is_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: note\n"
            "    tool: word\n"
            "    action: create_document\n"
            "    arguments:\n"
            "      output_path: output/note.md\n"
            "      elements: []\n"
        )

        self.assertIn("writes note.md with word.create_document", message)
        self.assertIn(".docx", message)

    def test_a_csv_for_the_excel_writer_is_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: rows\n"
            "    tool: excel\n"
            "    action: create_workbook\n"
            "    arguments:\n"
            "      output_path: output/rows.csv\n"
            "      sheets: []\n"
        )

        self.assertIn("writes rows.csv", message)

    def test_a_sort_on_a_column_the_aggregate_did_not_make_is_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: sales\n"
            "    tool: excel\n"
            "    action: read_table\n"
            "    arguments: {path: inputs/sales.xlsx, sheet: Sales}\n"
            "  - id: totals\n"
            "    tool: table\n"
            "    action: aggregate\n"
            "    arguments:\n"
            "      headers: $sales.headers\n"
            "      rows: $sales.rows\n"
            "      column: Revenue\n"
            "      op: sum\n"
            "      group_by: Region\n"
            "  - id: ordered\n"
            "    tool: table\n"
            "    action: sort\n"
            "    arguments:\n"
            "      headers: $totals.headers\n"
            "      rows: $totals.rows\n"
            "      column: Revenue\n"
        )

        self.assertIn("uses column 'Revenue'", message)
        self.assertIn("sum(Revenue)", message)

    def test_sorting_by_the_aggregate_column_passes(self):
        instruction = self.job / "instruction.txt"
        instruction.write_text(
            "steps:\n"
            "  - id: totals\n"
            "    tool: table\n"
            "    action: aggregate\n"
            "    arguments:\n"
            "      headers: [Region, Revenue]\n"
            "      rows: [[LatAm, 10]]\n"
            "      column: Revenue\n"
            "      op: sum\n"
            "      group_by: Region\n"
            "  - id: ordered\n"
            "    tool: table\n"
            "    action: sort\n"
            "    arguments:\n"
            "      headers: $totals.headers\n"
            "      rows: $totals.rows\n"
            "      column: sum(Revenue)\n"
            "      descending: true\n",
            encoding="utf-8",
        )

        runtime = AgentRuntime(self.job, build_registry())

        with redirect_stdout(io.StringIO()):
            plan = runtime.create_plan(runtime.read_instruction())
            runtime.validate_plan(plan)

        self.assertEqual(len(plan.steps), 2)

    def test_a_literal_column_that_is_not_in_literal_headers_is_rejected(self):
        message = self.rejection(
            "steps:\n"
            "  - id: low\n"
            "    tool: table\n"
            "    action: filter\n"
            "    arguments:\n"
            "      headers: [Item, Units]\n"
            "      rows: [[Bolt, 400]]\n"
            "      column: Quantity\n"
            "      op: '<'\n"
            "      value: 5\n"
        )

        self.assertIn("uses column 'Quantity'", message)
        self.assertIn("Item, Units", message)

    def test_evidence_must_stay_in_evidence_dir(self):
        message = self.rejection(
            "steps:\n"
            "  - id: a\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments:\n"
            "      output_path: output/a.txt\n"
            "      content: hi\n"
            "      evidence_path: output/a.txt\n"
        )

        self.assertIn("evidence/", message)

    def test_valid_plan_passes_validation(self):
        instruction = self.job / "instruction.txt"
        instruction.write_text(
            "steps:\n"
            "  - id: a\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments: {output_path: output/a.txt, content: hi}\n",
            encoding="utf-8",
        )

        runtime = AgentRuntime(self.job, build_registry())

        with redirect_stdout(io.StringIO()):
            plan = runtime.create_plan(
                runtime.read_instruction()
            )
            runtime.validate_plan(plan)

        self.assertEqual(len(plan.steps), 1)

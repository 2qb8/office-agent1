"""A brief that asks for an order gets a table.sort, whatever the model wrote."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from docx import Document
from openpyxl import Workbook

from agent.llm import LLM
from agent.registry import build_registry
from agent.runtime import AgentRuntime, _requested_order


BRIEF = (
    "Summarise inputs/sales.xlsx, worksheet Sales: the total units per "
    "region, sorted from the largest total down. Write the table to "
    "output/totals.txt."
)


def plan(sort: bool = False) -> dict:
    steps = [
        {
            "id": "read",
            "description": "Read the sheet",
            "tool": "excel",
            "action": "read_table",
            "arguments": {"path": "inputs/sales.xlsx", "sheet": "Sales"},
        },
        {
            "id": "totals",
            "description": "Total the units per region",
            "tool": "table",
            "action": "aggregate",
            "arguments": {
                "headers": "$read.headers",
                "rows": "$read.rows",
                "group_by": "Region",
                "column": "Units",
                "op": "sum",
            },
        },
    ]

    source = "totals"

    if sort:
        steps.append(
            {
                "id": "biggest_first",
                "description": "Biggest totals first",
                "tool": "table",
                "action": "sort",
                "arguments": {
                    "headers": "$totals.headers",
                    "rows": "$totals.rows",
                    "column": "sum(Units)",
                    "descending": True,
                },
            }
        )

        source = "biggest_first"

    steps.append(
        {
            "id": "write",
            "description": "Write the totals",
            "tool": "text",
            "action": "write",
            "arguments": {
                "output_path": "output/totals.txt",
                "headers": f"${source}.headers",
                "rows": f"${source}.rows",
            },
        }
    )

    return {"goal": "Totals per region", "steps": steps}


class ScriptedLLM(LLM):
    model = "scripted"

    def __init__(self, payload) -> None:
        self.payload = payload
        self.prompts: list = []

    def generate(self, prompt, temperature=0.0, max_tokens=None):
        self.prompts.append(prompt)

        return json.dumps(self.payload)


class OrderingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.job = Path(self._temp.name) / "job"
        self.job.mkdir(parents=True)

        document = Document()

        for line in BRIEF.splitlines():
            document.add_paragraph(line)

        document.save(self.job / "instruction.docx")

        (self.job / "inputs").mkdir()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sales"
        sheet.append(["Region", "Units"])
        sheet.append(["LatAm", 8])
        sheet.append(["EMEA", 10])
        sheet.append(["LatAm", 32])
        workbook.save(self.job / "inputs" / "sales.xlsx")

    def run_job(self, payload):
        runtime = AgentRuntime(self.job, build_registry())

        with mock.patch(
            "agent.runtime.create_llm",
            return_value=ScriptedLLM(payload),
        ):
            with redirect_stdout(io.StringIO()):
                state = runtime.run(use_ai=True)

        return runtime, state

    def saved_plan(self) -> dict:
        return json.loads(
            (self.job / "plan.json").read_text(encoding="utf-8")
        )


class RequestedOrderTests(unittest.TestCase):
    def test_an_order_is_read_from_the_brief(self):
        self.assertTrue(_requested_order("sorted from the largest total down"))
        self.assertTrue(_requested_order("Highest first, please."))
        self.assertFalse(_requested_order("sorted smallest first"))
        self.assertFalse(_requested_order("A to Z by client name"))
        self.assertIsNone(_requested_order("Totals per client, one table."))
        self.assertIsNone(_requested_order("sorted by date"))


class OrderIsAddedTests(OrderingTestCase):
    def test_a_missing_sort_is_added_and_the_sort_is_descending(self):
        runtime, state = self.run_job(plan())

        self.assertEqual(state.status.value, "success")

        ids = [step["id"] for step in self.saved_plan()["steps"]]

        self.assertEqual(ids, ["read", "totals", "sort_totals", "write"])

        sort = self.saved_plan()["steps"][2]

        self.assertEqual(sort["tool"], "table")
        self.assertEqual(sort["action"], "sort")
        self.assertEqual(sort["arguments"]["column"], "sum(Units)")
        self.assertTrue(sort["arguments"]["descending"])
        self.assertEqual(sort["arguments"]["rows"], "$totals.rows")
        self.assertEqual(sort["depends_on"], ["totals"])

        write = self.saved_plan()["steps"][3]

        self.assertEqual(write["arguments"]["rows"], "$sort_totals.rows")
        self.assertEqual(write["arguments"]["headers"], "$sort_totals.headers")

        text = (self.job / "output" / "totals.txt").read_text(encoding="utf-8")

        self.assertLess(text.index("LatAm"), text.index("EMEA"))

    def test_a_brief_without_an_order_is_left_alone(self):
        (self.job / "instruction.docx").unlink()

        document = Document()
        document.add_paragraph("Total the units per region in output/totals.txt.")
        document.save(self.job / "instruction.docx")

        runtime, state = self.run_job(plan())

        self.assertEqual(state.status.value, "success")

        ids = [step["id"] for step in self.saved_plan()["steps"]]

        self.assertEqual(ids, ["read", "totals", "write"])

    def test_an_order_with_no_direction_adds_no_sort(self):
        (self.job / "instruction.docx").unlink()

        document = Document()
        document.add_paragraph(
            "Total the units per region, sorted by region, in output/totals.txt."
        )
        document.save(self.job / "instruction.docx")

        runtime, state = self.run_job(plan())

        self.assertEqual(state.status.value, "success")

        ids = [step["id"] for step in self.saved_plan()["steps"]]

        self.assertEqual(ids, ["read", "totals", "write"])

    def test_a_plan_that_already_sorts_is_untouched(self):
        runtime, state = self.run_job(plan(sort=True))

        self.assertEqual(state.status.value, "success")

        ids = [step["id"] for step in self.saved_plan()["steps"]]

        self.assertEqual(
            ids,
            ["read", "totals", "biggest_first", "write"],
        )


if __name__ == "__main__":
    unittest.main()

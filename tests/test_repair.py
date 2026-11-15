"""A failed step goes back to the planner, at most twice, then the run resumes."""

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
from agent.runtime import MAX_REPAIRS, AgentRuntime


BRIEF = (
    "Build the totals from inputs/sales.xlsx, worksheet Sales, and write\n"
    "the rows to output/rows.txt."
)

SPEC_WITH_A_WRONG_SHEET = """\
title: Totals
steps:
  - id: read
    tool: excel
    action: read_table
    arguments:
      path: inputs/sales.xlsx
      sheet: Report
"""


def plan_with(sheet: str, prefix: bool = False) -> dict:
    """A plan that reads one sheet; ``prefix`` adds a step before it."""

    steps = []

    if prefix:
        steps.append(
            {
                "id": "start",
                "description": "Start the log",
                "tool": "text",
                "action": "write",
                "arguments": {
                    "output_path": "output/run.txt",
                    "content": "one\n",
                    "mode": "append",
                },
            }
        )

    steps.append(
        {
            "id": "read",
            "description": "Read the sheet",
            "tool": "excel",
            "action": "read_table",
            "arguments": {
                "path": "inputs/sales.xlsx",
                "sheet": sheet,
            },
        }
    )

    steps.append(
        {
            "id": "write",
            "description": "Write the rows",
            "tool": "text",
            "action": "write",
            "arguments": {
                "output_path": "output/rows.txt",
                "headers": "$read.headers",
                "rows": "$read.rows",
            },
        }
    )

    return {"goal": "Totals", "steps": steps}


BROKEN_FILE_PLAN = {
    "goal": "Read a broken workbook",
    "steps": [
        {
            "id": "read",
            "description": "Read the broken file",
            "tool": "excel",
            "action": "read_table",
            "arguments": {
                "path": "inputs/broken.xlsx",
                "sheet": "Sales",
            },
        }
    ],
}


class ScriptedLLM(LLM):
    """Answers with the payloads in order, then repeats the last one."""

    model = "scripted"

    def __init__(self, *payloads) -> None:
        self.payloads = list(payloads)
        self.prompts: list = []

    def generate(self, prompt, temperature=0.0, max_tokens=None):
        self.prompts.append(prompt)

        index = min(len(self.prompts) - 1, len(self.payloads) - 1)

        return json.dumps(self.payloads[index])

    def text_at(self, index: int) -> str:
        """Everything that was sent in one call, flattened."""

        prompt = self.prompts[index]

        if isinstance(prompt, str):
            return prompt

        return "\n".join(
            str(message.get("content", "")) for message in prompt
        )


class RepairTestCase(unittest.TestCase):
    def setUp(self):
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
        sheet.append(["LatAm", 32])
        workbook.save(self.job / "inputs" / "sales.xlsx")

    def run_job(self, llm) -> tuple[AgentRuntime, object]:
        runtime = AgentRuntime(self.job, build_registry())

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=llm,
        ):
            with redirect_stdout(io.StringIO()):
                state = runtime.run()

        return runtime, state

    def saved_plan(self) -> dict:
        return json.loads(
            (self.job / "plan.json").read_text(encoding="utf-8")
        )

    def log(self) -> str:
        return (self.job / "run.log").read_text(encoding="utf-8")


class RepairTests(RepairTestCase):
    def test_a_wrong_sheet_is_repaired_and_the_run_finishes(self):
        llm = ScriptedLLM(plan_with("Report"), plan_with("Sales"))

        runtime, state = self.run_job(llm)

        self.assertEqual(state.status.value, "success")
        self.assertTrue((self.job / "output" / "rows.txt").is_file())

        # One plan, one revision.
        self.assertEqual(len(llm.prompts), 2)

        revision_request = llm.text_at(1)

        self.assertIn("FAILED STEP: read", revision_request)
        self.assertIn("Worksheet not found", revision_request)
        self.assertIn("BRIEF", revision_request)

        saved = self.saved_plan()

        self.assertEqual(saved["source"], "api")
        self.assertEqual(len(saved["revisions"]), 1)

        revision = saved["revisions"][0]

        self.assertEqual(revision["step"], "read")
        self.assertIn("Worksheet not found", revision["error"])
        self.assertEqual(
            [step["id"] for step in revision["replaced"]],
            ["read", "write"],
        )
        self.assertEqual(saved["steps"][0]["arguments"]["sheet"], "Sales")

        self.assertIn("Repair attempt 1/2", self.log())

        report = json.loads(
            (self.job / "report.json").read_text(encoding="utf-8")
        )

        self.assertEqual(len(report["revisions"]), 1)

    def test_the_run_stops_after_two_repairs(self):
        llm = ScriptedLLM(plan_with("Report"))

        runtime, state = self.run_job(llm)

        self.assertEqual(state.status.value, "failed")
        self.assertEqual(len(llm.prompts), 1 + MAX_REPAIRS)
        self.assertIn("Repair attempt 2/2", self.log())

        saved = self.saved_plan()

        self.assertEqual(len(saved["revisions"]), MAX_REPAIRS)
        self.assertEqual(
            [revision["attempt"] for revision in saved["revisions"]],
            [1, 2],
        )
        self.assertFalse((self.job / "output" / "rows.txt").exists())

    def test_a_broken_file_is_not_a_planning_mistake(self):
        (self.job / "inputs" / "broken.xlsx").write_bytes(b"not a zip")

        llm = ScriptedLLM(BROKEN_FILE_PLAN, plan_with("Sales"))

        runtime, state = self.run_job(llm)

        self.assertEqual(state.status.value, "failed")
        self.assertEqual(
            len(llm.prompts),
            1,
            "a corrupt workbook should not be sent back to the planner",
        )
        self.assertIn("Not repairing", self.log())
        self.assertEqual(self.saved_plan()["revisions"], [])

    def test_a_spec_plan_is_never_repaired(self):
        document = Document()

        for line in SPEC_WITH_A_WRONG_SHEET.strip().splitlines():
            document.add_paragraph(line)

        document.save(self.job / "instruction.docx")

        runtime = AgentRuntime(self.job, build_registry())

        with mock.patch(
            "agent.runtime.try_create_llm",
            side_effect=AssertionError("a spec must not be redesigned"),
        ):
            with redirect_stdout(io.StringIO()):
                state = runtime.run()

        self.assertEqual(state.status.value, "failed")
        self.assertIn("not made by a model", self.log())

    def test_a_step_that_already_ran_is_not_run_again(self):
        llm = ScriptedLLM(
            plan_with("Report", prefix=True),
            plan_with("Sales", prefix=True),
        )

        runtime, state = self.run_job(llm)

        self.assertEqual(state.status.value, "success")

        # The first step appended once: resuming did not repeat it.
        self.assertEqual(
            (self.job / "output" / "run.txt").read_text(encoding="utf-8"),
            "one\n",
        )

    def test_a_revision_that_rewrites_earlier_steps_is_refused(self):
        wrong = plan_with("Report", prefix=True)

        fixed = plan_with("Sales", prefix=True)
        fixed["steps"][0]["id"] = "begin"

        llm = ScriptedLLM(wrong, fixed)

        runtime, state = self.run_job(llm)

        self.assertEqual(state.status.value, "failed")
        self.assertIn("changed steps that already ran", self.log())
        self.assertEqual(self.saved_plan()["revisions"], [])
        self.assertEqual(
            (self.job / "output" / "run.txt").read_text(encoding="utf-8"),
            "one\n",
        )


if __name__ == "__main__":
    unittest.main()

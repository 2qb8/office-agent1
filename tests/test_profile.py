"""The packet profile, the saved plan, and planning a prose brief."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from docx import Document
from openpyxl import Workbook

from agent import desktop
from agent.llm import LLM
from agent.planfile import fingerprint, load_plan, save_plan
from agent.profile import PER_FILE_CHARS, profile_packet
from agent.registry import build_registry
from agent.runtime import AgentRuntime
from agent.spec import build_plan_from_text


EXAMPLE = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "sales-pack"
)

BRIEF_PARAGRAPHS = [
    "Monthly sales pack",
    "The numbers are in inputs/sales.xlsx, worksheet \"Sales\".",
    "Only deals with 20 units or more count.",
]

SPEC = """\
title: Note
steps:
  - id: note
    tool: text
    action: write
    arguments:
      output_path: output/note.txt
      content: from the spec
"""

AI_PLAN = {
    "goal": "Note",
    "steps": [
        {
            "id": "note",
            "description": "Write the note",
            "tool": "text",
            "action": "write",
            "arguments": {
                "output_path": "output/note.txt",
                "content": "from the model",
            },
        }
    ],
}


class StubLLM(LLM):
    model = "stub-model"

    def __init__(self, payload=AI_PLAN) -> None:
        self.payload = payload
        self.prompts: list = []

    def generate(self, prompt, temperature=0.0, max_tokens=None):
        self.prompts.append(prompt)

        return json.dumps(self.payload)


def write_docx(path: Path, paragraphs, table=None) -> None:
    document = Document()

    for text in paragraphs:
        document.add_paragraph(text)

    if table:
        grid = document.add_table(
            rows=len(table),
            cols=len(table[0]),
        )

        for row_index, row in enumerate(table):
            for column_index, value in enumerate(row):
                grid.cell(row_index, column_index).text = str(value)

    document.save(path)


def make_packet(root: Path, brief=None) -> Path:
    job = root / "packet"

    (job / "inputs").mkdir(parents=True)

    write_docx(
        job / "instruction.docx",
        brief or BRIEF_PARAGRAPHS,
    )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Region", "Units", "Revenue"])
    sheet.append(["LatAm", 32, 1280])
    sheet.append(["Asia", 26, 1040])
    workbook.save(job / "inputs" / "sales.xlsx")

    write_docx(
        job / "inputs" / "summary.docx",
        ["Pipeline summary"],
        table=[["Metric", "Value"], ["Open deals", "7"]],
    )

    (job / "inputs" / "rates.csv").write_text(
        "Currency,Rate\nUSD,1\nEUR,1.1\n",
        encoding="utf-8",
    )

    (job / "inputs" / "notes.txt").write_text(
        "Revenue is net of discounts.\n",
        encoding="utf-8",
    )

    return job


class PacketTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.root = Path(self._temp.name)
        self.job = make_packet(self.root)

    def profile(self) -> dict:
        return profile_packet(
            self.job,
            self.job / "instruction.docx",
        )

    def entry(self, name: str, profile=None) -> dict:
        for file in (profile or self.profile())["files"]:
            if file["name"] == name:
                return file

        names = [file["name"] for file in self.profile()["files"]]

        raise AssertionError(f"{name} is not in the profile: {names}")


class ProfileTests(PacketTestCase):
    def test_the_brief_is_read_but_not_listed_as_an_input(self):
        profile = self.profile()

        self.assertEqual(profile["brief"]["name"], "instruction.docx")
        self.assertIn("20 units or more", profile["brief"]["text"])
        self.assertNotIn(
            "instruction.docx",
            [file["name"] for file in profile["files"]],
        )

    def test_every_file_that_travelled_with_the_brief_is_described(self):
        profile = self.profile()

        self.assertEqual(
            {file["name"] for file in profile["files"]},
            {"sales.xlsx", "summary.docx", "rates.csv", "notes.txt"},
        )
        self.assertEqual(profile["totals"]["files"], 4)
        self.assertFalse(profile["totals"]["truncated"])

    def test_an_excel_sheet_reports_headers_and_sample_rows(self):
        sheet = self.entry("sales.xlsx")["sheets"][0]

        self.assertEqual(sheet["name"], "Sales")
        self.assertEqual(
            sheet["headers"],
            ["Region", "Units", "Revenue"],
        )
        self.assertEqual(sheet["rows"], 3)
        self.assertEqual(sheet["sample_rows"][0], ["LatAm", 32, 1280])
        self.assertFalse(sheet["has_formulas"])

    def test_a_word_attachment_reports_its_table(self):
        word = self.entry("summary.docx")

        self.assertIn("Pipeline summary", word["text"])
        self.assertEqual(
            word["tables"][0]["header"],
            ["Metric", "Value"],
        )
        self.assertEqual(
            word["tables"][0]["sample_rows"],
            [["Open deals", "7"]],
        )

    def test_a_csv_reports_its_header_and_rows(self):
        table = self.entry("rates.csv")

        self.assertEqual(table["header"], ["Currency", "Rate"])
        self.assertEqual(table["rows"], 3)

    def test_a_file_beside_the_brief_is_packet_content(self):
        (self.job / "handover.csv").write_text(
            "Item,Count\nWidget,3\n",
            encoding="utf-8",
        )

        self.assertIn(
            "handover.csv",
            [file["name"] for file in self.profile()["files"]],
        )

    def test_the_jobs_own_files_are_not_packet_content(self):
        artifacts = (
            "run.log",
            "report.json",
            "state.json",
            "plan.json",
            "plan-request.md",
            "self-test.txt",
            # Written before planning starts, so it sits in the folder while
            # the packet is profiled.
            "self-test-crash.txt",
        )

        for name in artifacts:
            (self.job / name).write_text("{}", encoding="utf-8")

        names = [file["name"] for file in self.profile()["files"]]

        for name in artifacts:
            self.assertNotIn(name, names)

    def test_a_large_text_file_is_capped(self):
        (self.job / "inputs" / "long.txt").write_text(
            "x" * (PER_FILE_CHARS * 3),
            encoding="utf-8",
        )

        text = self.entry("long.txt")["text"]

        self.assertLessEqual(len(text), PER_FILE_CHARS + 40)
        self.assertIn("truncated", text)

    def test_the_fingerprint_follows_the_packet(self):
        before = fingerprint(self.profile())

        (self.job / "inputs" / "notes.txt").write_text(
            "Revenue includes discounts now.\n",
            encoding="utf-8",
        )

        self.assertNotEqual(before, fingerprint(self.profile()))


class PlanFileTests(PacketTestCase):
    def saved(self, plan):
        profile = self.profile()

        save_plan(
            self.job,
            plan,
            fingerprint(profile),
            source="spec",
        )

        return profile

    def test_a_saved_plan_round_trips_with_relative_paths(self):
        profile = self.saved(build_plan_from_text(SPEC, self.job))

        data = json.loads(
            (self.job / "plan.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            data["steps"][0]["arguments"]["output_path"],
            "output/note.txt",
        )

        plan, note, _source = load_plan(self.job, fingerprint(profile))

        self.assertIsNotNone(plan, note)
        self.assertEqual(
            plan.steps[0].arguments["output_path"],
            str((self.job / "output" / "note.txt").resolve()),
        )

    def test_an_edited_input_makes_the_saved_plan_stale(self):
        self.saved(build_plan_from_text(SPEC, self.job))

        (self.job / "inputs" / "sales.xlsx").write_bytes(
            (self.job / "inputs" / "sales.xlsx").read_bytes()
        )

        (self.job / "inputs" / "notes.txt").write_text(
            "Different note.\n",
            encoding="utf-8",
        )

        plan, note, _source = load_plan(
            self.job,
            fingerprint(self.profile()),
        )

        self.assertIsNone(plan)
        self.assertIn("out of date", note)


class DeepChangeTests(PacketTestCase):
    """The caps keep planning affordable; the digests keep it honest."""

    def save_current_plan(self) -> dict:
        profile = self.profile()

        save_plan(
            self.job,
            build_plan_from_text(SPEC, self.job),
            fingerprint(profile),
            source="spec",
        )

        return profile

    def write_sales(self, hidden: int) -> None:
        """A workbook whose differing value sits far past the sampled rows."""

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sales"
        sheet.append(["Region", "Units", "Revenue"])

        for index in range(2, 20):
            sheet.append([f"Region {index}", index, index * 10])

        sheet.append(["Hidden", 20, hidden])

        workbook.save(self.job / "inputs" / "sales.xlsx")

    def test_a_change_past_the_sampled_rows_invalidates_the_plan(self):
        self.write_sales(5000)

        before = self.save_current_plan()

        self.write_sales(6000)

        after = self.profile()

        old_sheet = self.entry("sales.xlsx", before)["sheets"][0]
        new_sheet = self.entry("sales.xlsx", after)["sheets"][0]

        # The capped description cannot see the difference...
        self.assertEqual(
            new_sheet["sample_rows"],
            old_sheet["sample_rows"],
        )
        self.assertEqual(new_sheet["rows"], old_sheet["rows"])

        # ...but the digest can, so the saved plan is not reused.
        self.assertNotEqual(
            self.entry("sales.xlsx", after)["digest"],
            self.entry("sales.xlsx", before)["digest"],
        )

        plan, note, _source = load_plan(self.job, fingerprint(after))

        self.assertIsNone(plan)
        self.assertIn("out of date", note)

    def test_a_change_past_the_character_cap_invalidates_the_plan(self):
        path = self.job / "inputs" / "long.txt"
        body = "x" * (PER_FILE_CHARS * 3)

        path.write_text(body, encoding="utf-8")

        before = self.save_current_plan()

        path.write_text(body[:-1] + "y", encoding="utf-8")

        after = self.profile()

        # Same size, same capped text, different file.
        self.assertEqual(
            self.entry("long.txt", after)["text"],
            self.entry("long.txt", before)["text"],
        )
        self.assertEqual(
            self.entry("long.txt", after)["bytes"],
            self.entry("long.txt", before)["bytes"],
        )

        plan, note, _source = load_plan(self.job, fingerprint(after))

        self.assertIsNone(plan)
        self.assertIn("out of date", note)

    def test_an_untouched_packet_still_reuses_its_plan(self):
        before = self.save_current_plan()

        # Saving the plan must not change the packet it describes.
        after = self.profile()

        self.assertEqual(fingerprint(after), fingerprint(before))

        plan, note, _source = load_plan(self.job, fingerprint(after))

        self.assertIsNotNone(plan, note)
        self.assertIn("saved plan", note)


class BriefPlanningTests(PacketTestCase):
    def prose_job(self) -> Path:
        write_docx(
            self.job / "instruction.docx",
            ["Please write output/note.txt with a short greeting."],
        )

        return self.job

    def runtime(self) -> AgentRuntime:
        return AgentRuntime(self.job, build_registry())

    def test_a_prose_brief_is_planned_from_the_packet_profile(self):
        self.prose_job()

        llm = StubLLM()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=llm,
        ):
            with redirect_stdout(io.StringIO()):
                state = self.runtime().run()

        self.assertEqual(state.status.value, "success")
        self.assertEqual(len(llm.prompts), 1)

        user = llm.prompts[0][-1]["content"]

        self.assertIn("BRIEF", user)
        self.assertIn("short greeting", user)
        self.assertIn("sales.xlsx", user)
        self.assertIn("Units", user)
        self.assertIn("Revenue", user)

    def test_the_model_plan_is_saved_for_the_next_run(self):
        self.prose_job()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=StubLLM(),
        ):
            with redirect_stdout(io.StringIO()):
                self.runtime().run()

        saved = json.loads(
            (self.job / "plan.json").read_text(encoding="utf-8")
        )

        self.assertEqual(saved["source"], "api")
        self.assertEqual(saved["model"], "stub-model")
        self.assertEqual(saved["goal"], "Note")

    def test_a_saved_plan_runs_without_asking_the_model(self):
        self.prose_job()

        llm = StubLLM()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=llm,
        ):
            with redirect_stdout(io.StringIO()):
                self.runtime().run()

        asked = len(llm.prompts)

        with mock.patch(
            "agent.runtime.try_create_llm",
            side_effect=AssertionError("the model must not be asked"),
        ):
            with redirect_stdout(io.StringIO()):
                kind, state, outputs = desktop.run_instruction(
                    self.job / "instruction.docx"
                )

        self.assertEqual(kind, "done", state)
        self.assertEqual(len(llm.prompts), asked)
        self.assertEqual(
            (self.job / "output" / "note.txt")
            .read_text(encoding="utf-8")
            .strip(),
            "from the model",
        )

    def test_an_edited_packet_is_planned_again(self):
        self.prose_job()

        first = StubLLM()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=first,
        ):
            with redirect_stdout(io.StringIO()):
                self.runtime().run()

        (self.job / "inputs" / "notes.txt").write_text(
            "A new note from the client.\n",
            encoding="utf-8",
        )

        second = StubLLM()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=second,
        ):
            with redirect_stdout(io.StringIO()):
                self.runtime().run()

        self.assertEqual(len(second.prompts), 1)

    def test_a_spec_in_the_brief_still_wins_without_a_model(self):
        write_docx(
            self.job / "instruction.docx",
            SPEC.strip().splitlines(),
        )

        with mock.patch(
            "agent.runtime.try_create_llm",
            side_effect=AssertionError("a spec needs no model"),
        ):
            with redirect_stdout(io.StringIO()):
                state = self.runtime().run()

        self.assertEqual(state.status.value, "success")
        self.assertEqual(
            (self.job / "output" / "note.txt")
            .read_text(encoding="utf-8")
            .strip(),
            "from the spec",
        )


class ShippedExampleTests(unittest.TestCase):
    """The example a new user runs first must work with no model at all."""

    def test_the_example_runs_from_its_saved_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "sales-pack"

            shutil.copytree(
                EXAMPLE,
                job,
                ignore=shutil.ignore_patterns(
                    "output",
                    "evidence",
                    "run.log",
                    "state.json",
                    "report.json",
                    "self-test.txt",
                ),
            )

            self.assertTrue((job / "plan.json").is_file())

            with mock.patch.dict(
                os.environ,
                {"LLM_PROVIDER": ""},
            ):
                with mock.patch(
                    "agent.runtime.try_create_llm",
                    side_effect=AssertionError(
                        "the example must not need a model"
                    ),
                ):
                    with redirect_stdout(io.StringIO()):
                        kind, state, outputs = desktop.run_instruction(
                            job / "instruction.docx"
                        )

            if kind != "done":
                raise AssertionError(f"the example ended as {kind!r}: {state}")

            self.assertEqual(state.status.value, "success")
            self.assertIn(
                str((job / "output" / "sales-report.docx").resolve()),
                outputs,
            )


if __name__ == "__main__":
    unittest.main()

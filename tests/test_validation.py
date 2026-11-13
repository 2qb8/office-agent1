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

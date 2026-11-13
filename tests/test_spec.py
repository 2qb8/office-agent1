from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.spec import (
    SpecError,
    build_plan_from_text,
    parse_spec,
)


FENCED_DOCUMENT = """\
Monthly report

Intro prose that is not part of the spec.

```yaml
title: Fenced job
steps:
  - id: write
    tool: text
    action: write
    arguments:
      output_path: output/notes.txt
      content: hello
```
"""


class ParseSpecTests(unittest.TestCase):
    def test_fenced_yaml_inside_prose(self):
        spec = parse_spec(FENCED_DOCUMENT)

        self.assertEqual(spec["title"], "Fenced job")
        self.assertEqual(spec["steps"][0]["id"], "write")

    def test_json_document(self):
        spec = parse_spec(
            '{"title": "Json job", "steps": [{"tool": "text", '
            '"action": "write", "arguments": {"content": "hi"}}]}'
        )

        self.assertEqual(spec["title"], "Json job")
        self.assertEqual(len(spec["steps"]), 1)

    def test_whole_document_yaml(self):
        spec = parse_spec(
            "steps:\n  - tool: text\n    action: write\n"
        )

        self.assertEqual(len(spec["steps"]), 1)

    def test_smart_quotes_are_normalized(self):
        spec = parse_spec(
            "steps:\n"
            "  - id: a\n"
            "    tool: table\n"
            "    action: filter\n"
            "    arguments:\n"
            "      op: \u201c>=\u201d\n"
            "      value: 5\n"
        )

        self.assertEqual(
            spec["steps"][0]["arguments"]["op"],
            ">=",
        )

    def test_prose_only_document_is_rejected(self):
        with self.assertRaises(SpecError) as caught:
            parse_spec(
                "Please put the numbers into a spreadsheet."
            )

        self.assertIn("job spec", str(caught.exception))


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.job_root = Path(self._temp.name)

    def tearDown(self):
        self._temp.cleanup()

    def plan(self, text: str):
        return build_plan_from_text(
            text,
            self.job_root,
            source="instruction.docx",
        )

    def test_defaults_and_argument_alias(self):
        plan = self.plan(
            "steps:\n"
            "  - tool: text\n"
            "    action: write\n"
            "    args:\n"
            "      output_path: output/a.txt\n"
            "      content: hi\n"
        )

        step = plan.steps[0]

        self.assertEqual(step.id, "step_1")
        self.assertEqual(step.description, "text.write")
        self.assertTrue(
            step.arguments["output_path"].startswith(
                str(self.job_root)
            )
        )

    def test_goal_falls_back_to_title(self):
        plan = self.plan(
            "goal: From goal\n"
            "steps:\n"
            "  - tool: text\n"
            "    action: read\n"
            "    arguments: {path: x}\n"
        )

        self.assertEqual(plan.goal, "From goal")

    def test_references_and_absolute_paths_are_kept(self):
        # A native absolute path: /etc/hosts is not absolute on Windows.
        absolute = str((self.job_root.parent / "outside.txt").resolve())

        plan = self.plan(
            "steps:\n"
            "  - id: first\n"
            "    tool: text\n"
            "    action: read\n"
            "    arguments:\n"
            f"      path: '{absolute}'\n"
            "  - id: second\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments:\n"
            "      output_path: output/b.txt\n"
            "      content: $first.text\n"
        )

        self.assertEqual(plan.steps[0].arguments["path"], absolute)
        self.assertEqual(
            plan.steps[1].arguments["content"],
            "$first.text",
        )

    def test_dependencies_accept_a_string(self):
        plan = self.plan(
            "steps:\n"
            "  - id: a\n"
            "    tool: text\n"
            "    action: read\n"
            "    arguments: {path: inputs/hosts.txt}\n"
            "  - id: b\n"
            "    tool: text\n"
            "    action: write\n"
            "    arguments: {output_path: output/b.txt, content: x}\n"
            "    depends_on: a\n"
        )

        self.assertEqual(plan.steps[1].depends_on, ["a"])

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(SpecError) as caught:
            self.plan(
                "steps:\n"
                "  - id: a\n"
                "    tool: text\n"
                "    action: read\n"
                "    arguments: {path: x}\n"
                "  - id: a\n"
                "    tool: text\n"
                "    action: read\n"
                "    arguments: {path: y}\n"
            )

        self.assertIn("Duplicate step id", str(caught.exception))

    def test_missing_steps_rejected(self):
        with self.assertRaises(SpecError):
            self.plan("title: Nothing\n")

    def test_step_without_action_rejected(self):
        with self.assertRaises(SpecError) as caught:
            self.plan("steps:\n  - id: a\n    tool: text\n")

        self.assertIn(
            "needs both 'tool' and 'action'",
            str(caught.exception),
        )

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(SpecError) as caught:
            self.plan(
                "steps:\n"
                "  - id: a\n"
                "    tool: text\n"
                "    action: read\n"
                "    arguments: {path: x}\n"
                "    depends_on: [ghost]\n"
            )

        self.assertIn("unknown step", str(caught.exception))

from __future__ import annotations

import re
import unittest

from agent.planner import SYSTEM_PROMPT
from run import build_registry


# Prompt tool lines look like "- excel.read_table(path, sheet[, ...])".
ADVERTISED_LINE = re.compile(
    r"^- ([a-z_]+)\.([a-z_]+)\(",
    re.MULTILINE,
)


class PlannerPromptTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()

        self.advertised = set(
            ADVERTISED_LINE.findall(SYSTEM_PROMPT)
        )

    def test_the_prompt_asks_for_the_instruction_language(self):
        # A Russian brief must not come back with English headings just
        # because the prompt itself is in English.
        self.assertIn(
            "in the language the brief is written in",
            SYSTEM_PROMPT,
        )

    def test_the_prompt_plans_a_prose_brief_rather_than_a_spec(self):
        # The brief is a task assignment; the YAML spec is the exception.
        self.assertIn("BRIEF: a task assignment", SYSTEM_PROMPT)
        self.assertIn("PACKET PROFILE", SYSTEM_PROMPT)
        self.assertNotIn("The instruction may be plain prose", SYSTEM_PROMPT)

    def test_the_prompt_says_a_total_adds_every_row(self):
        # The 1.5B model summed one invoice per client instead of all of
        # them; the brief's word "total" is the only cue it has.
        self.assertIn("every matching", SYSTEM_PROMPT)
        self.assertIn("is not picking one row per group", SYSTEM_PROMPT)

    def test_the_prompt_keeps_the_rows_that_have_a_value(self):
        # The 3B model inverted this filter and kept the blank emails.
        self.assertIn('op="not_empty"', SYSTEM_PROMPT)
        self.assertIn("never reach for it", SYSTEM_PROMPT)

    def test_every_registered_action_is_in_the_prompt(self):
        missing = []

        for name in self.registry.list_tools():
            tool = self.registry.get(name)

            for action in getattr(tool, "actions", ()):
                if (name, action) not in self.advertised:
                    missing.append(f"{name}.{action}")

        self.assertEqual(
            missing,
            [],
            "planner prompt does not advertise: " + ", ".join(missing),
        )

    def test_prompt_advertises_no_missing_action(self):
        unknown = []

        for name, action in sorted(self.advertised):
            try:
                tool = self.registry.get(name)
            except KeyError:
                unknown.append(f"{name}.{action}")
                continue

            if action not in getattr(tool, "actions", ()):
                unknown.append(f"{name}.{action}")

        self.assertEqual(
            unknown,
            [],
            "planner prompt advertises actions that do not exist: "
            + ", ".join(unknown),
        )

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
        # A Russian instruction must not come back with English headings just
        # because the prompt itself is in English.
        self.assertIn(
            "in the language the instruction is written",
            SYSTEM_PROMPT,
        )

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

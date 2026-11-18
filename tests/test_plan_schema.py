"""A local server enforces this schema as a grammar, so what it allows is
what the planner can say: no malformed JSON, no missing step fields, no
invented tool, and no action belonging to a different tool.
"""

from __future__ import annotations

import unittest

from agent import plan_schema
from agent.registry import build_registry


class PlanSchemaTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_registry()
        self.schema = plan_schema.plan_schema(self.registry)

    def branch_for(self, tool: str) -> dict:
        branches = self.schema["properties"]["steps"]["items"]["oneOf"]

        for branch in branches:
            if branch["properties"]["tool"]["enum"] == [tool]:
                return branch

        self.fail(f"no step branch for {tool}")

    def test_every_tool_gets_only_its_own_actions(self):
        """The union of actions was not enough: it let a step say
        filesystem.create_document, which no tool can run."""

        for name in self.registry.list_tools():
            supported = sorted(
                getattr(self.registry.get(name), "actions", ()) or ()
            )

            if not supported:
                continue

            branch = self.branch_for(name)

            self.assertEqual(
                branch["properties"]["action"]["enum"], supported
            )

    def test_a_step_must_carry_every_field_the_planner_reads(self):
        for branch in self.schema["properties"]["steps"]["items"]["oneOf"]:
            self.assertEqual(
                sorted(branch["required"]),
                [
                    "action",
                    "arguments",
                    "depends_on",
                    "description",
                    "id",
                    "tool",
                ],
            )
            self.assertFalse(branch["additionalProperties"])

            self.assertEqual(
                branch["properties"]["arguments"], {"type": "object"}
            )

    def test_the_plan_needs_a_goal_and_at_least_one_step(self):
        self.assertEqual(self.schema["required"], ["goal", "steps"])
        self.assertEqual(self.schema["properties"]["steps"]["minItems"], 1)
        self.assertFalse(self.schema["additionalProperties"])

    def test_the_request_asks_the_server_for_that_shape(self):
        request = plan_schema.response_format(self.registry)

        self.assertEqual(request["type"], "json_schema")
        self.assertEqual(
            request["json_schema"]["schema"],
            self.schema,
        )

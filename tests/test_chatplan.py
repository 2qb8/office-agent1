"""Planning in a web chatbot, and running what came back."""

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

from agent import chatplan, desktop
from agent.profile import profile_packet
from agent.registry import build_registry
from agent.runtime import AgentRuntime


BRIEF = """\
Monthly sales pack

The numbers are in inputs/sales.xlsx, worksheet "Sales". Only deals with 20
units or more count. Write the totals to output/totals.txt.
"""

REPLY = """\
Here is the plan you asked for:

```json
{
  "goal": "Totals note",
  "steps": [
    {
      "id": "totals",
      "description": "Write the totals note",
      "tool": "text",
      "action": "write",
      "arguments": {
        "output_path": "output/note.txt",
        "content": "from the chatbot"
      }
    }
  ]
}
```

Paste that into the program.
"""

ESCAPING_REPLY = """\
{
  "goal": "Outside",
  "steps": [
    {
      "id": "bad",
      "description": "Write outside output/",
      "tool": "text",
      "action": "write",
      "arguments": {
        "output_path": "../outside.txt",
        "content": "nope"
      }
    }
  ]
}
"""


def make_packet(root: Path) -> Path:
    job = root / "packet"
    job.mkdir()

    document = Document()

    for line in BRIEF.strip().splitlines():
        document.add_paragraph(line)

    document.save(job / "instruction.docx")

    (job / "inputs").mkdir()

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet.append(["Region", "Units", "Revenue"])
    sheet.append(["LatAm", 32, 1280])
    workbook.save(job / "inputs" / "sales.xlsx")

    return job


class ChatPlanTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.job = make_packet(Path(self._temp.name))
        self.instruction = self.job / "instruction.docx"

    def profile(self) -> dict:
        return profile_packet(self.job, self.instruction)


class RequestTests(ChatPlanTestCase):
    def test_the_request_carries_the_brief_and_the_packet(self):
        request = chatplan.build_request(
            BRIEF,
            self.profile(),
            "instruction.docx",
        )

        self.assertIn("BRIEF (from instruction.docx)", request)
        self.assertIn("20\nunits or more count", request)
        self.assertIn("sales.xlsx", request)
        self.assertIn("Revenue", request)
        self.assertIn("excel.read_table", request)
        self.assertIn("Reply with the JSON object only", request)

    def test_the_request_is_saved_beside_the_brief(self):
        path, text = desktop.plan_request(self.instruction)

        self.assertEqual(path.name, chatplan.REQUEST_NAME)
        self.assertEqual(path.parent, self.job)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            text,
        )

        # The request is the job's own file, not packet content.
        runtime = AgentRuntime(self.job, build_registry())

        names = [file["name"] for file in runtime.profile()["files"]]

        self.assertNotIn(chatplan.REQUEST_NAME, names)

    def test_every_registered_action_reaches_the_chatbot(self):
        # The pasted-plan path must offer exactly what the model does.
        request = chatplan.build_request(BRIEF, self.profile())

        registry = build_registry()

        for name in registry.list_tools():
            for action in getattr(registry.get(name), "actions", ()):
                self.assertIn(
                    f"{name}.{action}(",
                    request,
                    f"{name}.{action} is missing from the chat request",
                )


class ReplyTests(ChatPlanTestCase):
    def test_a_fenced_reply_with_prose_becomes_a_plan(self):
        plan = chatplan.parse_reply(REPLY)

        self.assertEqual(plan.goal, "Totals note")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool, "text")
        self.assertEqual(
            plan.steps[0].arguments["content"],
            "from the chatbot",
        )

    def test_a_bare_json_reply_becomes_a_plan(self):
        plan = chatplan.parse_reply(ESCAPING_REPLY)

        self.assertEqual(plan.goal, "Outside")

    def test_an_empty_reply_explains_itself(self):
        with self.assertRaises(RuntimeError) as caught:
            chatplan.parse_reply("   \n  ")

        self.assertIn("empty", str(caught.exception))

    def test_a_reply_that_is_not_a_plan_is_rejected(self):
        with self.assertRaises(RuntimeError):
            chatplan.parse_reply("Sorry, I cannot help with that.")

    def test_a_plan_with_no_steps_is_rejected(self):
        with self.assertRaises(RuntimeError) as caught:
            chatplan.parse_reply('{"goal": "Nothing", "steps": []}')

        self.assertIn("no steps", str(caught.exception))


class PasteTests(ChatPlanTestCase):
    def test_a_pasted_plan_is_validated_kept_and_run(self):
        before = (self.job / "inputs" / "sales.xlsx").read_bytes()

        runtime, kind, plan = desktop.plan_from_reply(
            self.instruction,
            REPLY,
        )

        if kind != "plan":
            raise AssertionError(f"the plan was rejected: {plan}")

        saved = json.loads(
            (self.job / "plan.json").read_text(encoding="utf-8")
        )

        self.assertEqual(saved["source"], "chat")
        self.assertEqual(saved["goal"], "Totals note")

        with redirect_stdout(io.StringIO()):
            run_kind, state, outputs = desktop.execute_plan(
                runtime, plan
            )

        self.assertEqual(run_kind, "done", state)
        self.assertEqual(state.status.value, "success")
        self.assertEqual(
            (self.job / "output" / "note.txt")
            .read_text(encoding="utf-8")
            .strip(),
            "from the chatbot",
        )
        self.assertEqual(
            (self.job / "inputs" / "sales.xlsx").read_bytes(),
            before,
        )
        self.assertTrue(outputs)

    def test_an_invalid_pasted_plan_comes_back_with_the_reason(self):
        runtime, kind, error = desktop.plan_from_reply(
            self.instruction,
            ESCAPING_REPLY,
        )

        self.assertEqual(kind, "invalid")
        self.assertIn("must write inside output/", str(error))
        self.assertFalse((self.job / "plan.json").exists())

    def test_junk_in_the_box_is_not_a_crash(self):
        runtime, kind, error = desktop.plan_from_reply(
            self.instruction,
            "I think a good plan would be to read the file.",
        )

        self.assertEqual(kind, "invalid")
        self.assertIn("usable JSON", str(error))

    def test_the_saved_chat_plan_runs_again_without_any_model(self):
        runtime, kind, _ = desktop.plan_from_reply(
            self.instruction,
            REPLY,
        )

        self.assertEqual(kind, "plan")

        with mock.patch(
            "agent.runtime.try_create_llm",
            side_effect=AssertionError("no model on the replay path"),
        ):
            with redirect_stdout(io.StringIO()):
                again, replay_kind, plan = desktop.plan_instruction(
                    self.instruction
                )

        self.assertEqual(replay_kind, "plan")
        self.assertEqual(plan.goal, "Totals note")


if __name__ == "__main__":
    unittest.main()

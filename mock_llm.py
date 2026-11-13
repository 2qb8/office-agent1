from __future__ import annotations

import json

from agent.llm import LLM


class MockLLM(LLM):

    def generate(
    self,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
) -> str:

        user_message = messages[-1]["content"]

        context_marker = (
            "Available job files and observations:"
        )

        context_start = user_message.find(
            context_marker
        )

        if context_start == -1:
            raise RuntimeError(
                "MockLLM could not find job context."
            )

        json_start = user_message.find(
            "{",
            context_start,
        )

        if json_start == -1:
            raise RuntimeError(
                "MockLLM could not find context JSON."
            )

        decoder = json.JSONDecoder()

        try:
            context, _ = decoder.raw_decode(
                user_message[json_start:]
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "MockLLM could not parse context JSON."
            ) from exc

        observations = context.get(
            "excel_observations",
            [],
        )

        if not observations:
            raise RuntimeError(
                "No Excel workbook observations found."
            )

        observation = observations[0]

        file_info = observation["file"]
        inspection = observation["inspection"]

        sheets = inspection.get("sheets", [])

        if not sheets:
            raise RuntimeError(
                "Workbook contains no worksheets."
            )

        sheet = sheets[0]

        sheet_name = sheet["name"]

        return json.dumps(
            {
                "goal": (
                    "Modify the discovered workbook "
                    "and verify the modification."
                ),
                "steps": [
                    {
                        "id": "write_test_value",
                        "description": (
                            "Write a temporary test value "
                            "to the first worksheet."
                        ),
                        "tool": "excel",
                        "action": "set_cell",
                        "arguments": {
                            "path": file_info["path"],
                            "sheet": sheet_name,
                            "cell": "A1",
                            "value": "AGENT_WRITE_TEST",
                        },
                        "depends_on": [],
                        "verify": True,
                    },
                    {
                        "id": "verify_write",
                        "description": (
                            "Verify the value written "
                            "to A1."
                        ),
                        "tool": "excel",
                        "action": "verify_cell",
                        "arguments": {
                            "path": file_info["path"],
                            "sheet": sheet_name,
                            "cell": "A1",
                            "expected": "AGENT_WRITE_TEST",
                        },
                        "depends_on": [
                            "write_test_value"
                        ],
                        "verify": True,
                    },
                ],
            }
        )
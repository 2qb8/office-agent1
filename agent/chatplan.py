"""Planning a job in a web chatbot, when no model is configured.

The request is everything the planner would have been given anyway — the
same instructions, the brief and the packet profile — written as one block
of text a person can paste into ChatGPT, Claude or any other chat window.
The reply comes back through the window's paste box, and is parsed with the
same code that reads a model's answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.models import JobPlan
from agent.planner import SYSTEM_PROMPT, Planner

REQUEST_NAME = "plan-request.md"

PREAMBLE = """\
I need a plan for a small Windows program that builds Word and Excel files
from a work packet. Read the instructions below, then the brief and the
packet profile, and reply with the plan as one JSON object and nothing else.
"""


def build_request(
    brief: str,
    profile: dict[str, Any] | None = None,
    brief_name: str = "the brief",
) -> str:
    """The text to paste into a chatbot."""

    parts = [
        PREAMBLE.strip(),
        "",
        "--- BEGIN INSTRUCTIONS ---",
        "",
        SYSTEM_PROMPT.strip(),
        "",
        "--- END INSTRUCTIONS ---",
        "",
        f"BRIEF (from {brief_name}):",
        "",
        brief.strip(),
    ]

    if profile:
        parts.extend(
            [
                "",
                "PACKET PROFILE (JSON):",
                "",
                "```json",
                json.dumps(
                    profile,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                "```",
            ]
        )

    parts.extend(
        [
            "",
            "Reply with the JSON object only: no prose, no code fences.",
        ]
    )

    return "\n".join(parts) + "\n"


def parse_reply(text: str) -> JobPlan:
    """Turn a chatbot's reply into a plan, or explain why it is not one."""

    cleaned = (text or "").strip()

    if not cleaned:
        raise RuntimeError(
            "The reply is empty. Paste the chatbot's answer first."
        )

    data = Planner._parse_json(cleaned)

    return JobPlan.model_validate(Planner._normalize(data))


def write_request(job_path: Path, text: str) -> Path:
    """Keep the request beside the brief, so it can be reused or edited."""

    path = Path(job_path) / REQUEST_NAME

    path.write_text(text, encoding="utf-8")

    return path

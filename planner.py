from __future__ import annotations

import json

from agent.llm import LLM
from agent.models import JobPlan


SYSTEM_PROMPT = """
You are the planning component of a local office automation agent.

Your job is to analyze a user's assignment and create an executable
plan for deterministic tools.

You are NOT allowed to perform the work yourself.

Available tools will include things such as:

- filesystem
- web_research
- excel
- word
- pdf
- browser
- screenshot
- computer

Return ONLY valid JSON.

The JSON must have this structure:

{
  "goal": "short description",
  "steps": [
    {
      "id": "unique_step_id",
      "description": "what must be accomplished",
      "tool": "tool name",
      "action": "tool action",
      "arguments": {},
      "depends_on": [],
      "verify": true
    }
  ]
}

Important:

- Break complex assignments into small steps.
- Prefer deterministic tools over computer interaction.
- Do not invent facts.
- If internet research is required, create a research step.
- If a file must be modified, create an appropriate file-tool step.
- Include verification steps where appropriate.
- Do not put prose outside the JSON.
- Use the provided job file inventory to identify input files.
- Never invent filenames.
- Use the exact paths provided by the inventory.
- Workbook inspection data is authoritative.
- Use actual worksheet names from inspection data.
- Use actual column/header names from inspection data.
- Never invent worksheet names, columns, filenames, or cell locations.
- If required information is missing, create a discovery/inspection step instead of guessing.
- Excel modifications must be followed by verification when practical.

JOB DIRECTORY RULES:

- Input files are read-only.
- Never modify files inside inputs/.
- Generated or modified user-facing files MUST be written inside output_dir.
- Evidence files MUST be written inside evidence_dir.
- Never write generated files directly into job_root.
- Use the exact output_dir path provided in the context.
- Never invent an output directory.

VERIFICATION RULES:

- Verification must inspect the actual result.
- Do not claim content was verified when only file existence was checked.
- For Word documents, use word.verify_document after word.create_document when the expected content is known.
- Use word.inspect when discovery of the actual document structure/content is needed.
- For Excel files, inspect the resulting workbook after modifications when practical.

word.verify_document:
- path: exact path of the DOCX to verify
- expected: expected document content

For generated Word documents, prefer:
1. word.create_document
2. word.verify_document

The verification step must contain the expected
paragraphs and tables that the create_document step
was instructed to create.

Verification must be deterministic.
Do not consider a document verified merely because
the file exists or can be opened.

TOOL ARGUMENT CONTRACTS:

word.create_document:
- output_path: exact path for the generated DOCX
- elements: list of document elements

word.inspect:
- path: exact path of the DOCX to inspect
- Use the output_path from the preceding create_document step
  as the path for the verification step.

DEPENDENCY ARGUMENT RULE:

When a verification step operates on a file created by a previous step,
the verification step MUST include the exact file path in its arguments.
Do not leave required arguments implicit.
"""


class Planner:

    def __init__(self, llm: LLM):
        self.llm = llm

    def create_plan(
    self,
    instruction: str,
    context: dict | None = None,
) -> JobPlan:

        context_text = ""

        if context:
            context_text = (
                "\n\nAvailable job files and observations:\n"
                + json.dumps(
                    context,
                    ensure_ascii=False,
                    indent=2,
                )
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": instruction + context_text,
            },
        ]

        response = self.llm.generate(
            messages,
            temperature=0.0,
        )

        text = response.strip()

        # Handle models that wrap JSON in ```json ... ```
        if text.startswith("```"):
            lines = text.splitlines()

            if lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)

        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Planner returned invalid JSON:\n\n"
                + response
            ) from exc

        return JobPlan.model_validate(data)
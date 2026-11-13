from __future__ import annotations

import json
import re
from typing import Any

from agent.llm import LLM
from agent.models import JobPlan


SYSTEM_PROMPT = """\
You plan file-automation jobs for a deterministic agent that works on
DOCX, XLSX, CSV and text files.

Return ONE JSON object and nothing else:

{
  "goal": "short description",
  "steps": [
    {
      "id": "unique_step_id",
      "description": "what this step does",
      "tool": "tool name",
      "action": "tool action",
      "arguments": {},
      "depends_on": []
    }
  ]
}

Steps run in order; execution stops at the first failure.

PATHS
- Paths are relative to the job folder: read from inputs/, write to output/.
- Never modify anything inside inputs/.
- Actions that create a file need output_path (filesystem.copy_file uses
  destination_path). Generated files must stay inside output/.

DATA BETWEEN STEPS
- A "$step_id.field" string is replaced by the result of an earlier step,
  for example "$sales.rows" or "$totals.headers".
- read_table results contain: headers, rows, row_count, column_count.

TOOLS AND ACTIONS
- excel.inspect(path[, sheet])
- excel.read_table(path, sheet[, header_row, max_rows])
- excel.create_workbook(output_path, sheets=[{name, headers, rows}], metadata={...})
- excel.append_rows(path, sheet, rows)
- excel.set_cell(path, sheet, cell, value)
- excel.set_range_values(path, sheet, start_cell, values)
- excel.merge_cells(path, sheet, range[, value])
- excel.format_header(path, sheet[, row])
- excel.autofit(path[, sheet])
- excel.add_image(path, sheet, image_path[, cell, width, height])
- excel.set_metadata(path, metadata={author, title, subject, keywords, category, comments})
- excel.verify_cell(path, sheet, cell, expected)
- excel.verify_workbook(path, expected={sheets: [...]})
- excel.verify_exists(path)
- word.create_document(output_path, elements=[...], metadata={...})
- word.append_elements(path, elements=[...][, output_path, metadata])
- word.replace_text(path, replacements={"{{placeholder}}": "value"}[, output_path])
- word.append_image(path, image_path[, output_path, caption, width_inches])
- word.set_metadata(path, metadata={author, title, subject, keywords, category, comments})
- word.read_table(path[, table, header_row, max_rows])
- word.inspect(path)
- word.export_text(path[, output_path])
- word.verify_document(path, expected={paragraphs, tables})
- text.write(output_path, one of content | lines | data | headers+rows[, mode])
- text.read(path)
- text.verify(path[, expected_text, expected_contains])
- table.filter(headers, rows, column, op, value)
- table.sort(headers, rows, column[, descending])
- table.select(headers, rows, columns)
- table.aggregate(headers, rows, column, op[, group_by])
- table.limit(headers, rows, limit[, offset])
- filesystem.copy_file(path, destination_path)
- filesystem.list_files(path)
- screenshot.document(path, output_path[, scale])
- screenshot.workbook(path, output_path[, sheet, scale, max_rows, max_columns])

METADATA
- DOCX and XLSX metadata fields: author, last_modified_by, title, subject,
  keywords, category, comments, created, modified (ISO 8601 dates).
- Defaults live in the agent; the environment variable
  OFFICE_AGENT_AUTHOR overrides the author. A spec can set a job-level
  'metadata' block or per-step 'metadata'; step arguments win.
- Use word.set_metadata or excel.set_metadata to change an existing file.

SCREENSHOTS
- screenshot.document and screenshot.workbook render the file to a PNG
  preview. Use them when the job should include visual evidence, then
  attach the PNG with word.append_image or excel.add_image.

WORD ELEMENTS
{"type": "heading", "text": "...", "level": 1}
{"type": "paragraph", "text": "..."}
{"type": "table", "headers": [...], "rows": [[...]]}
{"type": "bullet_list", "items": [...]} or {"type": "numbered_list", "items": [...]}
{"type": "page_break"}

OPERATORS
- filter op: ==, !=, >, >=, <, <=, contains, starts_with, ends_with, in,
  not_in, is_empty, not_empty
- aggregate op: sum, count, mean, min, max

RULES
- Use only the tools, actions and arguments listed above.
- Use exact filenames, worksheet names and column names from the job
  context. Never invent them.
- If a needed detail is unknown, add a discovery step (inspect, read_table,
  list_files) before the step that needs it.
- The instruction may be plain prose; infer the work from it and the context.
- Do not include prose, comments or code fences in your reply.
"""

FENCE_PATTERN = re.compile(
    r"```[A-Za-z0-9_+-]*[ \t]*\r?\n?(.*?)```",
    re.DOTALL,
)


class Planner:
    """Turns an instruction (and job context) into a JobPlan with an LLM."""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def create_plan(
        self,
        instruction: str,
        context: dict | None = None,
    ) -> JobPlan:

        user_content = instruction

        if context:
            user_content += (
                "\n\nJob context (JSON):\n"
                + json.dumps(
                    context,
                    ensure_ascii=False,
                    indent=2,
                )
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = self.llm.generate(
            messages,
            temperature=0.0,
        )

        data = self._parse_json(response)

        return JobPlan.model_validate(self._normalize(data))

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Parse JSON from a reply, tolerating fences and leading prose."""

        candidates = [text]

        candidates.extend(
            match.group(1)
            for match in FENCE_PATTERN.finditer(text)
        )

        start = text.find("{")

        if start >= 0:
            candidates.append(text[start:])

        for candidate in candidates:
            stripped = candidate.strip()

            if not stripped:
                continue

            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue

        if start >= 0:
            try:
                data, _ = json.JSONDecoder().raw_decode(
                    text[start:]
                )
                return data
            except json.JSONDecodeError:
                pass

        raise RuntimeError(
            "The AI planner did not return usable JSON:\n\n"
            + text[:2000]
        )

    @staticmethod
    def _normalize(data: Any) -> dict[str, Any]:
        """
        Make a model's plan safe to validate.

        Missing ids, descriptions and dependencies are filled in, unusable
        steps are dropped, and dependencies that point at later steps are
        removed (order already determines execution).
        """

        if not isinstance(data, dict):
            raise RuntimeError(
                "The AI planner returned JSON that is not an object."
            )

        raw_steps = data.get("steps") or data.get("plan") or []

        if not isinstance(raw_steps, list) or not raw_steps:
            raise RuntimeError(
                "The AI planner returned no steps."
            )

        steps: list[dict[str, Any]] = []
        used_ids: list[str] = []

        for index, raw in enumerate(raw_steps, start=1):

            if not isinstance(raw, dict):
                continue

            tool = str(raw.get("tool") or "").strip()
            action = str(raw.get("action") or "").strip()

            if not tool or not action:
                continue

            step_id = str(
                raw.get("id") or f"step_{index}"
            ).strip() or f"step_{index}"

            base_id = step_id
            suffix = 2

            while step_id in used_ids:
                step_id = f"{base_id}_{suffix}"
                suffix += 1

            arguments = (
                raw.get("arguments")
                or raw.get("args")
                or {}
            )

            if not isinstance(arguments, dict):
                arguments = {}

            depends_on = raw.get("depends_on") or []

            if isinstance(depends_on, str):
                depends_on = [depends_on]

            if not isinstance(depends_on, list):
                depends_on = []

            steps.append(
                {
                    "id": step_id,
                    "description": str(
                        raw.get("description")
                        or f"{tool}.{action}"
                    ),
                    "tool": tool,
                    "action": action,
                    "arguments": arguments,
                    "depends_on": [
                        str(dependency)
                        for dependency in depends_on
                        if str(dependency) in used_ids
                    ],
                }
            )

            used_ids.append(step_id)

        if not steps:
            raise RuntimeError(
                "The AI planner returned no usable steps."
            )

        return {
            "goal": str(
                data.get("goal")
                or data.get("title")
                or "AI plan"
            ),
            "steps": steps,
        }
